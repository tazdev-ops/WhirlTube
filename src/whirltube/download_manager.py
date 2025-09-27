from __future__ import annotations

import logging
from pathlib import Path
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gio, Gtk

from .downloader import DownloadProgress, DownloadTask, RunnerDownloadTask
from .models import Video
from .dialogs import DownloadOptions
from .download_history import add_download

log = logging.getLogger(__name__)

class DownloadRow(Gtk.Box):
    def __init__(self, task: Any | None = None, title: str | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.task = task
        self._base_title = title or getattr(getattr(task, "video", None), "title", "Download")

        self.set_margin_top(6)
        self.set_margin_bottom(6)

        start_label = "Downloading" if task else "Queued"
        self.label = Gtk.Label(label=f"{start_label}: {self._base_title}", xalign=0.0, wrap=True)
        self.progress = Gtk.ProgressBar(show_text=True)
        self.status = Gtk.Label(label="", xalign=0.0)

        # Actions row (open folder/file)
        self.actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.btn_open_folder = Gtk.Button(label="Open folder")
        self.btn_open_folder.set_sensitive(False)
        self.btn_open_folder.connect("clicked", self._open_folder)
        self.btn_open_file = Gtk.Button(label="Open file")
        self.btn_open_file.set_sensitive(False)
        self.btn_open_file.connect("clicked", self._open_file)

        self.actions.append(self.btn_open_folder)
        self.actions.append(self.btn_open_file)

        self.append(self.label)
        self.append(self.progress)
        self.append(self.status)
        self.append(self.actions)

    def set_queued(self) -> None:
        try:
            self.label.set_text(f"Queued: {self._base_title}")
            self.progress.set_fraction(0.0)
            self.progress.set_text("")
            self.status.set_text("")
        except Exception:
            pass

    def attach_task(self, task: Any) -> None:
        self.task = task
        try:
            self.label.set_text(f"Downloading: {self._base_title}")
        except Exception:
            pass

    def update_progress(self, p: DownloadProgress) -> None:
        # Switch label when we get the first real progress
        if p.status == "downloading":
            try:
                self.label.set_text(f"Downloading: {self._base_title}")
            except Exception:
                pass
        frac = 0.0
        if p.bytes_total and p.bytes_total > 0:
            frac = min(1.0, max(0.0, p.bytes_downloaded / p.bytes_total))
        self.progress.set_fraction(frac)
        self.progress.set_text(_fmt_dl_text(p))
        self.status.set_text(_fmt_dl_status(p))

        if p.status == "finished":
            # Enable actions
            self.btn_open_folder.set_sensitive(True)
            if p.filename:
                self.btn_open_file.set_sensitive(True)

    def _open_folder(self, *_a) -> None:
        try:
            dest = getattr(self.task, "dest_dir", None)
            if isinstance(dest, Path) and dest.exists():
                Gio.AppInfo.launch_default_for_uri(f"file://{dest}", None)
        except Exception:
            pass

    def _open_file(self, *_a) -> None:
        try:
            p: DownloadProgress = getattr(self.task, "progress", None)
            dest: Path = getattr(self.task, "dest_dir", None)
            if p and p.filename:
                fp = Path(p.filename)
                # If filename isn't absolute, resolve against dest_dir
                if not fp.is_absolute() and isinstance(dest, Path):
                    fp = dest / fp
                if fp.exists():
                    Gio.AppInfo.launch_default_for_uri(f"file://{fp}", None)
        except Exception:
            pass

def _fmt_dl_text(p: DownloadProgress) -> str:
    if p.status == "finished":
        return "100% (done)"
    if p.bytes_total:
        pct = int((p.bytes_downloaded / p.bytes_total) * 100)
        return f"{pct}%"
    if p.bytes_downloaded:
        kb = p.bytes_downloaded / 1024
        return f"{kb:.1f} KiB"
    return ""

def _fmt_dl_status(p: DownloadProgress) -> str:
    if p.status == "finished":
        return f"Saved: {p.filename or ''}"
    if p.status == "error":
        return f"Error: {p.error or 'unknown'}"
    parts = []
    if p.speed_bps:
        mbps = p.speed_bps / (1024 * 1024)
        parts.append(f"{mbps:.2f} MiB/s")
    if p.eta:
        parts.append(f"ETA {p.eta:d}s")
    return " • ".join(parts)


class DownloadManager:
    def __init__(self, downloads_box: Gtk.Box, show_downloads_view: Callable[[], None], get_setting: Callable[[str], str|bool|int|None], show_error: Callable[[str], None]) -> None:
        self.downloads_box = downloads_box
        self.show_downloads_view = show_downloads_view
        self.get_setting = get_setting
        self.show_error = show_error
        self.download_dir: Path | None = None # This will be set by MainWindow
        self._max_concurrent: int = 3
        self._active: int = 0
        # queue of (video, opts, dest_dir, row)
        self._queue: list[tuple[Video, DownloadOptions, Path, DownloadRow]] = []

    def set_download_dir(self, path: Path) -> None:
        self.download_dir = path

    def set_max_concurrent(self, n: int) -> None:
        try:
            self._max_concurrent = max(1, int(n))
        except Exception:
            self._max_concurrent = 1
        self._maybe_start_next()

    def _ensure_download_dir(self, path: Path) -> bool:
        try:
            path.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            self.show_error(f"Could not create download directory: {e}")
            return False

    def start_download(self, video: Video, opts: DownloadOptions) -> None:
        dest_dir = opts.target_dir or Path(self.get_setting("download_dir") or str(self.download_dir))
        if not self._ensure_download_dir(dest_dir):
            return
        # Create a queued row immediately
        row = DownloadRow(None, title=video.title)
        row.set_queued()
        self.downloads_box.append(row)
        self.show_downloads_view()
        # Enqueue and attempt to start
        self._queue.append((video, opts, dest_dir, row))
        self._maybe_start_next()

    def _maybe_start_next(self) -> None:
        # Start as many as allowed
        while self._active < self._max_concurrent and self._queue:
            video, opts, dest_dir, row = self._queue.pop(0)
            self._start_task(video, opts, dest_dir, row)

    def _start_task(self, video: Video, opts: DownloadOptions, dest_dir: Path, row: DownloadRow) -> None:
        self._active += 1
        advanced = (
            bool(opts.extra_flags.strip())
            or bool(opts.sort_string.strip())
            or bool(opts.sb_mark.strip())
            or bool(opts.sb_remove.strip())
            or opts.embed_metadata
            or opts.embed_thumbnail
            or opts.write_thumbnail
            or bool(opts.limit_rate.strip())
            or (opts.concurrent_fragments > 0)
            or bool(opts.impersonate.strip())
            or (opts.use_cookies and bool(opts.cookies_browser.strip()))
        )

        def _on_update(p: DownloadProgress) -> None:
            GLib.idle_add(row.update_progress, p)
            if p.status in ("finished", "error"):
                # Book-keeping on main loop
                def _done():
                    try:
                        if p.status == "finished":
                            try:
                                add_download(video, dest_dir, p.filename)
                            except Exception:
                                pass
                    finally:
                        self._active = max(0, self._active - 1)
                        self._maybe_start_next()
                    return False
                GLib.idle_add(_done)

        if advanced:
            cli = opts.raw_cli_list()
            # Inject global proxy if configured and not set explicitly
            proxy = self.get_setting("http_proxy")
            if isinstance(proxy, str) and proxy.strip() and "--proxy" not in cli:
                cli = ["--proxy", proxy.strip()] + cli
            # Optional custom yt-dlp binary path from settings
            ytdlp_path = self.get_setting("ytdlp_path")
            if not isinstance(ytdlp_path, str) or not ytdlp_path.strip():
                ytdlp_path = None
            task = RunnerDownloadTask(video, dest_dir, cli, bin_path=ytdlp_path)
            row.attach_task(task)
            task.start(_on_update)
            return

        ydl_override = opts.to_ydl_opts()
        proxy = self.get_setting("http_proxy")
        if isinstance(proxy, str) and proxy.strip():
            ydl_override["proxy"] = proxy.strip()

        dl_task = DownloadTask(video=video, dest_dir=dest_dir, ydl_opts_override=ydl_override)
        row.attach_task(dl_task)
        dl_task.start(_on_update)
        return