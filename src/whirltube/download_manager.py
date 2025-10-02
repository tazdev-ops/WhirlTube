from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable
from copy import deepcopy
from functools import partial
from dataclasses import asdict
import json

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gdk, Gio, Gtk

from .downloader import DownloadProgress, DownloadTask, RunnerDownloadTask
from .models import Video
from .dialogs import DownloadOptions
from .download_history import add_download
from .util import xdg_data_dir, _download_archive_path

log = logging.getLogger(__name__)

_QUEUE_FILE = xdg_data_dir() / "download_queue.json"
MAX_CONCURRENT_DEFAULT = 3

def _notify(summary: str) -> None:
    # Best-effort desktop notification without requiring GI at import time.
    try:
        import gi
        gi.require_version("Notify", "0.7")
        from gi.repository import Notify
        Notify.init("whirltube")
        n = Notify.Notification.new(summary)
        n.show()
    except Exception:
        pass

class DownloadRow(Gtk.Box):
    def __init__(self, task: Any | None = None, title: str | None = None, on_cancel: Callable[[], None] | None = None, on_retry: Callable[[], None] | None = None, on_remove: Callable[[], None] | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.task = task
        self._base_title = title or getattr(getattr(task, "video", None), "title", "Download")
        self._on_cancel = on_cancel
        self._on_retry = on_retry
        self._on_remove = on_remove
        # Metadata for retry
        self._video: Video | None = None
        self._opts: DownloadOptions | None = None
        self._dest_dir: Path | None = None
        self._state: str = "queued" if task is None else "downloading"

        self.set_margin_top(6)
        self.set_margin_bottom(6)

        start_label = "Downloading" if task else "Queued"
        self.label = Gtk.Label(label=f"{start_label}: {self._base_title}", xalign=0.0, wrap=True)
        self.progress = Gtk.ProgressBar(show_text=True)
        self.status = Gtk.Label(label="", xalign=0.0)

        # Actions popover menu
        self.actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.menu_btn = Gtk.MenuButton(label="Actions")
        pop = Gtk.Popover()
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        self._btn_m_cancel = Gtk.Button(label="Cancel")
        self._btn_m_cancel.connect("clicked", lambda *_: self._on_cancel_clicked())
        self._btn_m_retry = Gtk.Button(label="Retry")
        self._btn_m_retry.set_sensitive(False)
        self._btn_m_retry.connect("clicked", lambda *_: self._on_retry_clicked())
        self._btn_m_remove = Gtk.Button(label="Remove")
        self._btn_m_remove.set_sensitive(False)
        self._btn_m_remove.connect("clicked", lambda *_: self._on_remove_clicked())
        self._btn_m_open_folder = Gtk.Button(label="Open folder")
        self._btn_m_open_folder.connect("clicked", self._open_folder)
        self._btn_m_show_containing = Gtk.Button(label="Show in folder")
        self._btn_m_show_containing.connect("clicked", self._show_in_folder)
        self._btn_m_copy_path = Gtk.Button(label="Copy file path")
        self._btn_m_copy_path.connect("clicked", self._copy_path)
        self._btn_m_open_file = Gtk.Button(label="Open file")
        self._btn_m_open_file.connect("clicked", self._open_file)
        for b in (self._btn_m_cancel, self._btn_m_retry, self._btn_m_remove, self._btn_m_open_folder, self._btn_m_show_containing, self._btn_m_copy_path, self._btn_m_open_file):
            vbox.append(b)
        pop.set_child(vbox)
        self.menu_btn.set_popover(pop)
        self.actions.append(self.menu_btn)

        self.append(self.label)
        self.append(self.progress)
        self.append(self.status)
        self.append(self.actions)

    def _on_cancel_clicked(self) -> None:
        try:
            if self._on_cancel:
                self._on_cancel()
        finally:
            # Disable cancel to avoid repeated presses
            self._btn_m_cancel.set_sensitive(False)

    def _on_retry_clicked(self) -> None:
        try:
            if self._on_retry:
                self._on_retry()
        except Exception:
            pass

    def _on_remove_clicked(self) -> None:
        try:
            if self._on_remove:
                self._on_remove()
        except Exception:
            pass

    def set_queued(self) -> None:
        try:
            self.label.set_text(f"Queued: {self._base_title}")
            self.progress.set_fraction(0.0)
            self.progress.set_text("")
            self.status.set_text("")
            self._state = "queued"
        except Exception:
            pass

    def set_metadata(self, video: Video, opts: DownloadOptions, dest_dir: Path) -> None:
        # Deepcopy opts to decouple from future UI edits
        try:
            self._video = video
            self._opts = deepcopy(opts)
            self._dest_dir = dest_dir
        except Exception:
            self._video, self._opts, self._dest_dir = video, opts, dest_dir

    def attach_task(self, task: Any) -> None:
        self.task = task
        self.label.set_text(f"Downloading: {self._base_title}")
        self._state = "downloading"
        # While running, ensure retry/remove disabled
        try:
            self._btn_m_retry.set_sensitive(False)
            self._btn_m_remove.set_sensitive(False)
        except Exception:
            pass

    def update_progress(self, p: DownloadProgress) -> None:
        # Switch label when we get the first real progress
        if p.status == "downloading":
            try:
                self.label.set_text(f"Downloading: {self._base_title}")
            except Exception:
                pass
            self._state = "downloading"
        frac = 0.0
        if p.bytes_total and p.bytes_total > 0:
            frac = min(1.0, max(0.0, p.bytes_downloaded / p.bytes_total))
        self.progress.set_fraction(frac)
        self.progress.set_text(_fmt_dl_text(p))
        self.status.set_text(_fmt_dl_status(p))

        if p.status == "finished":
            # Adjust menu item sensitivity
            self._btn_m_cancel.set_sensitive(False)
            self._btn_m_retry.set_sensitive(False)
            self._btn_m_remove.set_sensitive(True)
            self._btn_m_open_folder.set_sensitive(True)
            self._btn_m_open_file.set_sensitive(True)
            self._btn_m_show_containing.set_sensitive(True)
            self._btn_m_copy_path.set_sensitive(True)
            self._state = "finished"
        elif p.status == "error":
            # Disable cancel after error
            self._btn_m_cancel.set_sensitive(False)
            self._btn_m_retry.set_sensitive(True)
            self._btn_m_remove.set_sensitive(True)
            self._btn_m_open_folder.set_sensitive(True)
            self._btn_m_show_containing.set_sensitive(True)
            # Copy path and open file may still not be resolvable; keep conservative
            self._btn_m_copy_path.set_sensitive(False)
            self._state = "error"

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

    def mark_cancelled(self) -> None:
        try:
            self.label.set_text(f"Cancelled: {self._base_title}")
            self.status.set_text("Cancelled")
            self.progress.set_fraction(0.0)
            self.progress.set_text("")
            self._btn_m_cancel.set_sensitive(False)
            self._btn_m_retry.set_sensitive(True)
            self._btn_m_remove.set_sensitive(True)
            self._btn_m_open_folder.set_sensitive(True)
            self._btn_m_show_containing.set_sensitive(True)
            self._btn_m_copy_path.set_sensitive(False)
            self._state = "cancelled"
        except Exception:
            pass

    def _show_in_folder(self, *_a) -> None:
        try:
            p: DownloadProgress = getattr(self.task, "progress", None)
            if p and p.filename:
                fp = Path(p.filename)
                # If not absolute, try resolve against dest_dir
                dest: Path = getattr(self.task, "dest_dir", None)
                if not fp.is_absolute() and isinstance(dest, Path):
                    fp = dest / fp
                parent = fp.parent
                if parent.exists():
                    Gio.AppInfo.launch_default_for_uri(f"file://{parent}", None)
        except Exception:
            pass

    def _copy_path(self, *_a) -> None:
        """
        Copy download path to clipboard with Wayland-safe async handling.
        Keeps a reference to the ContentProvider to avoid GC before paste.
        """
        try:
            p: DownloadProgress = getattr(self.task, "progress", None)
            dest: Path = getattr(self.task, "dest_dir", None)
            if p and p.filename:
                fp = Path(p.filename)
                if not fp.is_absolute() and isinstance(dest, Path):
                    fp = dest / fp
                
                disp = Gdk.Display.get_default()
                if not disp:
                    return
                clipboard = disp.get_clipboard()
                
                # Create a ContentProvider for text
                # Store it as an instance variable so it doesn't get GC'd (Wayland needs this)
                self._clipboard_provider = Gdk.ContentProvider.new_for_value(str(fp))
                clipboard.set_content(self._clipboard_provider)
                return
        except Exception:
            pass
        # Fallback: copy dest_dir
        try:
            disp = Gdk.Display.get_default()
            if not disp:
                return
            clipboard = disp.get_clipboard()
            
            dest: Path = getattr(self.task, "dest_dir", None)
            if isinstance(dest, Path):
                # Store provider to avoid GC on Wayland
                self._clipboard_provider = Gdk.ContentProvider.new_for_value(str(dest))
                clipboard.set_content(self._clipboard_provider)
        except Exception:
            pass

    def state(self) -> str:
        return self._state

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
    def __init__(self, downloads_box: Gtk.Box, show_downloads_view: Callable[[], None], get_setting: Callable[[str], str|bool|int|None], show_error: Callable[[str], None], show_toast: Callable[[str], None] | None = None) -> None:
        self.downloads_box = downloads_box
        self.show_downloads_view = show_downloads_view
        self.get_setting = get_setting
        self.show_error = show_error
        self.show_toast = show_toast or (lambda _s: None)
        self.download_dir: Path | None = None # This will be set by MainWindow
        self._max_concurrent: int = MAX_CONCURRENT_DEFAULT
        self._active: int = 0
        # queue of (video, opts, dest_dir, row)
        self._queue: list[tuple[Video, DownloadOptions, Path, DownloadRow]] = []
        self._rows: list[DownloadRow] = []
        # persistent queue path
        self._queue_path: Path = _QUEUE_FILE

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
        row = DownloadRow(None, title=video.title, on_cancel=partial(self._cancel_row, None), on_retry=partial(self._retry_row, None), on_remove=partial(self._remove_row, None))
        # Store a weak binding to this specific row into the callback
        row._on_cancel = partial(self._cancel_row, row)  # type: ignore[attr-defined]
        row._on_retry = partial(self._retry_row, row)  # type: ignore[attr-defined]
        row._on_remove = partial(self._remove_row, row)  # type: ignore[attr-defined]
        row.set_queued()
        row.set_metadata(video, opts, dest_dir)
        self.downloads_box.append(row)
        self._rows.append(row)
        self.show_downloads_view()
        # Enqueue and attempt to start
        self._queue.append((video, opts, dest_dir, row))
        self._persist_queue()
        self._maybe_start_next()

    def _maybe_start_next(self) -> None:
        # Start as many as allowed
        while self._active < self._max_concurrent and self._queue:
            video, opts, dest_dir, row = self._queue.pop(0)
            # Persist immediately after queue modification, before task start
            self._persist_queue()
            try:
                self._start_task(video, opts, dest_dir, row)
            except Exception as e:
                # If task fails to start, decrement active count
                self._active = max(0, self._active - 1)
                # Mark row as error
                try:
                    row.update_progress(DownloadProgress(status="error", error=f"Failed to start: {e}"))
                except Exception:
                    pass

    def _cancel_row(self, row: DownloadRow | None) -> None:
        # If None passed (shouldn't happen), ignore
        if row is None:
            return
        # If queued: remove from queue
        removed = False
        for i, (_v, _o, _d, r) in enumerate(list(self._queue)):
            if r is row:
                try:
                    self._queue.pop(i)
                    removed = True
                except Exception:
                    pass
                # Persist after successful removal
                if removed:
                    self._persist_queue()
                row.mark_cancelled()
                return
        # If running: try to stop the task
        task = getattr(row, "task", None)
        if task is None:
            row.mark_cancelled()
            return
        try:
            stop = getattr(task, "stop", None)
            if callable(stop):
                stop()
        except Exception:
            pass
        row.mark_cancelled()

    def _retry_row(self, row: DownloadRow | None) -> None:
        if row is None:
            return
        # If running or queued, ignore
        if row.state() in ("downloading", "queued"):
            return
        v, o, d = row._video, row._opts, row._dest_dir  # type: ignore[attr-defined]
        if not v or not o or not d:
            return
        # Re-enqueue fresh
        row.set_queued()
        self._queue.append((v, o, d, row))
        self._maybe_start_next()

    def _remove_row(self, row: DownloadRow | None) -> None:
        if row is None:
            return
        # If queued, remove from queue first
        for i, (_v, _o, _d, r) in enumerate(list(self._queue)):
            if r is row:
                try:
                    self._queue.pop(i)
                except Exception:
                    pass
                break
        # If running, attempt cancel
        if row.state() == "downloading":
            self._cancel_row(row)
        # Remove from UI and internal list
        try:
            self.downloads_box.remove(row)
        except Exception:
            pass
        try:
            self._rows.remove(row)
        except Exception:
            pass

    def cancel_all(self) -> None:
        # Cancel running and drop queued
        for video, opts, dest_dir, row in list(self._queue):
            try:
                row.mark_cancelled()
            except Exception:
                pass
        self._queue.clear()
        # Running: cancel
        for row in list(self._rows):
            if row.state() == "downloading":
                self._cancel_row(row)

    @staticmethod
    def _open_folder(path: Path) -> None:
        try:
            if isinstance(path, Path) and path.exists():
                Gio.AppInfo.launch_default_for_uri(f"file://{path}", None)
        except Exception:
            pass

    def clear_finished(self) -> None:
        # Remove rows that are done (finished, cancelled, error)
        for row in list(self._rows):
            if row.state() in ("finished", "cancelled", "error"):
                try:
                    self.downloads_box.remove(row)
                except Exception:
                    pass
                try:
                    self._rows.remove(row)
                except Exception:
                    pass

    def _validate_template(self, template: str) -> str:
        """Validate and sanitize output template"""
        if not template or not template.strip():
            return "%(title)s.%(ext)s"
        
        template = template.strip()
        
        # Check for path traversal attempts
        if ".." in template:
            log.warning(f"Template contains '..', using default: {template}")
            return "%(title)s.%(ext)s"
        
        # Check for absolute paths (Unix / and Windows C:\ style)
        if template.startswith("/") or (len(template) > 1 and template[1:3] == ":\\"):
            log.warning(f"Template contains absolute path, using default: {template}")
            return "%(title)s.%(ext)s"
        
        # Basic check: should contain %(ext)s for proper extension
        if "%(ext)s" not in template:
            log.warning(f"Template missing %(ext)s, appending it: {template}")
            template = f"{template}.%(ext)s"
        
        return template

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
                            self.show_toast(f"Downloaded: {video.title}")
                            _notify(f"Downloaded: {video.title}")
                            # Auto-open download folder if enabled
                            try:
                                if bool(self.get_setting("download_auto_open_folder")):
                                    self._open_folder(dest_dir)
                            except Exception:
                                pass
                        elif p.status == "error":
                            self.show_toast(f"Download failed: {video.title}")
                            _notify(f"Download failed: {video.title}")
                    finally:
                        self._active = max(0, self._active - 1)
                        self._maybe_start_next()
                    return False
                GLib.idle_add(_done)

        if advanced:
            cli = opts.raw_cli_list()
            # Add collision handling: let yt-dlp auto-rename if file exists
            cli.append("--no-overwrites")
            
            # Add archive to prevent re-downloads
            archive_path = _download_archive_path()
            cli.extend(["--download-archive", str(archive_path)])
            
            # Inject global proxy if configured and not set explicitly
            proxy = self.get_setting("http_proxy")
            if isinstance(proxy, str) and proxy.strip() and "--proxy" not in cli:
                cli = ["--proxy", proxy.strip()] + cli
            # Optional custom yt-dlp binary path from settings
            ytdlp_path = self.get_setting("ytdlp_path")
            if not isinstance(ytdlp_path, str) or not ytdlp_path.strip():
                ytdlp_path = None
            template = self._validate_template(str(self.get_setting("download_template") or "%(title)s.%(ext)s"))
            task = RunnerDownloadTask(video, dest_dir, cli, bin_path=ytdlp_path, outtmpl_template=template)
            row.attach_task(task)
            # Update cancel binding to running task
            row._on_cancel = lambda: self._cancel_row(row)  # type: ignore[attr-defined]
            task.start(_on_update)
            return

        ydl_override = opts.to_ydl_opts()
        proxy = self.get_setting("http_proxy")
        if isinstance(proxy, str) and proxy.strip():
            ydl_override["proxy"] = proxy.strip()

        # Add archive support
        archive_path = _download_archive_path()
        ydl_override["download_archive"] = str(archive_path)
        
        template = self._validate_template(str(self.get_setting("download_template") or "%(title)s.%(ext)s"))
        dl_task = DownloadTask(video=video, dest_dir=dest_dir, ydl_opts_override=ydl_override)
        dl_task.set_outtmpl_template(template)
        row.attach_task(dl_task)
        row._on_cancel = lambda: self._cancel_row(row)  # type: ignore[attr-defined]
        dl_task.start(_on_update)
        return

    def persist_queue(self) -> None:
        """Public: persist current queued items to disk."""
        self._persist_queue()

    def _persist_queue(self) -> None:
        """Write only queued items (not running) to a JSON file."""
        try:
            items = []
            for v, o, d, r in self._queue:
                # Serialize dataclasses; avoid Path in opts to keep JSON simple
                vd = asdict(v)
                od = asdict(o)
                od.pop("target_dir", None)
                items.append(
                    {
                        "video": vd,
                        "opts": od,
                        "dest_dir": str(d),
                        "title": v.title,
                    }
                )
            self._queue_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._queue_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._queue_path)
        except Exception:
            pass

    def restore_queued(self) -> None:
        """Restore queued items from disk and enqueue them."""
        p = self._queue_path
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return
        except Exception:
            return
        for it in data:
            try:
                if not isinstance(it, dict):
                    continue
                vraw = it.get("video") or {}
                oraw = it.get("opts") or {}
                dstr = it.get("dest_dir") or ""
                if not isinstance(vraw, dict) or not isinstance(oraw, dict) or not isinstance(dstr, str):
                    continue
                video = Video(
                    id=str(vraw.get("id") or ""),
                    title=vraw.get("title") or "",
                    url=vraw.get("url") or "",
                    channel=vraw.get("channel"),
                    duration=vraw.get("duration"),
                    thumb_url=vraw.get("thumb_url"),
                    kind=vraw.get("kind") or "video",
                )
                opts = DownloadOptions(**oraw)
                dest_dir = Path(dstr)
                # Create row in UI as queued and put into _queue
                row = DownloadRow(None, title=video.title, on_cancel=partial(self._cancel_row, None), on_retry=partial(self._retry_row, None), on_remove=partial(self._remove_row, None))
                row._on_cancel = partial(self._cancel_row, row)  # type: ignore[attr-defined]
                row._on_retry = partial(self._retry_row, row)  # type: ignore[attr-defined]
                row._on_remove = partial(self._remove_row, row)  # type: ignore[attr-defined]
                row.set_metadata(video, opts, dest_dir)
                row.set_queued()
                self.downloads_box.append(row)
                self._rows.append(row)
                self._queue.append((video, opts, dest_dir, row))
            except Exception:
                continue
        # Kick off any that fit concurrency
        self._maybe_start_next()