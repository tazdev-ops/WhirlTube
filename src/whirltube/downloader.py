from __future__ import annotations

import subprocess
import threading
from threading import Event
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from yt_dlp import YoutubeDL
from .ytdlp_runner import PROGRESS_TPL, parse_line, YtDlpRunner

from .models import Video


@dataclass(slots=True)
class DownloadProgress:
    bytes_total: int | None = None
    bytes_downloaded: int = 0
    speed_bps: float | None = None
    eta: int | None = None
    status: str = "queued"  # queued|downloading|finished|error
    filename: str | None = None
    error: str | None = None


@dataclass(slots=True)
class DownloadTask:
    video: Video
    dest_dir: Path
    progress: DownloadProgress = field(default_factory=DownloadProgress)
    _thread: threading.Thread | None = field(default=None, init=False)
    ydl_opts_override: dict | None = None  # allow per-download overrides
    _cancel: Event = field(default_factory=Event, init=False)
    _outtmpl_template: str | None = None

    def start(self, on_update: Callable[[DownloadProgress], None]) -> None:
        """Start the download in a background thread using yt-dlp Python API."""
        if self._thread and self._thread.is_alive():
            return

        def hook(d: dict) -> None:
            st = d.get("status")
            # Cancellation path: raising in hook aborts the download in yt-dlp
            if self._cancel.is_set():
                raise KeyboardInterrupt("Cancelled")
            if st == "downloading":
                self.progress.status = "downloading"
                self.progress.bytes_downloaded = int(d.get("downloaded_bytes") or 0)
                tb = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                self.progress.bytes_total = int(tb) or None
                sp = d.get("speed")
                self.progress.speed_bps = float(sp) if sp is not None else None
                et = d.get("eta")
                self.progress.eta = int(et) if et is not None else None
                on_update(self.progress)
            elif st == "finished":
                self.progress.status = "finished"
                self.progress.filename = d.get("filename")
                on_update(self.progress)
            # ✅ NEW: Handle 'skipped' status (when video is in archive)
            elif st == "skipped":
                self.progress.status = "finished"
                self.progress.filename = "(already downloaded, skipped)"
                on_update(self.progress)
        def run() -> None:
            self.progress.status = "downloading"
            on_update(self.progress)
            template = self._outtmpl_template or "%(title)s.%(ext)s"
            outtmpl = str(self.dest_dir / template)
            ydl_opts = {
                "quiet": True,
                "outtmpl": outtmpl,
                "progress_hooks": [hook],
                "merge_output_format": "mp4",
                "format": "bv*+ba/b",
                "nocheckcertificate": True,
                "retries": 3,
                "fragment_retries": 2,
            }
            if self.ydl_opts_override:
                ydl_opts.update(self.ydl_opts_override)
            try:
                self.dest_dir.mkdir(parents=True, exist_ok=True)
                with YoutubeDL(ydl_opts) as ydl:
                    ydl.download([self.video.url])
            except Exception as e:
                self.progress.status = "error"
                self.progress.error = str(e)
                on_update(self.progress)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """
        Best-effort cancellation. For Python API we signal via hook and let yt-dlp abort soon.
        """
        try:
            self._cancel.set()
        except Exception:
            pass
        # Thread will exit after yt-dlp aborts; no force-termination here

    def set_outtmpl_template(self, tmpl: str | None) -> None:
        try:
            self._outtmpl_template = (tmpl or "").strip() or None
        except Exception:
            self._outtmpl_template = None


class SubprocessDownloadTask:
    """
    Legacy path: run yt-dlp as a subprocess. Kept for compatibility, not used by UI.
    Now emits structured JSON lines parsed by parse_line.
    """

    def __init__(self, video: Video, dest_dir: Path, cli_args: list[str]) -> None:
        self.video = video
        self.dest_dir = dest_dir
        self.cli_args = cli_args
        self.progress = DownloadProgress(status="queued")
        self._thread: threading.Thread | None = None

    def start(self, on_update: Callable[[DownloadProgress], None]) -> None:
        if self._thread and self._thread.is_alive():
            return

        def run() -> None:
            self.progress.status = "downloading"
            on_update(self.progress)
            self.dest_dir.mkdir(parents=True, exist_ok=True)
            outtmpl = str(self.dest_dir / "%(title)s.%(ext)s")
            # Use progress-template to emit structured JSON prefixed lines (parsed by parse_line)
            args = ["yt-dlp", "-o", outtmpl] + self.cli_args + PROGRESS_TPL + ["--no-quiet", self.video.url]
            try:
                with subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                ) as proc:
                    for line in proc.stdout or []:
                        events = parse_line(line)
                        if isinstance(events, Exception):
                            self.progress.status = "error"
                            self.progress.error = str(events)
                            on_update(self.progress)
                            continue
                        if not events:
                            continue
                        for ev in events:
                            if ev.kind == "downloading":
                                payload = ev.payload
                                self.progress.status = "downloading"
                                self.progress.bytes_downloaded = int(float(payload.get("downloaded_bytes") or 0.0))
                                tb = payload.get("total_bytes") or payload.get("total_bytes_estimate") or 0
                                self.progress.bytes_total = int(tb) or None
                                sp = payload.get("speed")
                                self.progress.speed_bps = float(sp) if sp not in (None, "NA") else None
                                et = payload.get("eta")
                                self.progress.eta = int(float(et)) if et not in (None, "NA") else None
                                on_update(self.progress)
                            elif ev.kind in ("end_of_video", "end_of_playlist"):
                                pass
                    proc.wait()
                    if self.progress.status != "error":
                        self.progress.status = "finished"
                        on_update(self.progress)
            except Exception as e:
                self.progress.status = "error"
                self.progress.error = str(e)
                on_update(self.progress)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def _parse_progress(self, line: str, on_update: Callable[[DownloadProgress], None]) -> None:
        # Unused pather, left for compatibility
        on_update(self.progress)


class RunnerDownloadTask:
    """
    Advanced download using YtDlpRunner (shared JSON progress template).
    Unifies progress handling with Quick Download.
    """
    def __init__(self, video: Video, dest_dir: Path, cli_args: list[str], bin_path: str | None = None, outtmpl_template: str | None = None) -> None:
        self.video = video
        self.dest_dir = dest_dir
        self.cli_args = cli_args
        self.progress = DownloadProgress(status="queued")
        self._outtmpl_template = (outtmpl_template or "").strip() or None
        self._runner = YtDlpRunner(self._on_progress_line)
        self._watcher: threading.Thread | None = None
        self._bin_path = bin_path
        self._on_update: Callable[[DownloadProgress], None] | None = None

    def start(self, on_update: Callable[[DownloadProgress], None]) -> None:
        if self._watcher and self._watcher.is_alive():
            return
        self._on_update = on_update
        self.progress.status = "downloading"
        on_update(self.progress)
        try:
            self.dest_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.progress.status = "error"
            self.progress.error = str(e)
            on_update(self.progress)
            return

        template = self._outtmpl_template or "%(title)s.%(ext)s"
        outtmpl = str(self.dest_dir / template)
        args = ["-o", outtmpl] + self.cli_args + [self.video.url]
        
        try:
            ok = self._runner.start(args, bin_path=self._bin_path)
        except Exception as e:
            self.progress.status = "error"
            self.progress.error = f"yt-dlp spawn failed: {e}"
            if self._on_update:
                self._on_update(self.progress)
            return

        def watch() -> None:
            # Poll until process exits, then mark finished if no error
            while self._runner.is_running():
                threading.Event().wait(0.2)
            
            # Check exit code if the process object is still available
            proc = self._runner._proc
            returncode = proc.returncode if proc else None
            
            if self.progress.status != "error":
                if returncode is not None and returncode != 0:
                    # Process exited with an error code, but no error line was parsed.
                    self.progress.status = "error"
                    self.progress.error = f"yt-dlp process exited with code {returncode}. Check logs for details."
                else:
                    self.progress.status = "finished"
                
            if self._on_update:
                self._on_update(self.progress)

        self._watcher = threading.Thread(target=watch, daemon=True)
        self._watcher.start()

    def _on_progress_line(self, text: str) -> None:
        evs = parse_line(text)
        if isinstance(evs, Exception):
            self.progress.status = "error"
            self.progress.error = str(evs)
            if self._on_update:
                self._on_update(self.progress)
            return
        if not evs:
            return
        for ev in evs:
            if ev.kind == "downloading":
                payload = ev.payload
                self.progress.status = "downloading"
                try:
                    self.progress.bytes_downloaded = int(float(payload.get("downloaded_bytes") or 0.0))
                except Exception:
                    self.progress.bytes_downloaded = 0
                tb = payload.get("total_bytes") or payload.get("total_bytes_estimate") or 0
                try:
                    self.progress.bytes_total = int(float(tb)) or None
                except Exception:
                    self.progress.bytes_total = None
                sp = payload.get("speed")
                et = payload.get("eta")
                self.progress.speed_bps = float(sp) if sp not in (None, "NA") else None
                self.progress.eta = int(float(et)) if et not in (None, "NA") else None
                if self._on_update:
                    self._on_update(self.progress)
            elif ev.kind in ("end_of_video", "end_of_playlist"):
                # ✅ NEW: Detect skip due to archive
                # If we get end_of_video but never saw any download progress,
                # the video was skipped (already in archive)
                if self.progress.bytes_downloaded == 0 and self.progress.status == "downloading":
                    self.progress.status = "finished"
                    self.progress.filename = "(already downloaded, skipped)"
                    if self._on_update:
                        self._on_update(self.progress)
                # Don't set finished here; watcher thread does that
                pass

    def stop(self) -> None:
        try:
            self._runner.stop()
        except Exception:
            pass