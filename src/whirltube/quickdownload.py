from __future__ import annotations

import os
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .util import load_settings, save_settings, _download_archive_path  # noqa: E402
from .ytdlp_runner import YtDlpRunner, parse_line  # noqa: E402


def _notify(summary: str) -> None:
    try:
        gi.require_version("Notify", "0.7")
        from gi.repository import Notify

        Notify.init("whirltube")
        n = Notify.Notification.new(summary)
        n.show()
    except Exception:
        pass

def _eta_fmt(eta: float | None) -> str:
    e = int(eta or 0)
    return f"{e//60:02}:{e%60:02}"

def _mb(b: float) -> str:
    mb = b / (1024**2)
    if mb > 1024:
        return f"{mb/1024:.2f}GB"
    return f"{mb:.2f}MB"

class QuickDownloadWindow(Gtk.Window):
    def __init__(self, parent: Gtk.Window) -> None:
        super().__init__(transient_for=parent, modal=True, title="Quick Download")
        self.set_default_size(820, 560)
        self.settings = load_settings()

        root = Adw.ToolbarView()
        self.set_child(root)
        header = Adw.HeaderBar()
        root.add_top_bar(header)

        self.tabview = Adw.TabView()

        # Top controls (URLs + progress)
        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        top.append(Gtk.Label(label="Paste URLs (one per line)", xalign=0.0))
        self.url_view = Gtk.TextView()
        self.url_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.url_view.set_size_request(-1, 120)
        sw = Gtk.ScrolledWindow()
        sw.set_child(self.url_view)
        sw.set_vexpand(False)
        top.append(sw)

        self.msg = Gtk.Label(xalign=0)
        self.progress = Gtk.ProgressBar()
        prow = Gtk.Box(spacing=8)
        prow.append(self.msg)
        prow.append(Gtk.Label(label="", hexpand=True))
        prow.append(self.progress)
        top.append(prow)

        # Video tab
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        vgrid = Gtk.Grid(column_spacing=8, row_spacing=8)
        vgrid.attach(Gtk.Label(label="Resolution (-S res)", xalign=0), 0, 0, 1, 1)
        self.dd_res = Gtk.DropDown.new_from_strings(["2160 (4K)", "1440 (2K)", "1080", "720", "480", "360", "240", "144"])
        self.dd_res.set_selected(2)
        vgrid.attach(self.dd_res, 1, 0, 1, 1)
        vgrid.attach(Gtk.Label(label="Remux to", xalign=0), 0, 1, 1, 1)
        self.dd_vidfmt = Gtk.DropDown.new_from_strings(["mp4", "mkv", "webm"])
        self.dd_vidfmt.set_selected(0)
        vgrid.attach(self.dd_vidfmt, 1, 1, 1, 1)
        vbox.append(vgrid)
        self.entry_path_video = Gtk.Entry(
            text=self.settings.get("quick_video_dir", str(Path.home() / "Videos"))
        )
        vbox.append(self._common_path_controls(self.entry_path_video))
        vbox.append(self._controls_row())
        page_video = self.tabview.append(vbox)
        page_video.set_title("Video")

        # Audio tab
        abox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        agrid = Gtk.Grid(column_spacing=8, row_spacing=8)
        agrid.attach(Gtk.Label(label="Audio format", xalign=0), 0, 0, 1, 1)
        self.dd_audfmt = Gtk.DropDown.new_from_strings(["mp3", "m4a", "opus", "vorbis", "wav"])
        self.dd_audfmt.set_selected(0)
        agrid.attach(self.dd_audfmt, 1, 0, 1, 1)
        agrid.attach(Gtk.Label(label="Audio quality (0 best .. 10 worst)", xalign=0), 0, 1, 1, 1)
        self.dd_audq = Gtk.DropDown.new_from_strings(["0 (Best)", "2 (Good)", "4 (Medium)", "6 (Low)"])
        self.dd_audq.set_selected(1)
        agrid.attach(self.dd_audq, 1, 1, 1, 1)
        abox.append(agrid)
        self.entry_path_audio = Gtk.Entry(
            text=self.settings.get("quick_audio_dir", str(Path.home() / "Music"))
        )
        abox.append(self._common_path_controls(self.entry_path_audio))
        abox.append(self._controls_row())
        page_audio = self.tabview.append(abox)
        page_audio.set_title("Audio")

        # Settings tab
        sbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)

        srow = Gtk.Box(spacing=6)
        srow.append(Gtk.Label(label="SponsorBlock:", xalign=0))
        self.dd_sb = Gtk.DropDown.new_from_strings(["Disabled", "Mark (default)", "Remove (default)"])
        self.dd_sb.set_selected(0)
        srow.append(self.dd_sb)
        self.chk_playlist = Gtk.CheckButton(label="Playlist mode")
        srow.append(self.chk_playlist)
        sbox.append(srow)

        crow = Gtk.Box(spacing=6)
        crow.append(Gtk.Label(label="Cookies file:", xalign=0))
        self.entry_cookies = Gtk.Entry()
        self.entry_cookies.set_text(self.settings.get("quick_cookies_path", "") or "")
        crow.append(self.entry_cookies)
        btn_cook = Gtk.Button(label="Browse")
        btn_cook.connect("clicked", self._on_browse_cookies)
        crow.append(btn_cook)
        sbox.append(crow)

        yrow = Gtk.Box(spacing=6)
        yrow.append(Gtk.Label(label="yt-dlp path:", xalign=0))
        self.entry_ytdlp = Gtk.Entry()
        self.entry_ytdlp.set_text(self.settings.get("ytdlp_path", "") or "")
        yrow.append(self.entry_ytdlp)
        btn_y = Gtk.Button(label="Browse")
        btn_y.connect("clicked", self._on_browse_ytdlp)
        yrow.append(btn_y)
        sbox.append(yrow)

        page_settings = self.tabview.append(sbox)
        page_settings.set_title("Settings")

        vcontainer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        vcontainer.append(top)
        vcontainer.append(self.tabview)
        root.set_content(vcontainer)

        self.runner = YtDlpRunner(self._on_progress_line)

    def _common_path_controls(self, entry: Gtk.Entry) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        row = Gtk.Box(spacing=6)
        btn = Gtk.Button(label="Browse")
        btn.connect("clicked", lambda *_: self._on_browse_folder(entry))
        row.append(entry)
        row.append(btn)
        box.append(row)
        return box

    def _controls_row(self) -> Gtk.Widget:
        row = Gtk.Box(spacing=6)
        btn_dl = Gtk.Button(label="Download")
        btn_dl.connect("clicked", self._on_download)
        btn_stop = Gtk.Button(label="Stop")
        btn_stop.connect("clicked", self._on_stop)
        row.append(btn_dl)
        row.append(btn_stop)
        return row

    def _on_browse_folder(self, entry: Gtk.Entry, *_):
        dlg = Gtk.FileDialog(title="Choose folder")
        dlg.select_folder(self, None, self._on_folder_selected, entry)

    def _on_folder_selected(self, dlg: Gtk.FileDialog, res: Gio.AsyncResult, entry: Gtk.Entry):
        try:
            f = dlg.select_folder_finish(res)
            if f:
                entry.set_text(f.get_path() or "")
        except Exception:
            pass

    def _on_browse_cookies(self, *_):
        dlg = Gtk.FileDialog(title="Choose cookies file")
        dlg.open(self, None, self._on_cookies_selected, None)

    def _on_cookies_selected(self, dlg: Gtk.FileDialog, res: Gio.AsyncResult, _data):
        try:
            f = dlg.open_finish(res)
            if f:
                self.entry_cookies.set_text(f.get_path() or "")
        except Exception:
            pass

    def _on_browse_ytdlp(self, *_):
        dlg = Gtk.FileDialog(title="Choose yt-dlp binary")
        dlg.open(self, None, self._on_ytdlp_selected, None)

    def _on_ytdlp_selected(self, dlg: Gtk.FileDialog, res: Gio.AsyncResult, _data):
        try:
            f = dlg.open_finish(res)
            if f:
                self.entry_ytdlp.set_text(f.get_path() or "")
        except Exception:
            pass

    def _on_download(self, *_):
        buf = self.url_view.get_buffer()
        start = buf.get_start_iter()
        end = buf.get_end_iter()
        urls = [u.strip() for u in buf.get_text(start, end, False).splitlines() if u.strip()]
        if not urls:
            self._set_msg("No URLs")
            return

        page = self.tabview.get_selected_page()
        title = page.get_title()
        source_entry = self.entry_path_video if title == "Video" else self.entry_path_audio

        out_dir = os.path.expanduser(source_entry.get_text() or "")
        if not out_dir or not Path(out_dir).exists():
            self._set_msg("Invalid download folder")
            return

        # persist per-tab path and ytdlp_path (do not clobber global download_dir)
        if title == "Video":
            self.settings["quick_video_dir"] = out_dir
        else:
            self.settings["quick_audio_dir"] = out_dir

        self.settings["ytdlp_path"] = self.entry_ytdlp.get_text().strip()
        # also persist cookies path for convenience
        self.settings["quick_cookies_path"] = self.entry_cookies.get_text().strip()
        save_settings(self.settings)

        args: list[str] = []
        args += ["-P", out_dir]
        # Global proxy
        proxy = (self.settings.get("http_proxy") or "").strip()
        if proxy:
            args += ["--proxy", proxy]

        if title == "Video":
            sel = self.dd_res.get_selected()
            reslist = ["res:2160","res:1440","res:1080","res:720","res:480","res:360","res:240","res:144"]
            res = reslist[sel if sel >= 0 else 2]
            args += ["-S", res]
            fmt = ["mp4", "mkv", "webm"][self.dd_vidfmt.get_selected() or 0]
            args += ["--remux-video", fmt]
        else:
            fmt = ["mp3", "m4a", "opus", "vorbis", "wav"][self.dd_audfmt.get_selected() or 0]
            qual_map = ["0", "2", "4", "6"]
            aq = qual_map[self.dd_audq.get_selected() or 1]
            args += ["-x", "--audio-format", fmt, "--audio-quality", aq]

        # cookies file
        ck = self.entry_cookies.get_text().strip()
        if ck:
            args += ["--cookies", ck]

        # sponsorblock
        sb_idx = self.dd_sb.get_selected()
        if sb_idx == 1:
            args += ["--sponsorblock-mark", "default"]
        elif sb_idx == 2:
            args += ["--sponsorblock-remove", "default"]

        # playlist mode
        if self.chk_playlist.get_active():
            args += ["--yes-playlist", "-o", "%(playlist)s/%(title)s.%(ext)s"]
        else:
            template = self.settings.get("download_template") or "%(title)s.%(ext)s"
            args += [
                "--break-on-reject",
                "--match-filter",
                "!playlist",
                "--no-playlist",
                "-o",
                template,
            ]

        # Parity arguments (Task 2)
        args += [
            "--download-archive", str(_download_archive_path()),
            "--no-overwrites",
            "--continue",
            "--retries", "3",
            "--fragment-retries", "2",
            "-N", "4", # Concurrency
        ]

        args += urls

        self.progress.set_fraction(0.0)
        self._set_msg("Initializing…")
        path = self.settings.get("ytdlp_path", "") or None
        self.runner.start(args, bin_path=path)
        # Watch for process exit, then mark end if not already stopped
        import threading
        def _watch():
            import time
            while self.runner.is_running():
                time.sleep(0.2)
            GLib.idle_add(self._end, ok="Done")
        threading.Thread(target=_watch, daemon=True).start()

    def _on_stop(self, *_):
        self.runner.stop()
        self.progress.set_fraction(0.0)
        self._set_msg("Stopped")

    def _on_progress_line(self, text: str) -> None:
        GLib.idle_add(self._handle_line, text)

    def _handle_line(self, text: str) -> bool:
        parsed = parse_line(text)
        if isinstance(parsed, Exception):
            self._end(error=str(parsed))
            return False
        if not parsed:
            return False
        for ev in parsed:
            if ev.kind == "downloading":
                d = float(ev.payload.get("downloaded_bytes") or 0.0)
                t = ev.payload.get("total_bytes") or ev.payload.get("total_bytes_estimate")
                total = float(t or 0.0)
                frac = (d / total) if total > 0 else 0.0
                self.progress.set_fraction(min(1.0, max(0.0, frac)))
                speed = float(ev.payload.get("speed") or 0.0)
                eta = float(ev.payload.get("eta") or 0.0)
                pc = ev.payload.get("playlist_count")
                pi = ev.payload.get("playlist_index")
                msg = f"{_mb(d)} | {speed/(1024**2):.2f}MB/s | ETA {_eta_fmt(eta)}"
                if pc and pi:
                    msg += f" {pi}/{pc}"
                self._set_msg(msg)
            elif ev.kind == "end_of_playlist":
                # Do not end early; wait for process exit
                pass
            elif ev.kind == "end_of_video":
                pass
        return False

    def _end(self, ok: str | None = None, error: str | None = None) -> None:
        self.runner.stop()
        if ok:
            self._set_msg(ok)
            _notify(ok)
        elif error:
            self._set_msg(error)
            _notify(error)

    def _set_msg(self, s: str) -> None:
        self.msg.set_label(s)
