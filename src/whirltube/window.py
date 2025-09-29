from __future__ import annotations

import logging
import os
import tempfile
import shlex
import secrets
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import re

import httpx

from . import __version__
from .app import APP_ID
from .dialogs import DownloadOptions, DownloadOptionsWindow, PreferencesWindow
from .history import add_search_term, add_watch, list_watch
from .models import Video
from .mpv_embed import MpvWidget
from .player import has_mpv, start_mpv, mpv_send_cmd, mpv_supports_option
from .provider import YTDLPProvider
from .invidious_provider import InvidiousProvider
from .download_manager import DownloadManager
from .search_filters import normalize_search_filters
from .navigation_controller import NavigationController
from .download_history import list_downloads
from .subscriptions import is_followed, add_subscription, remove_subscription, list_subscriptions, export_subscriptions, import_subscriptions
from .quickdownload import QuickDownloadWindow
from .util import load_settings, save_settings, xdg_data_dir, safe_httpx_proxy, is_valid_youtube_url

import gi
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}

log = logging.getLogger(__name__)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="WhirlTube")
        # Load settings first, then apply persisted window size
        self.settings = load_settings()
        try:
            w = int(self.settings.get("win_w") or 1080)
            h = int(self.settings.get("win_h") or 740)
        except Exception:
            w, h = 1080, 740
        self.set_default_size(w, h)
        self.set_icon_name("whirltube")

        self.download_dir = Path(self.settings.get("download_dir") or str(xdg_data_dir() / "downloads"))
        self.settings.setdefault("playback_mode", "external")  # external | embedded
        self.settings.setdefault("mpv_args", "")
        self.settings.setdefault("mpv_quality", "auto")

        # Optional playback cookies for MPV
        self.settings.setdefault("mpv_cookies_enable", False)
        self.settings.setdefault("mpv_cookies_browser", "")
        self.settings.setdefault("mpv_cookies_keyring", "")
        self.settings.setdefault("mpv_cookies_profile", "")
        self.settings.setdefault("mpv_cookies_container", "")

        self.settings.setdefault("max_concurrent_downloads", 3)
        self.settings.setdefault("mpv_autohide_controls", False)
        self.settings.setdefault("download_template", "%(title)s.%(ext)s")
        self.settings.setdefault("download_auto_open_folder", False)
        # Window size persistence
        self.settings.setdefault("win_w", 1080)
        self.settings.setdefault("win_h", 740)
        # Initialize provider with global proxy and optional Invidious
        proxy = (self.settings.get("http_proxy") or "").strip() or None
        if bool(self.settings.get("use_invidious")):
            base = (self.settings.get("invidious_instance") or "https://yewtu.be").strip()
            self.provider: YTDLPProvider | InvidiousProvider = InvidiousProvider(base, proxy=proxy, fallback=YTDLPProvider(proxy or None))
        else:
            self.provider: YTDLPProvider | InvidiousProvider = YTDLPProvider(proxy or None)
        self._search_generation = 0
        self._thumb_loader_pool = ThreadPoolExecutor(max_workers=4)
        
        # ToolbarView
        self.toolbar_view = Adw.ToolbarView()
        
        # Header
        header = Adw.HeaderBar()
        self.toolbar_view.add_top_bar(header)
        
        # MPV control bar (hidden by default; shown for external MPV)
        self.ctrl_bar = Adw.HeaderBar()
        self.ctrl_bar.set_title_widget(Gtk.Label(label="MPV Controls", css_classes=["dim-label"]))
        # Toast overlay wrappers the whole UI
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)
        # Buttons: Seek -10, Play/Pause, Seek +10, Speed -, Speed +, Stop
        self.btn_seek_back = Gtk.Button(icon_name="media-seek-backward-symbolic")
        self.btn_play_pause = Gtk.Button(icon_name="media-playback-pause-symbolic")
        self.btn_seek_fwd = Gtk.Button(icon_name="media-seek-forward-symbolic")
        self.btn_speed_down = Gtk.Button(label="Speed -")
        self.btn_speed_up = Gtk.Button(label="Speed +")
        self.btn_stop_mpv = Gtk.Button(icon_name="media-playback-stop-symbolic")
        self.btn_seek_back.connect("clicked", lambda *_: self._mpv_seek(-10))
        self.btn_play_pause.connect("clicked", lambda *_: self._mpv_cycle_pause())
        self.btn_seek_fwd.connect("clicked", lambda *_: self._mpv_seek(10))
        self.btn_speed_down.connect("clicked", lambda *_: self._mpv_speed_delta(-0.1))
        self.btn_speed_up.connect("clicked", lambda *_: self._mpv_speed_delta(0.1))
        self.btn_copy_ts = Gtk.Button(icon_name="edit-copy-symbolic")
        self.btn_copy_ts.set_tooltip_text("Copy URL at current time (T)")
        self.btn_copy_ts.connect("clicked", lambda *_: self._mpv_copy_ts())
        self.btn_stop_mpv.connect("clicked", lambda *_: self._mpv_stop())
        # Pack controls on the right
        self.ctrl_bar.pack_end(self.btn_stop_mpv)
        self.ctrl_bar.pack_end(self.btn_copy_ts)
        self.ctrl_bar.pack_end(self.btn_speed_up)
        self.ctrl_bar.pack_end(self.btn_speed_down)
        self.ctrl_bar.pack_end(self.btn_seek_fwd)
        self.ctrl_bar.pack_end(self.btn_play_pause)
        self.ctrl_bar.pack_end(self.btn_seek_back)
        self.toolbar_view.add_top_bar(self.ctrl_bar)
        self.ctrl_bar.set_visible(False)
        
        # Back button (NavigationController will connect it)
        self.btn_back = Gtk.Button(icon_name="go-previous-symbolic")
        self.btn_back.set_tooltip_text("Back")
        header.pack_start(self.btn_back)
        
        # Menu
        menu = Gio.Menu()
        menu.append("Preferences", "win.preferences")
        menu.append("About", "win.about")
        menu.append("Manage Subscriptions", "win.subscriptions")
        menu.append("Import Subscriptions…", "win.subs_import")
        menu.append("Export Subscriptions…", "win.subs_export")
        menu.append("Keyboard Shortcuts", "win.shortcuts")
        menu.append("Download History", "win.download_history")
        menu.append("Cancel All Downloads", "win.cancel_all_downloads")
        menu.append("Clear Finished Downloads", "win.clear_finished_downloads")
        menu.append("Copy URL @ time", "win.mpv_copy_ts")
        menu.append("Stop MPV", "win.stop_mpv")
        menu.append("Quit", "app.quit")
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_btn.set_menu_model(menu)
        header.pack_start(menu_btn)
        
        # Quick actions (left)
        self.btn_open = Gtk.Button(label="Open URL…")
        self.btn_open.set_tooltip_text("Open any YouTube URL (video/playlist/channel)")
        self.btn_open.connect("clicked", self._on_open_url)
        header.pack_start(self.btn_open)

        self.btn_hist = Gtk.Button(label="History")
        self.btn_hist.set_tooltip_text("Watch history")
        self.btn_hist.connect("clicked", self._on_history)
        header.pack_start(self.btn_hist)

        self.btn_feed = Gtk.Button(label="Feed")
        self.btn_feed.set_tooltip_text("Recent from followed channels")
        self.btn_feed.connect("clicked", self._on_feed)
        header.pack_start(self.btn_feed)

        self.btn_trending = Gtk.Button(label="Trending")
        self.btn_trending.set_tooltip_text("YouTube trending now")
        self.btn_trending.connect("clicked", self._on_trending)
        header.pack_start(self.btn_trending)

        self.btn_qdl = Gtk.Button(label="Quick Download")
        self.btn_qdl.set_tooltip_text("Batch download multiple URLs")
        self.btn_qdl.connect("clicked", self._on_quick_download)
        header.pack_start(self.btn_qdl)

        # Search
        self.search = Gtk.SearchEntry(hexpand=True)
        self.search.set_placeholder_text("Search YouTube…")
        header.set_title_widget(self.search)
        self.search.connect("activate", self._on_search_activate)
        # Clear text when the user presses Escape or the clear icon
        def _stop_search(_entry, *_a):
            try:
                self.search.set_text("")
                self._set_welcome()
            except Exception:
                pass
        self.search.connect("stop-search", _stop_search)
        
        # Filters popover
        self.btn_filters = Gtk.MenuButton(icon_name="view-list-symbolic")
        self.btn_filters.set_tooltip_text("Search filters")
        header.pack_end(self.btn_filters)
        self._filters_pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        # Duration
        box.append(Gtk.Label(label="Duration", xalign=0.0))
        self.dd_dur = Gtk.DropDown.new_from_strings(["Any", "Short (<4m)", "Medium (4–20m)", "Long (>20m)"])
        box.append(self.dd_dur)
        # Upload date
        box.append(Gtk.Label(label="Upload date", xalign=0.0))
        self.dd_period = Gtk.DropDown.new_from_strings(["Any", "Today", "This week", "This month"]) 
        box.append(self.dd_period)
        # Order
        box.append(Gtk.Label(label="Order", xalign=0.0))
        self.dd_order = Gtk.DropDown.new_from_strings(["Relevance", "Date", "Views"]) 
        box.append(self.dd_order)
        # Buttons row
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_clear = Gtk.Button(label="Clear")
        btn_apply = Gtk.Button(label="Apply", css_classes=["suggested-action"]) 
        row.append(btn_clear)
        row.append(btn_apply)
        box.append(row)
        self._filters_pop.set_child(box)
        self.btn_filters.set_popover(self._filters_pop)
        # Load current settings into UI
        self._filters_load_from_settings()
        btn_clear.connect("clicked", self._filters_clear)
        btn_apply.connect("clicked", self._filters_apply)
        
        # Downloads toggle
        self.downloads_button = Gtk.Button(label="Downloads")
        self.downloads_button.connect("clicked", self._show_downloads)
        header.pack_end(self.downloads_button)

        # Stack
        self.stack = Gtk.Stack(
            vexpand=True,
            hexpand=True,
            transition_type=Gtk.StackTransitionType.CROSSFADE,
        )
        
        # Results
        self.results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._set_margins(self.results_box, 8)
        results_scroll = Gtk.ScrolledWindow(vexpand=True)
        results_scroll.set_child(self.results_box)
        self.stack.add_titled(results_scroll, "results", "Results")

        # Downloads
        downloads_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._set_margins(downloads_page, 8)
        # Header row with "Open download directory"
        dl_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.btn_open_dl_dir = Gtk.Button(label="Open download directory")
        self.btn_open_dl_dir.set_tooltip_text("Open current download directory")
        self.btn_open_dl_dir.connect("clicked", self._open_download_dir)
        dl_hdr.append(self.btn_open_dl_dir)
        dl_hdr.append(Gtk.Label(label="", hexpand=True))  # spacer
        downloads_page.append(dl_hdr)
        # Scroll with list
        self.downloads_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        downloads_scroll = Gtk.ScrolledWindow(vexpand=True)
        downloads_scroll.set_child(self.downloads_box)
        downloads_page.append(downloads_scroll)
        # Add as stack page
        self.stack.add_titled(downloads_page, "downloads", "Downloads")

        # Player (embedded mpv)
        self.player_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._set_margins(self.player_box, 0)
        self.mpv_widget = MpvWidget()
        self.player_box.append(self.mpv_widget)
        self.stack.add_titled(self.player_box, "player", "Player")

        # Place ToolbarView inside the ToastOverlay
        self.toast_overlay.set_child(self.toolbar_view)
        self.toolbar_view.set_content(self.stack)
        
        # Track stack page changes once (for MPV controls visibility)
        try:
            self.stack.connect("notify::visible-child", self._on_stack_changed)
        except Exception:
            pass

        # Navigation controller (handles back button)
        self.navigation_controller = NavigationController(self.stack, self.btn_back)

        # Download manager (after downloads_box and nav exist)
        self.download_manager = DownloadManager(
            downloads_box=self.downloads_box,
            show_downloads_view=lambda: self.navigation_controller.show_view("downloads"),
            get_setting=self.settings.get,
            show_error=self._show_error,
            show_toast=self._show_toast,
        )
        self.download_manager.set_download_dir(self.download_dir)
        self.download_manager.set_max_concurrent(int(self.settings.get("max_concurrent_downloads") or 3))
        self.download_manager.restore_queued()

        self._create_actions()
        self._set_welcome()
        self._install_shortcuts()

        # MPV actions (menu + hotkeys)
        self._install_mpv_actions()
        self._install_key_controller()

        # Track current URL for timestamp copying
        self._mpv_current_url: str | None = None

        # MPV external player state
        self._mpv_proc: subprocess.Popen | None = None
        self._mpv_ipc: str | None = None
        self._mpv_speed = 1.0

        # Save settings on window close
        self.connect("close-request", self._on_main_close)
    def _show_toast(self, text: str) -> None:
        try:
            self.toast_overlay.add_toast(Adw.Toast.new(text))
        except Exception:
            pass

    def _install_shortcuts(self) -> None:
        # Add a "go-back" action with common shortcuts.
        go_back = Gio.SimpleAction.new("go-back", None)
        go_back.connect("activate", lambda *_: self.navigation_controller.go_back())
        self.add_action(go_back)
        app = self.get_application()
        if app:
            app.set_accels_for_action(
                "win.go-back",
                ["Escape", "BackSpace", "<Alt>Left", "<Primary>BackSpace"],
            )

    def _set_margins(self, w: Gtk.Widget, px: int) -> None:
        w.set_margin_top(px)
        w.set_margin_bottom(px)
        w.set_margin_start(px)
        w.set_margin_end(px)

    def _install_mpv_actions(self) -> None:
        # Define actions
        a_play_pause = Gio.SimpleAction.new("mpv_play_pause", None)
        a_play_pause.connect("activate", lambda *_: self._mpv_cycle_pause())
        self.add_action(a_play_pause)

        a_seek_back = Gio.SimpleAction.new("mpv_seek_back", None)
        a_seek_back.connect("activate", lambda *_: self._mpv_seek(-10))
        self.add_action(a_seek_back)

        a_seek_fwd = Gio.SimpleAction.new("mpv_seek_fwd", None)
        a_seek_fwd.connect("activate", lambda *_: self._mpv_seek(10))
        self.add_action(a_seek_fwd)

        a_speed_down = Gio.SimpleAction.new("mpv_speed_down", None)
        a_speed_down.connect("activate", lambda *_: self._mpv_speed_delta(-0.1))
        self.add_action(a_speed_down)

        a_speed_up = Gio.SimpleAction.new("mpv_speed_up", None)
        a_speed_up.connect("activate", lambda *_: self._mpv_speed_delta(0.1))
        self.add_action(a_speed_up)

        a_copy_ts = Gio.SimpleAction.new("mpv_copy_ts", None)
        a_copy_ts.connect("activate", lambda *_: self._mpv_copy_ts())
        self.add_action(a_copy_ts)

        a_stop = Gio.SimpleAction.new("stop_mpv", None)
        a_stop.connect("activate", lambda *_: self._mpv_stop())
        a_stop.set_enabled(False)  # only enabled when mpv running
        self.add_action(a_stop)
        self._act_stop_mpv = a_stop

        # Install accelerators
        app = self.get_application()
        if not app:
            return
        # YouTube-like keys: j/k/l and +/- for speed, x to stop
        app.set_accels_for_action("win.mpv_play_pause", ["K", "k"])
        app.set_accels_for_action("win.mpv_seek_back", ["J", "j"])
        app.set_accels_for_action("win.mpv_seek_fwd", ["L", "l"])
        app.set_accels_for_action("win.mpv_speed_down", ["minus", "KP_Subtract"])
        app.set_accels_for_action("win.mpv_speed_up", ["equal", "KP_Add"])
        app.set_accels_for_action("win.mpv_copy_ts", ["T", "t"])
        app.set_accels_for_action("win.stop_mpv", ["X", "x"])

    def _install_key_controller(self) -> None:
        ctrl = Gtk.EventControllerKey()
        def on_key(_c, keyval, keycode, state):
            # Only handle when MPV is running
            if self._mpv_proc is None:
                return False
            k = Gdk.keyval_name(keyval) or ""
            k = k.lower()
            handled = False
            if k == "j":
                self._mpv_seek(-10); handled = True
            elif k == "k":
                self._mpv_cycle_pause(); handled = True
            elif k == "l":
                self._mpv_seek(10); handled = True
            elif k in ("minus", "kp_subtract"):
                self._mpv_speed_delta(-0.1); handled = True
            elif k in ("equal", "kp_add", "plus"):
                self._mpv_speed_delta(0.1); handled = True
            elif k == "x":
                self._mpv_stop(); handled = True
            elif k == "t":
                self._mpv_copy_ts(); handled = True
            return handled
        ctrl.connect("key-pressed", on_key)
        self.add_controller(ctrl)

    def _create_actions(self) -> None:
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._on_about)
        self.add_action(about)

        prefs = Gio.SimpleAction.new("preferences", None)
        prefs.connect("activate", self._on_preferences)
        self.add_action(prefs)

        # Add the open URL action for Ctrl+L
        open_url = Gio.SimpleAction.new("open_url", None)
        open_url.connect("activate", self._on_open_url)
        self.add_action(open_url)
        app = self.get_application()
        if app:
            app.set_accels_for_action("win.open_url", ["<Primary>L"])

        shortcuts = Gio.SimpleAction.new("shortcuts", None)
        shortcuts.connect("activate", self._on_shortcuts)
        self.add_action(shortcuts)

        dlh = Gio.SimpleAction.new("download_history", None)
        dlh.connect("activate", self._on_download_history)
        self.add_action(dlh)

        cancel_all = Gio.SimpleAction.new("cancel_all_downloads", None)
        cancel_all.connect("activate", lambda *_: self.download_manager.cancel_all())
        self.add_action(cancel_all)

        clear_fin = Gio.SimpleAction.new("clear_finished_downloads", None)
        clear_fin.connect("activate", lambda *_: self.download_manager.clear_finished())
        self.add_action(clear_fin)

        # Subscriptions actions (menu entries exist, actions were missing)
        subs = Gio.SimpleAction.new("subscriptions", None)
        subs.connect("activate", self._on_subscriptions)
        self.add_action(subs)

        subs_import = Gio.SimpleAction.new("subs_import", None)
        subs_import.connect("activate", self._on_subs_import)
        self.add_action(subs_import)

        subs_export = Gio.SimpleAction.new("subs_export", None)
        subs_export.connect("activate", self._on_subs_export)
        self.add_action(subs_export)

    def _show_loading(self, message: str) -> None:
        # Clear results and show a centered spinner + message
        self._clear_results()
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_halign(Gtk.Align.CENTER)
        row.set_valign(Gtk.Align.CENTER)
        spinner = Gtk.Spinner()
        spinner.start()
        row.append(spinner)
        row.append(Gtk.Label(label=message))
        self.results_box.append(row)
        self.navigation_controller.show_view("results")

    def _on_shortcuts(self, *_a) -> None:
        # Create a ShortcutsWindow describing common keybindings
        win = Gtk.ShortcutsWindow(transient_for=self, modal=True)
        sec = Gtk.ShortcutsSection()
        # Navigation group
        grp_nav = Gtk.ShortcutsGroup(title="Navigation")
        grp_nav.append(Gtk.ShortcutsShortcut(title="Back", accelerator="Escape"))
        grp_nav.append(Gtk.ShortcutsShortcut(title="Back", accelerator="BackSpace"))
        grp_nav.append(Gtk.ShortcutsShortcut(title="Back", accelerator="<Alt>Left"))
        grp_nav.append(Gtk.ShortcutsShortcut(title="Back", accelerator="<Primary>BackSpace"))
        # App group
        grp_app = Gtk.ShortcutsGroup(title="Application")
        grp_app.append(Gtk.ShortcutsShortcut(title="Open URL", accelerator="<Primary>L"))
        grp_app.append(Gtk.ShortcutsShortcut(title="Quit", accelerator="<Primary>q"))
        # Search group
        grp_search = Gtk.ShortcutsGroup(title="Search")
        grp_search.append(Gtk.ShortcutsShortcut(title="Run search", accelerator="Return"))
        # Player/MPV controls
        grp_play = Gtk.ShortcutsGroup(title="MPV Controls")
        grp_play.append(Gtk.ShortcutsShortcut(title="Play/Pause", accelerator="K"))
        grp_play.append(Gtk.ShortcutsShortcut(title="Seek backward 10s", accelerator="J"))
        grp_play.append(Gtk.ShortcutsShortcut(title="Seek forward 10s", accelerator="L"))
        grp_play.append(Gtk.ShortcutsShortcut(title="Speed down", accelerator="-"))
        grp_play.append(Gtk.ShortcutsShortcut(title="Speed up", accelerator="="))
        grp_play.append(Gtk.ShortcutsShortcut(title="Stop", accelerator="X"))
        # Assemble: Add groups to section using add_group
        sec.add_group(grp_nav)
        sec.add_group(grp_app)
        sec.add_group(grp_search)
        sec.add_group(grp_play)
        win.add_section(sec)
        win.present()

    def _on_about(self, *_args) -> None:
        dlg = Adw.AboutDialog(
            application_name="WhirlTube",
            application_icon="whirltube",
            developer_name="WhirlTube contributors",
            version=__version__,
            license_type=Gtk.License.GPL_3_0,
            website="https://github.com/whirltube/whirltube",
            issue_url="https://github.com/whirltube/whirltube/issues",
            comments="Lightweight GTK4 frontend for YouTube using MPV + yt-dlp.",
        )
        dlg.present(self)

    def _on_download_history(self, *_a) -> None:
        vids = list_downloads(limit=300)
        self._populate_results(vids)
        self.navigation_controller.show_view("results")

    def _on_subscriptions(self, *_a) -> None:
        # Show followed channels as rows (channel-kind Video entries)
        subs = list_subscriptions()
        vids = []
        for sub in subs:
            title = sub.title or "(channel)"
            vids.append(Video(id=sub.url, title=title, url=sub.url, channel=title, duration=None, thumb_url=None, kind="channel"))
        self._populate_results(vids)
        self.navigation_controller.show_view("results")

    def _on_subs_import(self, *_a) -> None:
        dlg = Gtk.FileDialog(title="Import subscriptions.json")
        def on_done(d, res, *_):
            try:
                f = d.open_finish(res)
            except Exception:
                return
            path = f.get_path()
            if not path:
                return
            try:
                added = import_subscriptions(Path(path))
                if added:
                    # Refresh subscriptions view if currently visible
                    self._on_subscriptions()
            except Exception:
                pass
        dlg.open(self, None, on_done, None)

    def _on_subs_export(self, *_a) -> None:
        dlg = Gtk.FileDialog(title="Export subscriptions")
        dlg.set_initial_name("subscriptions.json")
        def on_done(d, res, *_):
            try:
                f = d.save_finish(res)
            except Exception:
                return
            path = f.get_path()
            if not path:
                return
            dest = Path(path)
            try:
                export_subscriptions(dest)
                self._show_toast(f"Exported {len(list_subscriptions())} subscriptions to {dest}")
            except Exception as e:
                self._show_error(f"Export failed: {e}")
        dlg.save(self, None, on_done, None)

    def _on_preferences(self, *_a) -> None:
        win = PreferencesWindow(self, self.settings)
        win.present()

        def persist(_w, *_a):
            save_settings(self.settings)
            new_dir = self.settings.get("download_dir")
            if new_dir:
                self.download_dir = Path(new_dir)
                self.download_manager.set_download_dir(self.download_dir)
            # Reconfigure provider: Invidious vs yt-dlp
            proxy = (self.settings.get("http_proxy") or "").strip() or None
            use_invid = bool(self.settings.get("use_invidious"))
            invid_base = (self.settings.get("invidious_instance") or "https://yewtu.be").strip()
            try:
                if use_invid:
                    self.provider = InvidiousProvider(invid_base, proxy=proxy, fallback=YTDLPProvider(proxy or None))
                else:
                    self.provider = YTDLPProvider(proxy or None)
            except Exception:
                # fallback to yt-dlp
                self.provider = YTDLPProvider(proxy or None)
            # Update concurrency at runtime
            self.download_manager.set_max_concurrent(int(self.settings.get("max_concurrent_downloads") or 3))
            # Update MPV controls visibility preference immediately
            self.ctrl_bar.set_visible(self._is_mpv_controls_visible())

        win.connect("close-request", persist)

    def _on_main_close(self, *_a) -> bool:
        # Persist current window size
        try:
            self.settings["win_w"], self.settings["win_h"] = int(self.get_width()), int(self.get_height())
        except Exception:
            pass
        # Stop MPV if running
        try:
            self._mpv_stop()
        except Exception:
            pass
        # Shut down thumbnail loader pool
        try:
            self._thumb_loader_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

        # Persist queue (best effort)
        try:
            self.download_manager.persist_queue()
        except Exception:
            pass
        save_settings(self.settings)
        return False

    def _set_welcome(self) -> None:
        self.navigation_controller.clear_history()
        self._clear_results()
        self.results_box.append(_spacer(16))
        label = Gtk.Label(
            label="Type a search and press Enter.\nOr click Open URL / Quick Download.",
            justify=Gtk.Justification.CENTER,
        )
        # Center in both axes using GTK4 halign/valign
        label.set_halign(Gtk.Align.CENTER)
        label.set_valign(Gtk.Align.CENTER)
        self.results_box.append(label)
        self.navigation_controller.show_view("results")

    def _clear_results(self) -> None:
        child = self.results_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.results_box.remove(child)
            child = nxt

    # ---------- Header actions ----------

    def _on_open_url(self, *_a) -> None:
        dlg = Gtk.Dialog(title="Open URL", transient_for=self, modal=True)
        entry = Gtk.Entry()
        entry.set_placeholder_text("Paste a YouTube URL (video/channel/playlist)…")
        box = dlg.get_content_area()
        box.append(entry)
        dlg.add_button("Open", Gtk.ResponseType.OK)
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dlg.set_default_response(Gtk.ResponseType.OK)
        dlg.present()

        def on_response(d: Gtk.Dialog, resp):
            try:
                if resp == Gtk.ResponseType.OK:
                    url = entry.get_text().strip()
                    if url:
                        # Allow Invidious host when "use_invidious" is enabled
                        extra = []
                        if bool(self.settings.get("use_invidious")):
                            host = urlparse((self.settings.get("invidious_instance") or "").strip()).hostname
                            if host:
                                extra.append(host)
                                # common subdomain case
                                if not host.startswith("www."):
                                    extra.append("www." + host)
                        if not is_valid_youtube_url(url, extra):
                            self._show_error("This doesn't look like a YouTube/Invidious URL.")
                        else:
                            # If this looks like a direct video URL, play immediately
                            vid = self._extract_ytid_from_url(url)
                            if vid:
                                v = Video(id=vid, title=url, url=url, channel=None, duration=None, thumb_url=None, kind="video")
                                self._play_video(v)
                            else:
                                # Otherwise open as a listing (playlist/channel/etc.)
                                self._browse_url(url)
            finally:
                d.destroy()

        dlg.connect("response", on_response)

    def _extract_ytid_from_url(self, url: str) -> str | None:
        """
        Extract a YouTube video ID from common URL forms:
        - https://www.youtube.com/watch?v=ID
        - https://youtu.be/ID
        - https://www.youtube.com/shorts/ID
        - https://www.youtube.com/embed/ID
        """
        try:
            u = urlparse(url)
            host = (u.hostname or "").lower()
            path = u.path or ""
            if host == "youtu.be":
                m = re.match(r"^/([0-9A-Za-z_-]{11})", path)
                if m:
                    return m.group(1)
            if host.endswith("youtube.com"):
                if path.startswith("/watch"):
                    qs = parse_qs(u.query or "")
                    v = qs.get("v", [None])[0]
                    if v and re.fullmatch(r"[0-9A-Za-z_-]{11}", v):
                        return v
                m = re.match(r"^/(?:shorts|embed)/([0-9A-Za-z_-]{11})", path)
                if m:
                    return m.group(1)
        except Exception:
            pass
        return None

    def _on_history(self, *_a) -> None:
        vids = list_watch(limit=200)
        self._populate_results(vids)
        self.navigation_controller.show_view("results")

    def _on_quick_download(self, *_a) -> None:
        QuickDownloadWindow(self).present()

    def _on_feed(self, *_a) -> None:
        # Show loading, then fetch recent uploads from each followed channel
        self._show_loading("Loading feed…")

        def worker():
            vids_all = []
            try:
                subs = list_subscriptions()
                per_chan = 5
                for sub in subs:
                    try:
                        vids = self.provider.channel_tab(sub.url, "videos")
                        if vids:
                            vids_all.extend(vids[:per_chan])
                    except Exception:
                        continue
            except Exception:
                vids_all = []
            GLib.idle_add(self._populate_results, vids_all)
        threading.Thread(target=worker, daemon=True).start()

    def _on_trending(self, *_a) -> None:
        self._show_loading("Loading trending…")
        def worker():
            try:
                vids = self.provider.trending()
            except Exception:
                vids = []
            def show():
                self._populate_results(vids)
                if not vids:
                    self._show_toast("Trending is unavailable on your network/region right now.")
                return False
            GLib.idle_add(show)
        threading.Thread(target=worker, daemon=True).start()

    # ---------- Browse helpers ----------

    def _browse_url(self, url: str) -> None:
        self._show_loading(f"Opening: {url}")

        def worker():
            vids = self.provider.browse_url(url)
            GLib.idle_add(self._populate_results, vids)

        threading.Thread(target=worker, daemon=True).start()

    # ---------- Search ----------

    def _on_search_activate(self, entry: Gtk.SearchEntry) -> None:
        query = entry.get_text().strip()
        if not query:
            return
        add_search_term(query)
        self._run_search(query)

    def _run_search(self, query: str) -> None:
        log.info("Searching: %s", query)
        self._show_loading(f"Searching: {query}")

        gen = self._search_generation = self._search_generation + 1

        def worker() -> None:
            try:
                # Normalize filters from settings to provider-friendly form
                order, duration, period = normalize_search_filters(self.settings)
                results = self.provider.search(query, limit=30, order=order, duration=duration, period=period)
            except Exception as e:
                log.exception("Search failed")
                GLib.idle_add(self._show_error, f"Search failed: {e}")
                return
            if gen != self._search_generation:
                return
            GLib.idle_add(self._populate_results, results)

        threading.Thread(target=worker, daemon=True).start()

    def _show_error(self, msg: str) -> None:
        self._clear_results()
        lbl = Gtk.Label(label=msg)
        lbl.add_css_class("error")
        self.results_box.append(lbl)
        self.navigation_controller.show_view("results")

    def _populate_results(self, videos: list[Video]) -> None:
        self._clear_results()
        if not videos:
            self.results_box.append(Gtk.Label(label="No results."))
            return
        for v in videos:
            import logging
            log = logging.getLogger("whirltube.window")
            log.debug("row kind=%s title=%s", v.kind, v.title)
            row = ResultRow(
                video=v,
                on_play=self._play_video,
                on_download_opts=self._download_options,
                on_open=self._open_item,
                on_related=self._on_related,
                on_comments=self._on_comments,
                thumb_loader_pool=self._thumb_loader_pool,
                http_proxy=(self.settings.get("http_proxy") or None),
                on_follow=self._follow_channel,
                on_unfollow=self._unfollow_channel,
                followed=is_followed(v.url) if v.kind == "channel" else False,
                on_open_channel=self._open_channel_from_video,
                on_toast=self._show_toast,
            )
            self.results_box.append(row)

    def _follow_channel(self, video: Video) -> None:
        try:
            add_subscription(video.url, video.title)
        except Exception:
            pass

    def _unfollow_channel(self, video: Video) -> None:
        try:
            remove_subscription(video.url)
        except Exception:
            pass

    # ---------- Item actions ----------

    def _open_item(self, video: Video) -> None:
        # For playlists/channels/comments: open URL to list inner entries or view.
        if video.kind == "playlist":
            self._open_playlist(video.url)
        elif video.kind == "channel":
            self._open_channel(video.url)
        elif video.kind == "comment":
            self._browse_url(video.url)
        else:
            self._play_video(video)

    def _open_playlist(self, url: str) -> None:
        self._show_loading("Opening playlist…")

        def worker():
            vids = self.provider.playlist(url)
            GLib.idle_add(self._populate_results, vids)

        threading.Thread(target=worker, daemon=True).start()

    def _open_channel(self, url: str) -> None:
        self._show_loading("Opening channel…")

        def worker():
            vids = self.provider.channel_tab(url, "videos")
            GLib.idle_add(self._populate_results, vids)

        threading.Thread(target=worker, daemon=True).start()

    def _on_related(self, video: Video) -> None:
        self._show_loading(f"Related to: {video.title}")

        def worker():
            vids = self.provider.related(video.url)
            GLib.idle_add(self._populate_results, vids)

        threading.Thread(target=worker, daemon=True).start()

    def _on_comments(self, video: Video) -> None:
        self._show_loading(f"Comments for: {video.title}")

        def worker():
            vids = self.provider.comments(video.url, max_comments=100)
            GLib.idle_add(self._populate_results, vids)

        threading.Thread(target=worker, daemon=True).start()

    def _open_channel_from_video(self, video: Video) -> None:
        # Resolve channel URL from a video, then open channel view
        self._show_loading(f"Opening channel for: {video.title}")
        def worker():
            try:
                url = self.provider.channel_url_of(video.url)
            except Exception:
                url = None
            if not url:
                GLib.idle_add(self._show_error, "Unable to resolve channel for this video.")
                return
            # Reuse existing channel opener
            def go():
                self._open_channel(url)
                return False
            GLib.idle_add(go)
        threading.Thread(target=worker, daemon=True).start()

    def _play_video(self, video: Video) -> None:
        # Log that the function was called to help with debugging
        log.debug("_play_video called: url=%s", video.url)
        # Save to watch history
        add_watch(video)

        mode = self.settings.get("playback_mode", "external")
        mpv_args = self.settings.get("mpv_args", "") or ""
        
        # Detect Wayland/X11
        session = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
        is_wayland = session == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))
        log.debug("Play requested: url=%s mode=%s wayland=%s", video.url, mode, is_wayland)

        # Embedded on Wayland? Fall back
        if mode == "embedded" and is_wayland:
            log.debug("Detected embedded mode on Wayland - falling back to external")
            self._show_toast("In-window playback is X11-only. Using external player on Wayland.")
            mode = "external"

        # Quality preset
        q = (self.settings.get("mpv_quality") or "auto").strip()
        if q and q != "auto":
            try:
                h = int(q)
                ytdl_fmt = f'bv*[height<={h}]+ba/b[height<={h}]'
                mpv_args = f'{mpv_args} --ytdl-format="{ytdl_fmt}"'.strip()
            except Exception:
                pass

        # Optional cookies for playback
        if self.settings.get("mpv_cookies_enable"):
            cookie_arg = self._mpv_cookie_arg()
            if cookie_arg:
                mpv_args = f"{mpv_args} {cookie_arg}".strip()

        # Add fullscreen option if enabled in settings
        if bool(self.settings.get("mpv_fullscreen")):
            mpv_args = f"{mpv_args} --fs".strip()

        extra_platform_args: list[str] = []
        # Wayland grouping (if mpv supports it)
        if is_wayland and mpv_supports_option("wayland-app-id"):
            extra_platform_args.append(f"--wayland-app-id={APP_ID}")

        # X11 grouping via WM_CLASS (if supported)
        if not is_wayland and mpv_supports_option("class"):
            # Sets WM_CLASS (X11); harmless on Wayland builds that accept it
            extra_platform_args.append(f"--class={APP_ID}")

        try:
            base_args = shlex.split(mpv_args)
        except Exception:
            log.warning("Failed to parse MPV args; launching without user args")
            base_args = []
        final_mpv_args_list = base_args + extra_platform_args

        # Try embedded first only when actually allowed
        if mode == "embedded":
            log.debug("Attempting embedded playback")
            ok = self.mpv_widget.play(video.url)
            if ok:
                log.debug("Embedded playback started successfully")
                self.navigation_controller.show_view("player")
                return
            else:
                log.debug("Embedded playback failed, falling back to external")
        else:
            log.debug("Using external playback mode")

        if not has_mpv():
            self._show_error("MPV not found in PATH.")
            return

        # Proxy for mpv/yt-dlp
        extra_env = {}
        proxy = (self.settings.get("http_proxy") or "").strip()
        if proxy:
            extra_env["http_proxy"] = proxy
            extra_env["https_proxy"] = proxy

        # Unique IPC path per launch to avoid collisions
        rnd = secrets.token_hex(4)
        ipc_dir = Path(tempfile.gettempdir())
        ipc_path = str(ipc_dir / f"whirltube-mpv-{os.getpid()}-{rnd}.sock")

        # Optional: write mpv logs to /tmp when WHIRLTUBE_DEBUG=1
        log_file = None
        if os.environ.get("WHIRLTUBE_DEBUG"):
            log_file = str(ipc_dir / f"whirltube-mpv-{os.getpid()}-{rnd}.log")

        log.debug("Launching mpv: args=%s proxy=%s", final_mpv_args_list, bool(proxy))
        # Log the actual command being executed for debugging
        mpv_cmd_parts = ["mpv", "--force-window=yes"] 
        if ipc_path:
            mpv_cmd_parts.append(f"--input-ipc-server={ipc_path}")
        if log_file:
            mpv_cmd_parts.extend(["--msg-level=all=v", f"--log-file={log_file}"])
        mpv_cmd_parts.extend(final_mpv_args_list)
        mpv_cmd_parts.append(video.url)
        log.debug("MPV command: %s", " ".join(shlex.quote(arg) for arg in mpv_cmd_parts))
        if os.environ.get("WHIRLTUBE_DEBUG"):
            # Show a simplified command in the toast to avoid overwhelming the user
            simplified_cmd = ["mpv"] + [arg for arg in final_mpv_args_list if not arg.startswith("--input-ipc-server") and not arg.startswith("--log-file")] + [video.url]
            self._show_toast(f"Launching mpv: {' '.join(shlex.quote(arg) for arg in simplified_cmd)}")
        
        try:
            proc = start_mpv(
                video.url,
                extra_args=final_mpv_args_list,
                ipc_server_path=ipc_path,
                extra_env=extra_env,
                log_file_path=log_file,
            )

            # Store for later cleanup and control
            self._mpv_proc = proc
            self._mpv_ipc = ipc_path
            self._mpv_current_url = video.url
            self._mpv_speed = 1.0
            self.ctrl_bar.set_visible(self._is_mpv_controls_visible())
            # Enable stop action (and implicitly other mpv actions if desired)
            try:
                self._act_stop_mpv.set_enabled(True)
            except Exception:
                pass

            # Watcher thread: hide controls on exit
            def _watch():
                try:
                    proc.wait()
                except Exception:
                    pass
                GLib.idle_add(self._on_mpv_exit)
            threading.Thread(target=_watch, daemon=True).start()
        except Exception as e:
            log.error("Failed to start mpv: %s", e)
            if os.environ.get("WHIRLTUBE_DEBUG") and 'log_file' in locals() and log_file:
                self._show_error(f"Failed to start mpv. See log: {log_file}")
            else:
                self._show_error("Failed to start mpv. See logs for details.")

    def _on_mpv_exit(self) -> None:
        # Clean up the IPC socket file
        try:
            if getattr(self, "_mpv_ipc", None) and os.path.exists(self._mpv_ipc):
                os.remove(self._mpv_ipc)
        except OSError as e:
            log.warning("Failed to remove mpv IPC socket %s: %s", getattr(self, "_mpv_ipc", ""), e)

        self._mpv_proc = None
        self._mpv_ipc = None
        self.ctrl_bar.set_visible(False)
        try:
            self._act_stop_mpv.set_enabled(False)
        except Exception:
            pass

    def _mpv_copy_ts(self) -> None:
        if not self._mpv_ipc:
            return
        # Ask mpv for current playback position
        pos = 0
        try:
            resp = mpv_send_cmd(self._mpv_ipc, ["get_property", "time-pos"])
            if isinstance(resp, dict) and "data" in resp:
                v = resp.get("data")
                if isinstance(v, (int, float)):
                    pos = int(v)
        except Exception:
            pos = 0
        url = self._mpv_current_url or ""
        if not url:
            # Try to get from MPV path property as fallback
            try:
                resp2 = mpv_send_cmd(self._mpv_ipc, ["get_property", "path"])
                if isinstance(resp2, dict) and isinstance(resp2.get("data"), str):
                    url = str(resp2["data"])
            except Exception:
                pass
        if not url:
            return
        sep = "&" if "?" in url else "?"
        stamped = f"{url}{sep}t={pos}s"
        try:
            disp = Gdk.Display.get_default()
            if disp:
                disp.get_clipboard().set_text(stamped)
        except Exception:
            pass
        self._show_toast(f"Copied URL at {pos}s")

    def _is_mpv_controls_visible(self) -> bool:
        # Only show controls if MPV running
        if self._mpv_proc is None:
            return False
        # honor autohide preference: show only on player view when enabled
        if bool(self.settings.get("mpv_autohide_controls")):
            return (self.stack.get_visible_child_name() == "player")
        return True

    def _on_stack_changed(self, *_a) -> None:
        try:
            self.ctrl_bar.set_visible(self._is_mpv_controls_visible())
        except Exception:
            pass

    def _mpv_cookie_arg(self) -> str:
        browser = (self.settings.get("mpv_cookies_browser") or "").strip()
        if not browser:
            return ""
        keyring = (self.settings.get("mpv_cookies_keyring") or "").strip()
        profile = (self.settings.get("mpv_cookies_profile") or "").strip()
        container = (self.settings.get("mpv_cookies_container") or "").strip()
        val = browser
        if keyring:
            val += f"+{keyring}"
        if profile or container:
            val += f":{profile}"
        if container:
            val += f"::{container}"
        return f'--ytdl-raw-options=cookies-from-browser={val}'

    def _mpv_cycle_pause(self) -> None:
        if not self._mpv_ipc:
            return
        mpv_send_cmd(self._mpv_ipc, ["cycle", "pause"])

    def _mpv_seek(self, secs: int) -> None:
        if not self._mpv_ipc:
            return
        mpv_send_cmd(self._mpv_ipc, ["seek", secs, "relative"])

    def _mpv_speed_delta(self, delta: float) -> None:
        if not self._mpv_ipc:
            return
        try:
            self._mpv_speed = max(0.1, min(4.0, self._mpv_speed + delta))
        except Exception:
            self._mpv_speed = 1.0
        mpv_send_cmd(self._mpv_ipc, ["set_property", "speed", round(self._mpv_speed, 2)])

    def _mpv_stop(self) -> None:
        # Prefer quit over kill where possible
        if self._mpv_ipc:
            mpv_send_cmd(self._mpv_ipc, ["quit"])
        proc = getattr(self, "_mpv_proc", None)
        if proc:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._mpv_proc = None
        self._mpv_ipc = None
        self.ctrl_bar.set_visible(False)

    def _filters_load_from_settings(self) -> None:
        dur = (self.settings.get("search_duration") or "any").lower()
        per = (self.settings.get("search_period") or "any").lower()
        ordv = (self.settings.get("search_order") or "relevance").lower()
        # Map to indices
        dur_idx = {"any":0, "short":1, "medium":2, "long":3}.get(dur, 0)
        per_idx = {"any":0, "today":1, "week":2, "month":3}.get(per, 0)
        ord_idx = {"relevance":0, "date":1, "views":2}.get(ordv, 0)
        try:
            self.dd_dur.set_selected(dur_idx)
            self.dd_period.set_selected(per_idx)
            self.dd_order.set_selected(ord_idx)
        except Exception:
            pass

    def _filters_apply(self, *_a) -> None:
        # Save UI selections into settings and persist
        dur_map = {0:"any", 1:"short", 2:"medium", 3:"long"}
        per_map = {0:"any", 1:"today", 2:"week", 3:"month"}
        ord_map = {0:"relevance", 1:"date", 2:"views"}
        self.settings["search_duration"] = dur_map.get(self.dd_dur.get_selected(), "any")
        self.settings["search_period"] = per_map.get(self.dd_period.get_selected(), "any")
        self.settings["search_order"] = ord_map.get(self.dd_order.get_selected(), "relevance")
        save_settings(self.settings)
        self._filters_pop.popdown()
        # If there is a current query, re-run search with new filters
        try:
            q = (self.search.get_text() or "").strip()
            if q:
                self._run_search(q)
        except Exception:
            pass

    def _filters_clear(self, *_a) -> None:
        self.settings["search_duration"] = "any"
        self.settings["search_period"] = "any"
        self.settings["search_order"] = "relevance"
        save_settings(self.settings)
        self._filters_load_from_settings()
        # Optionally re-run current search after clearing
        try:
            q = (self.search.get_text() or "").strip()
            if q:
                self._run_search(q)
        except Exception:
            pass

    # ---------- Downloads ----------

    def _download_options(self, video: Video) -> None:
        dlg = DownloadOptionsWindow(self, video.title)

        def fetch_formats(_btn):
            dlg.begin_format_fetch()
            def worker() -> None:
                try:
                    fmts = self.provider.fetch_formats(video.url)
                except Exception:
                    fmts = []
                GLib.idle_add(dlg.set_formats, fmts)

        dlg.btn_fetch.connect("clicked", fetch_formats)
        dlg.present()

        def after_close(_w, *_a):
            accepted, opts = dlg.get_options()
            if accepted:
                self._download_video_with_options(video, opts)

        dlg.connect("close-request", after_close)

    def _download_video_with_options(self, video: Video, opts: DownloadOptions) -> None:
        self.download_manager.start_download(video, opts)

    def _show_downloads(self, *_args) -> None:
        self.navigation_controller.show_view("downloads")

    def _open_download_dir(self, *_a) -> None:
        try:
            p = self.download_dir
            if isinstance(p, Path):
                Gio.AppInfo.launch_default_for_uri(p.as_uri(), None)
        except Exception:
            pass


class ResultRow(Gtk.Box):
    def __init__(
        self,
        video: Video,
        on_play: Callable[[Video], None],
        on_download_opts: Callable[[Video], None],
        on_open: Callable[[Video], None],
        on_related: Callable[[Video], None],
        on_comments: Callable[[Video], None],
        thumb_loader_pool: ThreadPoolExecutor,
        http_proxy: str | None = None,
        on_follow: Callable[[Video], None] | None = None,
        on_unfollow: Callable[[Video], None] | None = None,
        followed: bool = False,
        on_open_channel: Callable[[Video], None] | None = None,
        on_toast: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.video = video
        self.on_play = on_play
        self.on_download_opts = on_download_opts
        self.on_open = on_open
        self.on_related = on_related
        self.on_comments = on_comments
        self.on_open_channel = on_open_channel
        self.thumb_loader_pool = thumb_loader_pool
        self.on_follow = on_follow
        self.on_unfollow = on_unfollow
        self._followed = followed
        self._http_proxy = http_proxy
        self.on_toast = on_toast
        self._proxies = safe_httpx_proxy(http_proxy)

        self.set_margin_top(6)
        self.set_margin_bottom(6)

        # Thumbnail stack with placeholder and image
        self.thumb_stack = Gtk.Stack()
        self.thumb_stack.set_size_request(160, 90)
        
        # Create placeholder widget once
        self.thumb_placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.thumb_placeholder.set_size_request(160, 90)
        self.thumb_placeholder.set_halign(Gtk.Align.FILL)
        self.thumb_placeholder.set_valign(Gtk.Align.FILL)
        lbl = Gtk.Label(label="No thumbnail")
        lbl.set_halign(Gtk.Align.CENTER)
        lbl.set_valign(Gtk.Align.CENTER)
        lbl.add_css_class("dim-label")
        lbl.set_wrap(True)
        self.thumb_placeholder.append(lbl)
        
        # Create picture widget once
        self.thumb = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
        self.thumb.set_size_request(160, 90)
        
        # Add both to stack
        self.thumb_stack.add_named(self.thumb_placeholder, "placeholder")
        self.thumb_stack.add_named(self.thumb, "picture")
        self.append(self.thumb_stack)

        # Texts
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        title = Gtk.Label(label=video.title, wrap=True, xalign=0.0)
        title.add_css_class("title-3")
        meta = Gtk.Label(label=_fmt_meta(video), xalign=0.0)
        meta.add_css_class("dim-label")
        box.append(title)
        box.append(meta)
        self.append(box)

        # Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        if video.is_playable:
            play_btn = Gtk.Button(label="Play")
            play_btn.connect("clicked", self._on_play_clicked)
            dl_btn = Gtk.Button(label="Download…")
            dl_btn.connect("clicked", self._on_download_clicked)
            btn_box.append(play_btn)
            btn_box.append(dl_btn)
            # Compact "More…" menu
            more = Gtk.MenuButton(label="More…")
            pop = Gtk.Popover()
            vbx = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
            b_rel = Gtk.Button(label="Related")
            b_rel.connect("clicked", lambda *_: self.on_related(self.video))
            b_cmt = Gtk.Button(label="Comments")
            b_cmt.connect("clicked", lambda *_: self.on_comments(self.video))
            b_ch = Gtk.Button(label="Open channel")
            b_ch.set_tooltip_text("Open the uploader's channel")
            b_ch.connect("clicked", lambda *_: self.on_open_channel(self.video))
            b_web = Gtk.Button(label="Open in Browser")
            b_web.connect("clicked", lambda *_: self._open_in_browser())
            b_cu = Gtk.Button(label="Copy URL")
            b_cu.connect("clicked", lambda *_: self._copy_url())
            b_ct = Gtk.Button(label="Copy Title")
            b_ct.connect("clicked", lambda *_: self._copy_title())
            for b in (b_rel, b_cmt, b_ch, b_web, b_cu, b_ct):
                vbx.append(b)
            pop.set_child(vbx)
            more.set_popover(pop)
            btn_box.append(more)
        else:
            # Non-playable kinds
            if self.video.kind == "playlist":
                open_btn = Gtk.Button(label="Open")
                open_btn.set_tooltip_text("Open this playlist")
                open_btn.connect("clicked", lambda *_: self.on_open(self.video))
                btn_box.append(open_btn)
                # Playlist may be downloaded (folder structure)
                dl_btn = Gtk.Button(label="Download…")
                dl_btn.connect("clicked", lambda *_: self.on_download_opts(self.video))
                btn_box.append(dl_btn)
            elif self.video.kind == "channel":
                open_btn = Gtk.Button(label="Open")
                open_btn.set_tooltip_text("Open this channel")
                open_btn.connect("clicked", lambda *_: self.on_open(self.video))
                btn_box.append(open_btn)
                label = "Unfollow" if self._followed else "Follow"
                follow_btn = Gtk.Button(label=label)
                def _toggle_follow(_btn):
                    try:
                        if self._followed:
                            if self.on_unfollow:
                                self.on_unfollow(self.video)
                            self._followed = False
                            _btn.set_label("Follow")
                            if self.on_toast:
                                self.on_toast("Unfollowed channel")
                        else:
                            if self.on_follow:
                                self.on_follow(self.video)
                            self._followed = True
                            _btn.set_label("Unfollow")
                            if self.on_toast:
                                self.on_toast("Followed channel")
                    except Exception:
                        pass
                follow_btn.connect("clicked", _toggle_follow)
                btn_box.append(follow_btn)
            else:
                # comment or other: no "Open" or "Download…" actions
                pass
            # Compact "More…" for common actions
            more = Gtk.MenuButton(label="More…")
            pop = Gtk.Popover()
            vbx = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
            b_web = Gtk.Button(label="Open in Browser")
            b_web.connect("clicked", lambda *_: self._open_in_browser())
            b_cu = Gtk.Button(label="Copy URL")
            b_cu.connect("clicked", lambda *_: self._copy_url())
            b_ct = Gtk.Button(label="Copy Title")
            b_ct.connect("clicked", lambda *_: self._copy_title())
            for b in (b_web, b_cu, b_ct):
                vbx.append(b)
            pop.set_child(vbx)
            more.set_popover(pop)
            btn_box.append(more)
        self.append(btn_box)

        # Load thumbnail
        if video.thumb_url:
            self.thumb_loader_pool.submit(self._load_thumb)
        else:
            # No URL -> placeholder
            GLib.idle_add(self._set_thumb_placeholder)

    def _on_play_clicked(self, *_a):
        import logging
        log = logging.getLogger("whirltube.window")
        try:
            log.debug("ResultRow Play clicked: %s (%s)", self.video.title, self.video.url)
            if callable(self.on_play):
                self.on_play(self.video)
            else:
                log.error("on_play is not callable: %r", self.on_play)
        except Exception as e:
            log.exception("on_play failed: %s", e)

    def _on_download_clicked(self, *_a):
        import logging
        log = logging.getLogger("whirltube.window")
        log.debug("ResultRow Download clicked: %s", self.video.title)
        if callable(self.on_download_opts):
            self.on_download_opts(self.video)

    def _load_thumb(self) -> None:
        # Try with proxy (if valid), then fallback without
        data: bytes | None = None
        try:
            # For httpx 0.28.1+, use proxy parameter directly when _proxies is a string
            if self._proxies:
                with httpx.Client(timeout=10.0, follow_redirects=True, proxy=self._proxies, headers=HEADERS) as client:
                    r = client.get(self.video.thumb_url)  # type: ignore[arg-type]
                    r.raise_for_status()
                    data = r.content
            else:
                # No proxy configured
                with httpx.Client(timeout=10.0, follow_redirects=True, headers=HEADERS) as client:
                    r = client.get(self.video.thumb_url)  # type: ignore[arg-type]
                    r.raise_for_status()
                    data = r.content
        except Exception:
            data = None
            # Fallback: retry without proxy if we had one
            try:
                with httpx.Client(timeout=10.0, follow_redirects=True, headers=HEADERS) as client2:
                    r2 = client2.get(self.video.thumb_url)  # type: ignore[arg-type]
                    r2.raise_for_status()
                    data = r2.content
            except Exception:
                data = None
        if data is None:
            GLib.idle_add(self._set_thumb_placeholder)
            return
        GLib.idle_add(self._set_thumb, data)

    def _set_thumb(self, data: bytes) -> None:
        # Check content type and convert WebP to JPEG if needed
        try:
            # First try to load directly
            loader = GdkPixbuf.PixbufLoader()
            loader.write(data)
            loader.close()
            pixbuf = loader.get_pixbuf()
            
            if pixbuf is None:
                # If direct load fails, try to detect content type
                if data.startswith(b'RIFF') and b'WEBP' in data[:12]:
                    # This is a WebP image, try to convert it
                    import io
                    try:
                        from PIL import Image
                        img = Image.open(io.BytesIO(data))
                        # Convert WebP to JPEG in memory
                        output = io.BytesIO()
                        img.convert('RGB').save(output, format='JPEG')
                        jpeg_data = output.getvalue()
                        
                        # Now load the JPEG
                        loader2 = GdkPixbuf.PixbufLoader()
                        loader2.write(jpeg_data)
                        loader2.close()
                        pixbuf = loader2.get_pixbuf()
                    except ImportError:
                        # PIL not available, show placeholder
                        self._set_thumb_placeholder()
                        return
                    except Exception:
                        # Conversion failed, show placeholder
                        self._set_thumb_placeholder()
                        return
            
            if pixbuf:
                # Check for tiny placeholder images (e.g. 1x1)
                if pixbuf.get_width() < 10 or pixbuf.get_height() < 10:
                    self._set_thumb_placeholder()
                    return
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                self.thumb.set_paintable(texture)
                # Show the picture in the stack
                self.thumb_stack.set_visible_child_name("picture")
                return
        except Exception:
            pass
        # If decoding fails, show placeholder
        self._set_thumb_placeholder()

    def _set_thumb_placeholder(self) -> None:
        # Show the placeholder in the stack
        self.thumb_stack.set_visible_child_name("placeholder")

    def _open_in_browser(self) -> None:
        try:
            if self.video and self.video.url:
                Gio.AppInfo.launch_default_for_uri(self.video.url, None)
        except Exception:
            pass

    def _copy_url(self) -> None:
        text = self.video.url or ""
        if not text:
            return
        def do_copy():
            try:
                disp = Gdk.Display.get_default()
                if disp:
                    try:
                        disp.get_clipboard().set_text(text)
                    except Exception:
                        # best-effort fallback
                        disp.get_primary_clipboard().set_text(text)
                    if self.on_toast:
                        self.on_toast("URL copied to clipboard")
            except Exception:
                pass
            return False
        GLib.idle_add(do_copy)

    def _copy_title(self) -> None:
        text = self.video.title or ""
        if not text:
            return
        def do_copy():
            try:
                disp = Gdk.Display.get_default()
                if disp:
                    try:
                        disp.get_clipboard().set_text(text)
                    except Exception:
                        # best-effort fallback
                        disp.get_primary_clipboard().set_text(text)
                    if self.on_toast:
                        self.on_toast("Title copied to clipboard")
            except Exception:
                pass
            return False
        GLib.idle_add(do_copy)

def _fmt_meta(v: Video) -> str:
    ch = v.channel or "Unknown channel"
    dur = v.duration_str
    base = f"{ch} • {dur}" if dur else ch
    if v.kind in ("playlist", "channel"):
        return f"{base} • {v.kind}"
    return base


def _spacer(px: int) -> Gtk.Box:
    b = Gtk.Box()
    b.set_size_request(-1, px)
    return b