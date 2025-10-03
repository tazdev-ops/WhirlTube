from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import re

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, Gio, GLib, Gtk, Gdk, Pango

from . import __version__
from .dialogs import DownloadOptions, DownloadOptionsWindow, PreferencesWindow
from .history import add_search_term, add_watch, list_watch, search_history_suggestions, clear_search_history, get_search_history_count
from .subscription_feed import is_watched
from .models import Video
from .mpv_embed import MpvWidget
from .providers.ytdlp import YTDLPProvider
from .providers.invidious import InvidiousProvider
from .download_manager import DownloadManager
from .navigation_controller import NavigationController
from .download_history import list_downloads
from .subscriptions import is_followed, add_subscription, remove_subscription, list_subscriptions, export_subscriptions, import_subscriptions
from .watch_later import list_watch_later, clear_watch_later, get_watch_later_count
from .thumbnail_cache import clear_cache as clear_thumbnail_cache, get_cache_stats, cleanup_old_cache, enforce_cache_size_limit
from .quickdownload import QuickDownloadWindow
from .ui.widgets.result_row import ResultRow
from .ui.widgets.mpv_controls import MpvControls
from .services.playback import PlaybackService
from .ui.controllers import search
from .metrics import timed
from .util import load_settings, save_settings, xdg_data_dir, safe_httpx_proxy

# Use GL-based widget for Wayland compatibility if available
# Prefer GL widget on Wayland, fallback to X11 widget on X11
try:
    from .mpv_gl import MpvGLWidget
    HAS_GL_WIDGET = True
except ImportError:
    HAS_GL_WIDGET = False
    MpvGLWidget = None  # type: ignore

# Detect session type for better widget selection
SESSION_TYPE = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
IS_WAYLAND = SESSION_TYPE == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}

THUMB_SIZE = (160, 90)
DEFAULT_SEARCH_LIMIT = 30
DEFAULT_WATCH_HISTORY = 200
DEFAULT_DOWNLOAD_HISTORY = 300
MAX_THUMB_WORKERS = 4
FEED_VIDEOS_PER_CHANNEL = 5

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
        self.settings.setdefault("native_playback", False)

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
        self.settings.setdefault("quick_quality_presets", "1080p,720p,audio")  # NEW
        # SponsorBlock settings
        self.settings.setdefault("sb_playback_enable", False)
        self.settings.setdefault("sb_playback_mode", "mark")  # mark | skip
        self.settings.setdefault("sb_playback_categories", "default")
        # Window size persistence
        self.settings.setdefault("win_w", 1080)
        self.settings.setdefault("win_h", 740)
        self.settings.setdefault("yt_hl", "en")
        self.settings.setdefault("yt_gl", "US")
        self.settings.setdefault("use_ytextractor", False)  # NEW
        
        # Keep track of the current download dialog to prevent GC
        self._current_download_dlg: DownloadOptionsWindow | None = None
        
        # Initialize provider with global proxy and optional Invidious
        proxy_raw = (self.settings.get("http_proxy") or "").strip()
        proxy = safe_httpx_proxy(proxy_raw) if proxy_raw else None

        # Check for ytextractor provider
        if bool(self.settings.get("use_ytextractor")):
            try:
                from .providers.ytextractor_provider import YtExtractorProvider
                hl = (self.settings.get("yt_hl") or "en").strip() or "en"
                gl = (self.settings.get("yt_gl") or "US").strip() or "US"
                self.provider = YtExtractorProvider(proxy=proxy, hl=hl, gl=gl)
                log.info("Using YtExtractor provider (native stream resolution)")
            except Exception as e:
                log.warning(f"Failed to initialize YtExtractor provider: {e}, falling back to yt-dlp")
                self.provider = YTDLPProvider(proxy)
        elif bool(self.settings.get("use_invidious")):
            base = (self.settings.get("invidious_instance") or "https://yewtu.be").strip()
            self.provider = InvidiousProvider(base, proxy=proxy, fallback=YTDLPProvider(proxy))
        else:
            fb = YTDLPProvider(proxy)
            from .providers.innertube_web import InnerTubeWeb
            from .providers.hybrid import HybridProvider
            hl = (self.settings.get("yt_hl") or "en").strip() or "en"
            gl = (self.settings.get("yt_gl") or "US").strip() or "US"
            self.provider = HybridProvider(InnerTubeWeb(hl=hl, gl=gl), fb)
        
        self._search_generation = 0
        self._search_lock = threading.Lock()
        self._thumb_loader_pool = ThreadPoolExecutor(max_workers=MAX_THUMB_WORKERS)
        
        # Create cached suggestion client to avoid creating new instances per keystroke
        self._suggestion_client = None
        self._sugg_timer_id = 0 # Debounce timer for suggestions
        self._sugg_generation = 0 # Generation counter to prevent out-of-order results
        self._last_suggestions_key = "" # Last key used for suggestions
        self._last_suggestions_items: list[str] = [] # Last list of suggestions for comparison
        
        # ToolbarView
        self.toolbar_view = Adw.ToolbarView()
        
        # Header
        header = Adw.HeaderBar()
        self.toolbar_view.add_top_bar(header)
        
        # Initialize MPV controls widget and service
        # Use GL-based widget for Wayland compatibility if available
        # On Wayland, prefer GL widget; on X11, prefer X11 widget
        if IS_WAYLAND and HAS_GL_WIDGET:
            self.mpv_widget = MpvGLWidget()
        elif HAS_GL_WIDGET:
            # Use GL widget as fallback if available (better compatibility)
            self.mpv_widget = MpvGLWidget()
        else:
            # Fallback to X11 widget
            self.mpv_widget = MpvWidget()
        self.playback_service = PlaybackService(self.mpv_widget, self.settings.get)
        self.playback_service.native_playback_enabled = bool(self.settings.get("native_playback"))
        self.mpv_controls = MpvControls(self.playback_service)
        
        # Pass cookies to provider as well (helps trending/region walls)
        try:
            spec = self.playback_service.get_cookie_spec()
            if spec:
                if isinstance(self.provider, YTDLPProvider):
                    self.provider.set_cookies_from_browser(spec)
                elif isinstance(self.provider, InvidiousProvider):
                    # Set cookies on the fallback YTDLPProvider for InvidiousProvider
                    self.provider._fallback.set_cookies_from_browser(spec)
        except Exception:
            pass
        
        # Add the MPV control bar as a top bar
        self.toolbar_view.add_top_bar(self.mpv_controls.get_ctrl_bar())
        self.mpv_controls.get_ctrl_bar().set_visible(False)
        
        # Toast overlay wraps the whole UI
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)
        
        # Back button (NavigationController will connect it)
        self.btn_back = Gtk.Button(icon_name="go-previous-symbolic")
        self.btn_back.set_tooltip_text("Back")
        header.pack_start(self.btn_back)
        
        # Menu - organized by function and usage frequency
        menu = Gio.Menu()
        
        # Primary application actions (high frequency)
        primary_section = Gio.Menu()
        primary_section.append("Preferences", "win.preferences")
        primary_section.append("Keyboard Shortcuts", "win.shortcuts")
        primary_section.append("About", "win.about")
        menu.append_section(None, primary_section)

        # Navigation and Quick Actions (from old primary_btn)
        nav_section = Gio.Menu()
        nav_section.append("Open URL…", "win.open_url")
        nav_section.append("Quick Download", "win.quick_download")
        nav_section.append("History", "win.history")
        nav_section.append("Feed", "win.feed")
        nav_section.append("Trending", "win.trending")
        menu.append_section("Browse", nav_section)
        
        # Content management actions (medium frequency)
        content_section = Gio.Menu()
        content_section.append("Watch Later", "win.watch_later")
        content_section.append("Download History", "win.download_history")
        content_section.append("Manage Subscriptions", "win.subscriptions")
        menu.append_section("Library", content_section)
        
        # Content maintenance (lower frequency, admin-like actions)
        maintenance_section = Gio.Menu()
        maintenance_section.append("Clear Watch Later", "win.clear_watch_later")
        maintenance_section.append("Clear Search History", "win.clear_search_history")
        maintenance_section.append("Clear Thumbnail Cache", "win.clear_thumb_cache")
        maintenance_section.append("Clear Finished Downloads", "win.clear_finished_downloads")
        menu.append_section("Maintenance", maintenance_section)
        
        # Subscriptions management
        subs_section = Gio.Menu()
        subs_section.append("Import Subscriptions…", "win.subs_import")
        subs_section.append("Export Subscriptions…", "win.subs_export")
        menu.append_section("Subscriptions", subs_section)
        
        # Playback and system functions
        system_section = Gio.Menu()
        system_section.append("Copy URL @ time", "win.mpv_copy_ts")
        system_section.append("Stop MPV", "win.stop_mpv")
        system_section.append("System Health Check", "win.health_check")
        system_section.append("Cancel All Downloads", "win.cancel_all_downloads")
        menu.append_section("System", system_section)
        
        # Application exit (always at the end)
        exit_section = Gio.Menu()
        exit_section.append("Quit", "app.quit")
        menu.append_section(None, exit_section)
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_btn.set_menu_model(menu)
        header.pack_start(menu_btn)
        
        # The primary actions menu (primary_btn) and the dedicated Watch Later button
        # have been merged into the main application menu (menu_btn) for simplification.

        # Search with autocomplete
        self.search = Gtk.SearchEntry(hexpand=True)
        self.search.set_can_focus(True)
        self.search.set_placeholder_text("Search YouTube…")
        header.set_title_widget(self.search)
        self.search.connect("activate", self._on_search_activate)
        log.debug("Connected 'activate' for search entry: %s", self.search)
        self.search.connect("search-changed", self._on_search_changed)
        log.debug("Connected 'search-changed' for search entry: %s", self.search)

        # Clear text when the user presses Escape or the clear icon
        def _stop_search(_entry, *_a):
            try:
                self.search.set_text("")
                self._set_welcome()
                # Hide suggestions when clearing
                if hasattr(self, '_search_suggestions_popover'):
                    self._search_suggestions_popover.popdown()
            except Exception:
                import logging
                logging.getLogger("search.debug").exception("Error in _stop_search")
                pass
        self.search.connect("stop-search", _stop_search)

        # Create suggestions popover
        self._create_search_suggestions()

        # Filters popover
        self.btn_filters = Gtk.MenuButton(icon_name="view-list-symbolic")
        self.btn_filters.set_can_focus(True)
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
        self.downloads_button.set_can_focus(True)
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
        
        # Debug: Print all window and app actions
        log.debug("Window actions: %s", list(self.list_actions()))
        app_obj = self.get_application()
        if app_obj:
            log.debug("App actions: %s", list(app_obj.list_actions()))
        
        self._set_welcome()
        self._install_shortcuts()

        # MPV actions (menu + hotkeys) - now using controls widget
        self.mpv_controls.add_actions_to_window(self)
        self._install_key_controller()
        self.playback_service.set_callbacks(
            on_started=self._on_mpv_started,
            on_stopped=self._on_mpv_stopped
        )

        # MPV actions (menu + hotkeys) - set up accelerators
        app_obj = self.get_application()
        if app_obj:
            self.mpv_controls.install_accelerators(app_obj)

        # Cache MPV accelerators to toggle them when search is focused
        self._mpv_accels = {
            "win.mpv_play_pause": ["K", "k"],
            "win.mpv_seek_back": ["J", "j"],
            "win.mpv_seek_fwd": ["L", "l"],
            "win.mpv_speed_down": ["minus", "KP_Subtract"],
            "win.mpv_speed_up": ["equal", "KP_Add"],
            "win.mpv_copy_ts": ["T", "t"],
            "win.stop_mpv": ["X", "x"],
        }
        # Toggle accelerators when search gains/loses focus
        self.search.connect("notify::has-focus", self._on_search_focus_changed)

        # If the entry starts focused, disable accelerators immediately
        if self.search.has_focus():
            self._set_mpv_accels_enabled(False)

        # Track current URL for timestamp copying
        self._mpv_current_url: str | None = None
        self._last_filters: dict[str, str] | None = None



    def _create_search_suggestions(self) -> None:
        """Create search suggestions popover"""
        self._search_suggestions_popover = Gtk.Popover()
        self._search_suggestions_popover.set_parent(self.search)
        self._search_suggestions_popover.set_autohide(True)
        
        # Container for proper sizing
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        container.set_spacing(0)
        
        # Scrolled window for suggestions
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_max_content_height(300)
        scroll.set_min_content_height(50)
        
        # Set initial size (will be updated dynamically)
        scroll.set_size_request(400, 100)
        
        # Enable natural size propagation
        scroll.set_propagate_natural_height(True)
        scroll.set_propagate_natural_width(True)
        
        # List box for suggestions
        self._suggestions_list = Gtk.ListBox()
        self._suggestions_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._suggestions_list.add_css_class("navigation-sidebar")
        
        scroll.set_child(self._suggestions_list)
        container.append(scroll)
        
        self._search_suggestions_popover.set_child(container)
        
        # Store reference to scroll for dynamic sizing
        self._suggestions_scroll = scroll
        
        # Connect row-activated to handle clicks on individual rows
        self._suggestions_list.connect("row-activated", self._on_suggestion_selected)

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        """Handle search text changes for autocomplete with debouncing and latest-only guard."""
        text = entry.get_text().strip()

        # Cancel previous timer if it exists
        if self._sugg_timer_id:
            GLib.source_remove(self._sugg_timer_id)
            self._sugg_timer_id = 0

        if not text:
            self._search_suggestions_popover.popdown()
            return

        def fire():
            # bump generation
            self._sugg_generation += 1
            gen = self._sugg_generation
            prefix = text

            def worker():
                # Local suggestions (existing) - moved to worker thread to prevent UI blocking
                local = search_history_suggestions(prefix, limit=5)
                
                remote = []
                try:
                    # Use self.provider instead of creating new client
                    remote = self.provider.suggestions(prefix, max_items=10)
                    log.debug(f"Got {len(remote)} remote suggestions for '{prefix}'")
                except Exception as e:
                    log.warning(f"Remote suggestions failed: {e}")
                    remote = []
                
                # If user kept typing, drop this result (generation guard)
                if gen != self._sugg_generation or self.search.get_text().strip() != prefix:
                    log.debug(f"Suggestions for '{prefix}' dropped (generation mismatch or text changed)")
                    return
                
                # merge + dedupe
                merged, seen = [], set()
                for s in (local + remote):
                    if s and (s.lower() not in seen):
                        seen.add(s.lower())
                        merged.append(s)
                
                # Avoid re-render if same list for same key
                if self._last_suggestions_key == prefix and self._last_suggestions_items == merged[:10]:
                    return
                
                self._last_suggestions_key = prefix
                self._last_suggestions_items = merged[:10]
                
                log.debug(f"Total suggestions: {len(merged)}")
                GLib.idle_add(self._populate_suggestions_list, merged[:10])

            import threading
            threading.Thread(target=worker, daemon=True).start()
            self._sugg_timer_id = 0
            return False

        # Debounce ~180ms
        self._sugg_timer_id = GLib.timeout_add(180, fire)

    def _populate_suggestions_list(self, items: list[str]) -> bool:
        # Clear list and repopulate
        if not items:
            self._search_suggestions_popover.popdown()
            return False
        
        # Remove old rows
        while True:
            row = self._suggestions_list.get_row_at_index(0)
            if not row:
                break
            self._suggestions_list.remove(row)
        
        # Add rows with proper sizing
        for s in items:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=s, xalign=0)
            label.set_margin_top(8)
            label.set_margin_bottom(8)
            label.set_margin_start(12)
            label.set_margin_end(12)
            label.set_wrap(False)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_max_width_chars(50)  # Prevent extremely wide suggestions
            row.set_child(label)
            row._suggestion_text = s
            
            self._suggestions_list.append(row)
        
        # Update size to match search entry width
        try:
            search_width = self.search.get_allocated_width()
            if search_width > 100:  # Valid width
                self._suggestions_scroll.set_size_request(search_width, -1)
            else:
                # Fallback to reasonable default
                self._suggestions_scroll.set_size_request(400, -1)
        except Exception:
            # If sizing fails, use default
            self._suggestions_scroll.set_size_request(400, -1)
    
        if items:
            self._search_suggestions_popover.popup()
        else:
            self._search_suggestions_popover.popdown()
        
        return False

    def _on_suggestion_selected(self, listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        """Handle suggestion selection"""
        if not hasattr(row, '_suggestion_text'):
            return
        
        suggestion = row._suggestion_text
        
        # Immediately hide the popover before doing anything else
        self._search_suggestions_popover.popdown()
        
        # Set the text and grab focus back to search
        self.search.set_text(suggestion)
        self.search.grab_focus()
        
        # Schedule the search to happen just after UI updates
        def do_search():
            add_search_term(suggestion)
            self._run_search(suggestion)
            return False  # Don't repeat
        GLib.idle_add(do_search)

        # Clean up old thumbnails on startup (runs in background)
        def _cleanup_cache():
            import threading
            def worker():
                try:
                    cleanup_old_cache()
                    enforce_cache_size_limit()
                except Exception as e:
                    log.debug(f"Cache cleanup failed: {e}")
            threading.Thread(target=worker, daemon=True).start()

        GLib.idle_add(_cleanup_cache)
        

        
        # Add Ctrl+F to focus search
        focus_search = Gio.SimpleAction.new("focus_search", None)
        focus_search.connect("activate", lambda *_: self.search.grab_focus())
        self.add_action(focus_search)
        app = self.get_application()
        if app:
            app.set_accels_for_action("win.focus_search", ["<Primary>f", "<Primary>F"])

    def _on_mpv_started(self, mode: str):
        """Called when MPV playback starts"""
        self.mpv_controls.get_ctrl_bar().set_visible(self._is_mpv_controls_visible())
        try:
            self._mpv_stop_action.set_enabled(True)
        except AttributeError:
            pass  # _mpv_stop_action may not be set in all contexts

    def _on_mpv_stopped(self):
        """Called when MPV playback stops"""
        self.mpv_controls.get_ctrl_bar().set_visible(False)
        try:
            self._mpv_stop_action.set_enabled(False)
        except AttributeError:
            pass

    def _on_search_focus_changed(self, _widget, _pspec) -> None:
        self._set_mpv_accels_enabled(not self.search.has_focus())

    def _set_mpv_accels_enabled(self, enabled: bool) -> None:
        app = self.get_application()
        if not app:
            return
        for act, keys in getattr(self, "_mpv_accels", {}).items():
            app.set_accels_for_action(act, keys if enabled else [])

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

    def _install_key_controller(self) -> None:
        ctrl = Gtk.EventControllerKey()
        def on_key(_c, keyval, keycode, state):
            k = (Gdk.keyval_name(keyval) or "").lower()

            # If search has focus, handle suggestion nav only; block MPV hotkeys
            if self.search.has_focus():
                if hasattr(self, '_search_suggestions_popover') and self._search_suggestions_popover.get_visible():
                    if k == "down":
                        first_row = self._suggestions_list.get_row_at_index(0)
                        if first_row:
                            self._suggestions_list.select_row(first_row)
                        return True
                    if k == "escape":
                        self._search_suggestions_popover.popdown()
                        return True
                    # Accept first/selected suggestion with Return/Tab
                    if k in ("return", "kp_enter", "tab"):
                        row = self._suggestions_list.get_selected_row()
                        if not row:
                            row = self._suggestions_list.get_row_at_index(0)
                        if row:
                            self._on_suggestion_selected(self._suggestions_list, row)
                            return True
                # Let the entry receive the key (don’t let MPV handle it)
                return False

            # Existing MPV controls only when entry not focused
            return self.mpv_controls.handle_key_press(keyval, keycode, state)
        
        ctrl.connect("key-pressed", on_key)
        self.add_controller(ctrl)

    def _create_actions(self) -> None:
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._on_about)
        self.add_action(about)
        log.debug("Added action: about")

        prefs = Gio.SimpleAction.new("preferences", None)
        prefs.connect("activate", self._on_preferences)
        self.add_action(prefs)
        log.debug("Added action: preferences")

        # Add the open URL action for Ctrl+L
        open_url = Gio.SimpleAction.new("open_url", None)
        open_url.connect("activate", self._on_open_url)
        self.add_action(open_url)
        log.debug("Added action: open_url")
        app = self.get_application()
        if app:
            app.set_accels_for_action("win.open_url", ["<Primary>L"])
            log.debug("Set accelerator for win.open_url: Ctrl+L")

        shortcuts = Gio.SimpleAction.new("shortcuts", None)
        shortcuts.connect("activate", self._on_shortcuts)
        self.add_action(shortcuts)
        log.debug("Added action: shortcuts")

        # Browse actions
        history_action = Gio.SimpleAction.new("history", None)
        history_action.connect("activate", self._on_history)
        self.add_action(history_action)
        log.debug("Added action: history")

        feed_action = Gio.SimpleAction.new("feed", None)
        feed_action.connect("activate", self._on_feed)
        self.add_action(feed_action)
        log.debug("Added action: feed")

        trending_action = Gio.SimpleAction.new("trending", None)
        trending_action.connect("activate", self._on_trending)
        self.add_action(trending_action)
        log.debug("Added action: trending")

        # Quick Download action
        quick_download_action = Gio.SimpleAction.new("quick_download", None)
        quick_download_action.connect("activate", self._on_quick_download)
        self.add_action(quick_download_action)

        # Watch Later actions
        watch_later_action = Gio.SimpleAction.new("watch_later", None)
        watch_later_action.connect("activate", self._on_watch_later)
        self.add_action(watch_later_action)

        clear_wl_action = Gio.SimpleAction.new("clear_watch_later", None)
        clear_wl_action.connect("activate", self._on_clear_watch_later)
        self.add_action(clear_wl_action)

        # Search history action
        clear_search_action = Gio.SimpleAction.new("clear_search_history", None)
        clear_search_action.connect("activate", self._on_clear_search_history)
        self.add_action(clear_search_action)

        # Thumbnail cache action
        clear_cache_action = Gio.SimpleAction.new("clear_thumb_cache", None)
        clear_cache_action.connect("activate", self._on_clear_thumbnail_cache)
        self.add_action(clear_cache_action)

        dlh = Gio.SimpleAction.new("download_history", None)
        dlh.connect("activate", self._on_download_history)
        self.add_action(dlh)

        cancel_all = Gio.SimpleAction.new("cancel_all_downloads", None)
        cancel_all.connect("activate", lambda *_: self.download_manager.cancel_all())
        self.add_action(cancel_all)

        clear_fin = Gio.SimpleAction.new("clear_finished_downloads", None)
        clear_fin.connect("activate", lambda *_: self.download_manager.clear_finished())
        self.add_action(clear_fin)

        health = Gio.SimpleAction.new("health_check", None)
        health.connect("activate", self._on_health_check)
        self.add_action(health)

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

    def _show_loading(self, message: str, cancellable: bool = False) -> None:
        # Clear results and show a centered spinner + message
        self._clear_results()
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_halign(Gtk.Align.CENTER)
        row.set_valign(Gtk.Align.CENTER)
        spinner = Gtk.Spinner()
        spinner.start()
        row.append(spinner)
        row.append(Gtk.Label(label=message))
        
        if cancellable:
            btn_cancel = Gtk.Button(label="Cancel")
            btn_cancel.connect("clicked", lambda *_: self._cancel_loading())
            row.append(btn_cancel)
            
        self.results_box.append(row)
        self.navigation_controller.show_view("results")

    def _cancel_loading(self):
        self._search_generation += 1  # Invalidate current search
        self._set_welcome()

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
        grp_play.append(Gtk.ShortcutsShortcut(title="Speed down", accelerator="minus"))
        grp_play.append(Gtk.ShortcutsShortcut(title="Speed up", accelerator="equal"))
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
        vids = list_downloads(limit=DEFAULT_DOWNLOAD_HISTORY)
        self._populate_results(vids)
        self.navigation_controller.show_view("results")

    def _on_health_check(self, *_a):
        dlg = Adw.MessageDialog(
            transient_for=self,
            heading="System Health Check",
            body=self._run_health_checks()
        )
        dlg.add_response("ok", "OK")
        dlg.present()

    def _run_health_checks(self) -> str:
        checks = []
        
        # MPV
        from .player import has_mpv
        checks.append(f"✓ MPV: {has_mpv()}")
        
        # Proxy
        proxy = self.settings.get("http_proxy")
        if proxy:
            # Need to import safe_httpx_proxy from util
            from .util import safe_httpx_proxy
            valid = safe_httpx_proxy(proxy, test=True)
            checks.append(f"{'✓' if valid else '✗'} Proxy: {proxy}")
        else:
            checks.append("✓ Proxy: (none configured)")
        
        # Provider
        checks.append(f"✓ Provider: {type(self.provider).__name__}")
        
        # Download dir
        checks.append(f"✓ Download dir: {self.download_dir.exists()}")
        
        return "\n".join(checks)

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

    def _on_clear_watch_later(self, *_a) -> None:
        """Clear all videos from watch later after confirmation"""
        count = get_watch_later_count()
        if count == 0:
            self._show_toast("Watch Later is already empty")
            return
        
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Clear Watch Later?",
            body=f"Remove all {count} video(s) from Watch Later?",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("clear", "Clear")
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        
        def on_response(d, response):
            if response == "clear":
                cleared = clear_watch_later()
                self._show_toast(f"Cleared {cleared} video(s) from Watch Later")
                # Refresh view if currently showing watch later
                if self.stack.get_visible_child_name() == "results":
                    current_results = len([c for c in self.results_box])
                    # Simple heuristic: if results match cleared count, we're probably showing watch later
                    if current_results > 0:
                        self._on_watch_later()
        
        dialog.connect("response", on_response)
        dialog.present()

    def _on_clear_search_history(self, *_a) -> None:
        """Clear search history after confirmation"""
        count = get_search_history_count()
        
        if count == 0:
            self._show_toast("Search history is already empty")
            return
        
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Clear Search History?",
            body=f"Remove all {count} search history entries?",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("clear", "Clear")
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        
        def on_response(d, response):
            if response == "clear":
                cleared = clear_search_history()
                self._show_toast(f"Cleared {cleared} search history entries")
        
        dialog.connect("response", on_response)
        dialog.present()

    def _on_clear_thumbnail_cache(self, *_a) -> None:
        """Clear thumbnail cache after showing stats"""
        stats = get_cache_stats()
        
        if stats['file_count'] == 0:
            self._show_toast("Thumbnail cache is already empty")
            return
        
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Clear Thumbnail Cache?",
            body=f"Remove {stats['file_count']} cached thumbnails ({stats['total_size_mb']} MB)?",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("clear", "Clear")
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        
        def on_response(d, response):
            if response == "clear":
                count = clear_thumbnail_cache()
                self._show_toast(f"Cleared {count} cached thumbnails")
        
        dialog.connect("response", on_response)
        dialog.present()

    def _on_preferences(self, *_a) -> None:
        win = PreferencesWindow(self, self.settings)
        win.present()

        def persist(_w, *_a):
            save_settings(self.settings)
            new_dir = self.settings.get("download_dir")
            if new_dir:
                self.download_dir = Path(new_dir)
                self.download_manager.set_download_dir(self.download_dir)
            # Reconfigure provider: ytextractor -> Invidious -> yt-dlp
            proxy_raw = (self.settings.get("http_proxy") or "").strip()
            proxy = safe_httpx_proxy(proxy_raw) if proxy_raw else None
            use_ytex = bool(self.settings.get("use_ytextractor"))
            use_invid = bool(self.settings.get("use_invidious"))
            invid_base = (self.settings.get("invidious_instance") or "https://yewtu.be").strip()
            try:
                if use_ytex:
                    try:
                        from .providers.ytextractor_provider import YtExtractorProvider
                        hl = (self.settings.get("yt_hl") or "en").strip() or "en"
                        gl = (self.settings.get("yt_gl") or "US").strip() or "US"
                        self.provider = YtExtractorProvider(proxy=proxy, hl=hl, gl=gl)
                    except Exception:
                        log.warning("YtExtractor provider disabled or not available, falling back to yt-dlp")
                        self.provider = YTDLPProvider(proxy)
                elif use_invid:
                    self.provider = InvidiousProvider(invid_base, proxy=proxy, fallback=YTDLPProvider(proxy))
                else:
                    self.provider = YTDLPProvider(proxy)
                # Reapply cookies to provider on reconfigure
                spec = self.playback_service.get_cookie_spec()
                if spec:
                    if isinstance(self.provider, YTDLPProvider):
                        self.provider.set_cookies_from_browser(spec)
                    elif isinstance(self.provider, InvidiousProvider):
                        # Set cookies on the fallback YTDLPProvider for InvidiousProvider
                        self.provider._fallback.set_cookies_from_browser(spec)
                    elif isinstance(self.provider, YtExtractorProvider):
                        # Set cookies on the fallback YTDLPProvider for YtExtractorProvider
                        self.provider._fallback.set_cookies_from_browser(spec)
            except Exception:
                # fallback to yt-dlp
                self.provider = YTDLPProvider(proxy)
            # Update concurrency at runtime
            self.download_manager.set_max_concurrent(int(self.settings.get("max_concurrent_downloads") or 3))
            # Update MPV controls visibility preference immediately
            self.mpv_controls.get_ctrl_bar().set_visible(self._is_mpv_controls_visible())

        win.connect("close-request", persist)

    def _on_main_close(self, *_a) -> bool:
        # Persist current window size
        try:
            self.settings["win_w"], self.settings["win_h"] = int(self.get_width()), int(self.get_height())
        except Exception:
            pass
        # Stop MPV if running
        try:
            self.playback_service.stop()
        except Exception:
            pass
        # Shut down thumbnail loader pool
        try:
            self._thumb_loader_pool.shutdown(wait=True, cancel_futures=True)
        except TypeError:
            # Python < 3.9 doesn't have cancel_futures
            self._thumb_loader_pool.shutdown(wait=False)
        except Exception:
            pass

        # Persist queue (best effort)
        try:
            self.download_manager.persist_queue()
        except Exception:
            pass
            
        # Close global HTTP client to prevent resource leak
        try:
            from .ui.widgets.result_row import _http_client
            if _http_client and not _http_client.is_closed:
                _http_client.close()
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
            # Call cleanup if it's a ResultRow to cancel thumbnail loading
            if hasattr(child, 'cancel_thumbnail_loading'):
                child.cancel_thumbnail_loading()
            self.results_box.remove(child)
            child = nxt

    # ---------- Header actions ----------

    def _on_open_url(self, *_a) -> None:
        from .ui.controllers.browse import open_url_dialog
        open_url_dialog(
            self, self.provider, self.navigation_controller,
            self._extract_ytid_from_url, self._show_error, self._populate_results, self._play_video, self._show_loading
        )

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
        vids = list_watch(limit=DEFAULT_WATCH_HISTORY)
        self._populate_results(vids)
        self.navigation_controller.show_view("results")

    def _on_quick_download(self, *_a) -> None:
        QuickDownloadWindow(self).present()

    def _on_watch_later(self, *_a) -> None:
        """Show watch later queue, filtering out watched videos"""
        
        vids = list_watch_later()
        
        if not vids:
            self._clear_results()
            self.results_box.append(Gtk.Label(label="No videos in Watch Later.\n\nClick 'Watch Later' on any video to add it here."))
            self.navigation_controller.show_view("results")
            return
        
        # Filter out watched videos
        unwatched = [v for v in vids if not is_watched(v.id)]
        
        if not unwatched:
            self._clear_results()
            self.results_box.append(Gtk.Label(label="All videos in Watch Later have been watched!\n\nGreat job!"))
            self.navigation_controller.show_view("results")
            return
        
        self._populate_results(unwatched)
        self.navigation_controller.show_view("results")

    def _on_feed(self, *_a) -> None:
        """Show subscription feed - use fast authenticated feed if available"""
        # Check if we have an authenticated Invidious token
        # Try secure storage first
        try:
            from .invidious_auth import InvidiousAuth
            auth_helper = InvidiousAuth("")
            token = auth_helper._get_secure_token()
            
            if not token:
                # Fall back to plain text settings
                token = self.settings.get("invidious_token", "")
        except Exception:
            # Fall back to plain text settings
            token = self.settings.get("invidious_token", "")
        
        instance_url = self.settings.get("invidious_instance", "https://yewtu.be").strip()
        
        if token and instance_url:
            # Try to use fast authenticated feed
            try:
                from .invidious_auth import InvidiousAuth
                
                # Create auth instance and set token
                auth = InvidiousAuth(instance_url)
                auth.token = token
                
                # Use fast authenticated feed
                self._show_loading("Loading feed (authenticated)...", cancellable=True)
                
                def worker():
                    try:
                        # Get feed from authenticated endpoint
                        feed_data = auth.get_feed(max_results=60)
                        
                        # Convert dicts to Video objects
                        from .providers.ytdlp import _entry_to_video
                        vids = [_entry_to_video(item) for item in feed_data if isinstance(item, dict)]
                        
                        GLib.idle_add(self._populate_results, vids)
                    except Exception as e:
                        import logging
                        logging.exception("Authenticated feed failed: %s", e)
                        # Fall back to slow method
                        GLib.idle_add(self._on_feed_slow_fallback)
                
                threading.Thread(target=worker, daemon=True).start()
                return
            except Exception as e:
                import logging
                logging.exception("Failed to initialize authenticated feed: %s", e)
                # Fall back to slow method
                self._on_feed_slow_fallback()
        else:
            # Use slow fallback method
            self._on_feed_slow_fallback()
    
    def _on_feed_slow_fallback(self, *_a) -> None:
        """Slow fallback method: fetch recent uploads from each followed channel"""
        self._show_loading("Loading feed (slow)...", cancellable=True)

        def worker():
            vids_all = []
            try:
                from .subscriptions import list_subscriptions
                subs = list_subscriptions()
                for sub in subs:
                    try:
                        vids = self.provider.channel_tab(sub.url, "videos")
                        if vids:
                            vids_all.extend(vids[:FEED_VIDEOS_PER_CHANNEL])
                    except Exception:
                        continue
            except Exception:
                vids_all = []
            GLib.idle_add(self._populate_results, vids_all)
        threading.Thread(target=worker, daemon=True).start()

    def _on_trending(self, *_a) -> None:
        import logging
        log = logging.getLogger("trending.debug")
        log.debug("_on_trending called")
        self._show_loading("Loading trending…", cancellable=True)
        def worker():
            try:
                vids = self.provider.trending()
            except Exception:
                import logging
                logging.getLogger("trending.debug").exception("Error in trending worker")
                vids = []
            def show():
                self._populate_results(vids)
                if not vids:
                    self._show_toast("Trending is unavailable on your network/region right now.")
                return False
            GLib.idle_add(show)
        threading.Thread(target=worker, daemon=True).start()

    # ---------- Search ----------

    # ---------- Search ----------

    def _on_search_activate(self, entry: Gtk.SearchEntry) -> None:
        import logging
        log = logging.getLogger("search.debug")
        log.debug("Search activate called")
        search.on_search_activate(entry, self._run_search)

    def _run_search(self, query: str) -> None:
        # Increment search generation atomically with lock to prevent race conditions
        with self._search_lock:
            self._search_generation += 1
            current_gen = self._search_generation
        search.run_search(
            query=query,
            provider=self.provider,
            settings=self.settings,
            search_generation=current_gen,
            show_loading_func=self._show_loading,
            show_error_func=self._show_error,
            populate_results_func=self._populate_results,
            set_search_generation_func=self._set_search_generation,
            limit=DEFAULT_SEARCH_LIMIT,
            last_filters=self._last_filters,
            timed_func=timed,
            search_lock=self._search_lock,  # Pass the lock for thread safety
        )

    def _set_search_generation(self, gen: int) -> int:
        """Helper to update and return the new search generation counter."""
        self._search_generation = gen
        # Also store in settings for the controller to check
        self.settings["_search_generation"] = gen
        return gen

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
                on_open=lambda video: self._open_item(video),
                on_related=lambda video: self._on_related(video),
                on_comments=lambda video: self._on_comments(video),
                thumb_loader_pool=self._thumb_loader_pool,
                http_proxy=(self.settings.get("http_proxy") or None),
                on_follow=self._follow_channel,
                on_unfollow=self._unfollow_channel,
                followed=is_followed(v.url) if v.kind == "channel" else False,
                on_open_channel=lambda video: self._open_channel_from_video(video),
                on_toast=self._show_toast,
                get_setting=self.settings.get,  # NEW - pass settings getter
                on_quick_download=self._quick_download_video,  # NEW - pass handler
            )
            self.results_box.append(row)

    def _quick_download_video(self, video: Video, opts: DownloadOptions) -> None:
        """Handle quick quality download"""
        self.download_manager.start_download(video, opts)

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
        from .ui.controllers.browse import open_item
        open_item(
            video, self.provider, self.navigation_controller, self._show_error, 
            self._populate_results, self._play_video, 
            lambda url: self._open_playlist(url), 
            lambda url: self._open_channel(url), self._show_loading
        )

    def _open_playlist(self, url: str) -> None:
        from .ui.controllers.browse import open_playlist
        open_playlist(url, self.provider, self.navigation_controller, self._show_error, self._populate_results, self._show_loading)

    def _open_channel(self, url: str) -> None:
        from .ui.controllers.browse import open_channel
        open_channel(url, self.provider, self.navigation_controller, self._show_error, self._populate_results, self._show_loading)

    def _on_related(self, video: Video) -> None:
        from .ui.controllers.browse import on_related
        on_related(video, self.provider, self.navigation_controller, self._show_error, self._populate_results, self._show_loading)

    def _on_comments(self, video: Video) -> None:
        from .ui.controllers.browse import on_comments
        on_comments(video, self.provider, self.navigation_controller, self._show_error, self._populate_results, self._show_loading)

    def _open_channel_from_video(self, video: Video) -> None:
        from .ui.controllers.browse import open_channel_from_video
        open_channel_from_video(
            video, self.provider, self.navigation_controller, self._show_error, 
            self._populate_results, lambda url: self._open_channel(url), self._show_loading
        )

    def _play_video(self, video: Video) -> None:
        # Log that the function was called to help with debugging
        log.debug("_play_video called: url=%s", video.url)
        # Save to watch history
        add_watch(video)

        # Play using the playback service
        success = self.playback_service.play(video=video)
        
        mode = self.settings.get("playback_mode", "external")
        if success and mode == "embedded":
            # If embedded playback was successful, show the player view
            self.navigation_controller.show_view("player")
        
        if success:
            self._show_toast(f"Playing: {video.title}")

    def _is_mpv_controls_visible(self) -> bool:
        if not hasattr(self, 'playback_service'):
            return False
        # Only show controls if MPV running
        if not self.playback_service.is_running():
            return False
        # honor autohide preference: show only on player view when enabled
        if bool(self.settings.get("mpv_autohide_controls")):
            return (self.stack.get_visible_child_name() == "player")
        return True

    def _on_stack_changed(self, *_a) -> None:
        try:
            self.mpv_controls.get_ctrl_bar().set_visible(self._is_mpv_controls_visible())
        except Exception:
            pass

    def _cookies_spec_for_ytdlp(self) -> str | None:
        if not self.settings.get("mpv_cookies_enable"):
            return None
        browser = (self.settings.get("mpv_cookies_browser") or "").strip()
        if not browser:
            return None
        keyring = (self.settings.get("mpv_cookies_keyring") or "").strip()
        profile = (self.settings.get("mpv_cookies_profile") or "").strip()
        container = (self.settings.get("mpv_cookies_container") or "").strip()
        
        # Construct: browser[+keyring][:profile][::container]
        val = browser
        if keyring:
            val += f"+{keyring}"
        
        # Handle profile and container correctly
        if profile and container:
            # Both present: browser:profile::container
            val += f":{profile}::{container}"
        elif profile:
            # Only profile: browser:profile
            val += f":{profile}"
        elif container:
            # Only container: browser::container
            val += f"::{container}"
        # If neither, val stays as browser or browser+keyring
        
        return val

    # ---------- Downloads ----------

    def _download_options(self, video: Video) -> None:
        log.debug("_download_options called for: %s", video.title)
        dlg = DownloadOptionsWindow(self, video.title)
        self._current_download_dlg = dlg # Keep a strong reference

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
            # Clear the strong reference when the dialog is closed
            self._current_download_dlg = None

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

    def _filters_load_from_settings(self) -> None:
        search.filters_load_from_settings(
            settings=self.settings,
            dd_dur=self.dd_dur,
            dd_period=self.dd_period,
            dd_order=self.dd_order,
        )

    def _filters_apply(self, *_a) -> None:
        def set_last_filters(filters: dict[str, str]) -> None:
            self._last_filters = filters
        
        search.filters_apply(
            settings=self.settings,
            dd_dur=self.dd_dur,
            dd_period=self.dd_period,
            dd_order=self.dd_order,
            filters_pop=self._filters_pop,
            search_entry=self.search,
            run_search_func=self._run_search,
            set_last_filters_func=set_last_filters,
        )

    def _filters_clear(self, *_a) -> None:
        search.filters_clear(
            settings=self.settings,
            load_filters_func=self._filters_load_from_settings,
            search_entry=self.search,
            run_search_func=self._run_search,
        )


def _spacer(px: int) -> Gtk.Box:
    b = Gtk.Box()
    b.set_size_request(-1, px)
    return Gtk.Box()
    b = Gtk.Box()
    b.set_size_request(-1, px)
    return bm_settings(
        search_entry=self.search,
        run_search_func=self._run_search,
    )


def _spacer(px: int) -> Gtk.Box:
    b = Gtk.Box()
    b.set_size_request(-1, px)
    return Gtk.Box()
    b = Gtk.Box()
    b.set_size_request(-1, px)
    return b