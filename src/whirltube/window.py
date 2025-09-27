from __future__ import annotations

import logging
import os
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from urllib.parse import urlparse
from pathlib import Path

import gi
import httpx

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk

from . import __version__
from .dialogs import DownloadOptions, DownloadOptionsWindow, PreferencesWindow
from .history import add_search_term, add_watch, list_watch
from .models import Video
from .mpv_embed import MpvWidget
from .player import has_mpv, start_mpv, mpv_send_cmd
from .provider import YTDLPProvider
from .invidious_provider import InvidiousProvider
from .download_manager import DownloadManager
from .search_filters import normalize_search_filters
from .navigation_controller import NavigationController
from .download_history import list_downloads
from .subscriptions import is_followed, add_subscription, remove_subscription, list_subscriptions, export_subscriptions, import_subscriptions
from .quickdownload import QuickDownloadWindow
from .util import load_settings, save_settings, xdg_data_dir, safe_httpx_proxy, is_valid_youtube_url

log = logging.getLogger(__name__)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="WhirlTube")
        # Use persisted window size
        try:
            w = int(self.settings.get("win_w") or 1080)
            h = int(self.settings.get("win_h") or 740)
        except Exception:
            w, h = 1080, 740
        self.set_default_size(w, h)
        self.set_icon_name("whirltube")

        self.settings = load_settings()
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
        # Window size persistence
        self.settings.setdefault("win_w", 1080)
        self.settings.setdefault("win_h", 740)
        # Initialize provider with global proxy and optional Invidious
        proxy = (self.settings.get("http_proxy") or "").strip() or None
        if bool(self.settings.get("use_invidious")):
            base = (self.settings.get("invidious_instance") or "https://yewtu.be").strip()
            self.provider = InvidiousProvider(base, proxy=proxy, fallback=YTDLPProvider(proxy or None))
        else:
            self.provider = YTDLPProvider(proxy or None)
        self._search_generation = 0
        self._thumb_loader_pool = ThreadPoolExecutor(max_workers=4)

        # ToolbarView
        self.toolbar_view = Adw.ToolbarView()
        self.set_content(self.toolbar_view)

        # Header
        header = Adw.HeaderBar()
        self.toolbar_view.add_top_bar(header)

        # MPV control bar (hidden by default; shown for external MPV)
        self.ctrl_bar = Adw.HeaderBar()
        self.ctrl_bar.set_title_widget(Gtk.Label(label="MPV Controls", css_classes=["dim-label"]))
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
        self.btn_stop_mpv.connect("clicked", lambda *_: self._mpv_stop())
        # Pack controls on the right
        self.ctrl_bar.pack_end(self.btn_stop_mpv)
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

        self.btn_qdl = Gtk.Button(label="Quick Download")
        self.btn_qdl.set_tooltip_text("Batch download multiple URLs")
        self.btn_qdl.connect("clicked", self._on_quick_download)
        header.pack_start(self.btn_qdl)

        # Search
        self.search = Gtk.SearchEntry(hexpand=True)
        self.search.set_placeholder_text("Search YouTube…")
        header.set_title_widget(self.search)
        self.search.connect("activate", self._on_search_activate)

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
        self.downloads_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._set_margins(self.downloads_box, 8)
        downloads_scroll = Gtk.ScrolledWindow(vexpand=True)
        downloads_scroll.set_child(self.downloads_box)
        self.stack.add_titled(downloads_scroll, "downloads", "Downloads")

        # Player (embedded mpv)
        self.player_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._set_margins(self.player_box, 0)
        self.mpv_widget = MpvWidget()
        self.player_box.append(self.mpv_widget)
        self.stack.add_titled(self.player_box, "player", "Player")

        self.toolbar_view.set_content(self.stack)

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

        self._create_actions()
        self._set_welcome()
        self._install_shortcuts()

        # MPV external player state
        self._mpv_proc = None
        self._mpv_ipc = None
        self._mpv_speed = 1.0

        # Save settings on window close
        self.connect("close-request", self._on_main_close)
        # React to stack page changes for MPV controls visibility
        self.stack.connect("notify::visible-child", self._on_stack_changed)

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

    def _create_actions(self) -> None:
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._on_about)
        self.add_action(about)

        prefs = Gio.SimpleAction.new("preferences", None)
        prefs.connect("activate", self._on_preferences)
        self.add_action(prefs)

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
        grp_app.append(Gtk.ShortcutsShortcut(title="Quit", accelerator="<Primary>q"))
        # Search group
        grp_search = Gtk.ShortcutsGroup(title="Search")
        grp_search.append(Gtk.ShortcutsShortcut(title="Run search", accelerator="Return"))
        # Player/MPV controls (external; via control bar)
        grp_play = Gtk.ShortcutsGroup(title="MPV Controls (when visible)")
        grp_play.append(Gtk.ShortcutsShortcut(title="Seek backward 10s", accelerator="button"))
        grp_play.append(Gtk.ShortcutsShortcut(title="Play/Pause", accelerator="button"))
        grp_play.append(Gtk.ShortcutsShortcut(title="Seek forward 10s", accelerator="button"))
        grp_play.append(Gtk.ShortcutsShortcut(title="Speed - / +", accelerator="button"))
        grp_play.append(Gtk.ShortcutsShortcut(title="Stop", accelerator="button"))
        # Assemble
        sec.append(grp_nav)
        sec.append(grp_app)
        sec.append(grp_search)
        sec.append(grp_play)
        win.add(sec)
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
        # Choose a folder, write subscriptions.json into it
        dlg = Gtk.FileDialog(title="Choose export folder")
        def on_done(d, res, *_):
            try:
                f = d.select_folder_finish(res)
            except Exception:
                return
            path = f.get_path()
            if not path:
                return
            dest = Path(path) / "subscriptions.json"
            try:
                export_subscriptions(dest)
            except Exception:
                pass
        dlg.select_folder(self, None, on_done, None)

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
                        if not is_valid_youtube_url(url, extra):
                            self._show_error("This doesn't look like a YouTube/Invidious URL.")
                        else:
                            self._browse_url(url)
            finally:
                d.destroy()

        dlg.connect("response", on_response)

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
        # Save to watch history
        add_watch(video)

        mode = self.settings.get("playback_mode", "external")
        mpv_args = self.settings.get("mpv_args", "") or ""
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

        if mode == "embedded":
            ok = self.mpv_widget.play(video.url)
            if ok:
                self.navigation_controller.show_view("player")
                return

        if not has_mpv():
            self._show_error("MPV not found in PATH.")
            return
        try:
            # Unique IPC path per launch to avoid collisions
            rnd = secrets.token_hex(4)
            ipc_path = f"/tmp/whirltube-mpv-{os.getpid()}-{rnd}.sock"
            proc = start_mpv(video.url, extra_args=mpv_args, ipc_server_path=ipc_path)
            self._mpv_proc = proc
            self._mpv_ipc = ipc_path
            self._mpv_speed = 1.0
            self.ctrl_bar.set_visible(self._is_mpv_controls_visible())

            # Watcher thread: hide controls on exit
            def _watch():
                try:
                    proc.wait()
                except Exception:
                    pass
                GLib.idle_add(self._on_mpv_exit)
            threading.Thread(target=_watch, daemon=True).start()
        except Exception as e:
            self._show_error(f"Failed to start MPV: {e}")

    def _on_mpv_exit(self) -> None:
        self._mpv_proc = None
        self._mpv_ipc = None
        self.ctrl_bar.set_visible(False)

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

    def _filters_clear(self, *_a) -> None:
        self.settings["search_duration"] = "any"
        self.settings["search_period"] = "any"
        self.settings["search_order"] = "relevance"
        save_settings(self.settings)
        self._filters_load_from_settings()

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
        self._proxies = safe_httpx_proxy(http_proxy)

        self.set_margin_top(6)
        self.set_margin_bottom(6)

        # Thumbnail
        self.thumb = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
        self.thumb.set_size_request(160, 90)
        self.append(self.thumb)

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
            play_btn.connect("clicked", lambda *_: self.on_play(self.video))
            dl_btn = Gtk.Button(label="Download…")
            dl_btn.connect("clicked", lambda *_: self.on_download_opts(self.video))
            rel_btn = Gtk.Button(label="Related")
            rel_btn.connect("clicked", lambda *_: self.on_related(self.video))
            cmt_btn = Gtk.Button(label="Comments")
            cmt_btn.connect("clicked", lambda *_: self.on_comments(self.video))
            ch_btn = Gtk.Button(label="Open channel")
            ch_btn.set_tooltip_text("Open the uploader's channel")
            ch_btn.connect("clicked", lambda *_: self.on_open_channel(self.video))
            btn_box.append(play_btn)
            btn_box.append(dl_btn)
            btn_box.append(rel_btn)
            btn_box.append(cmt_btn)
            btn_box.append(ch_btn)
        else:
            # Non-playable: show Open; if channel, also Follow/Unfollow
            open_btn = Gtk.Button(label="Open")
            open_btn.set_tooltip_text("Open this playlist/channel")
            open_btn.connect("clicked", lambda *_: self.on_open(self.video))
            btn_box.append(open_btn)
            if self.video.kind == "channel":
                label = "Unfollow" if self._followed else "Follow"
                follow_btn = Gtk.Button(label=label)
                def _toggle_follow(_btn):
                    try:
                        if self._followed:
                            if self.on_unfollow: 
                                self.on_unfollow(self.video)
                            self._followed = False
                            _btn.set_label("Follow")
                        else:
                            if self.on_follow: 
                                self.on_follow(self.video)
                            self._followed = True
                            _btn.set_label("Unfollow")
                    except Exception:
                        pass
                follow_btn.connect("clicked", _toggle_follow)
                btn_box.append(follow_btn)
        # Common actions: open in browser, copy URL
        open_web = Gtk.Button(label="Open in Browser")
        open_web.connect("clicked", lambda *_: self._open_in_browser())
        copy_url = Gtk.Button(label="Copy URL")
        copy_url.connect("clicked", lambda *_: self._copy_url())
        copy_title = Gtk.Button(label="Copy Title")
        copy_title.connect("clicked", lambda *_: self._copy_title())
        # Add spacing between common actions group and primary actions
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        btn_box.append(sep)
        btn_box.append(open_web)
        btn_box.append(copy_url)
        btn_box.append(copy_title)
        self.append(btn_box)

        # Load thumbnail
        if video.thumb_url:
            self.thumb_loader_pool.submit(self._load_thumb)
        else:
            # No URL -> placeholder
            GLib.idle_add(self._set_thumb_placeholder)

    def _load_thumb(self) -> None:
        # Try with proxy (if valid), then fallback without
        data: bytes | None = None
        try:
            with httpx.Client(timeout=10.0, follow_redirects=True, proxies=self._proxies) as client:
                r = client.get(self.video.thumb_url)  # type: ignore[arg-type]
                r.raise_for_status()
                data = r.content
        except Exception:
            data = None
            # Fallback: retry without proxy if we had one
            try:
                if self._proxies:
                    with httpx.Client(timeout=10.0, follow_redirects=True) as client2:
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
        loader = GdkPixbuf.PixbufLoader()
        try:
            loader.write(data)
            loader.close()
            pixbuf = loader.get_pixbuf()
            if pixbuf:
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                self.thumb.set_paintable(texture)
                return
        except Exception:
            pass
        # If decoding fails, show placeholder
        self._set_thumb_placeholder()

    def _set_thumb_placeholder(self) -> None:
        try:
            # Replace the picture with a placeholder box to keep consistent size
            parent = self.thumb.get_parent()
            if parent is not None:
                parent.remove(self.thumb)
        except Exception:
            pass
        ph = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        ph.set_size_request(160, 90)
        ph.set_halign(Gtk.Align.FILL)
        ph.set_valign(Gtk.Align.FILL)
        lbl = Gtk.Label(label="No thumbnail")
        # Center the placeholder label
        lbl.set_halign(Gtk.Align.CENTER)
        lbl.set_valign(Gtk.Align.CENTER)
        lbl.add_css_class("dim-label")
        lbl.set_wrap(True)
        ph.append(lbl)
        # Put the placeholder at the start (thumbnail slot)
        self.prepend(ph)

    def _open_in_browser(self) -> None:
        try:
            if self.video and self.video.url:
                Gio.AppInfo.launch_default_for_uri(self.video.url, None)
        except Exception:
            pass

    def _copy_url(self) -> None:
        try:
            disp = Gdk.Display.get_default()
            if disp and self.video and self.video.url:
                disp.get_clipboard().set_text(self.video.url)
        except Exception:
            pass

    def _copy_title(self) -> None:
        try:
            disp = Gdk.Display.get_default()
            if disp and self.video and self.video.title:
                disp.get_clipboard().set_text(self.video.title)
        except Exception:
            pass

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