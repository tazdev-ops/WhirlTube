from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import httpx

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

from ...models import Video
from ...dialogs import DownloadOptions
from ...thumbnail_cache import get_cached_thumbnail, cache_thumbnail
from ...util import safe_httpx_proxy, is_valid_youtube_url
from ...subscription_feed import is_watched, mark_as_watched, mark_as_unwatched
from ...watch_later import is_in_watch_later, add_to_watch_later, remove_from_watch_later
from ...quick_quality import get_enabled_presets, get_preset_label, get_preset_tooltip, get_quick_quality_options
from ...metrics import timed

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}

log = logging.getLogger(__name__)

# Shared HTTP client for thumbnail loading to reuse connections
_http_client: httpx.Client | None = None

def _get_http_client(proxy: str | None) -> httpx.Client:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.Client(
            timeout=10.0,
            follow_redirects=True,
            headers=HEADERS,
            proxy=safe_httpx_proxy(proxy),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=5)
        )
    return _http_client


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
        get_setting: Callable[[str], any] | None = None,  # NEW parameter
        on_quick_download: Callable[[Video, DownloadOptions], None] | None = None,  # NEW parameter
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
        self._get_setting = get_setting or (lambda k: None)  # NEW
        self._on_quick_download = on_quick_download  # NEW
        self._proxies = safe_httpx_proxy(http_proxy)
        self._thumb_future = None  # Track thumbnail loading future to prevent memory leaks

        self.set_margin_top(6)
        self.set_margin_bottom(6)

        # Thumbnail stack with placeholder and image
        self._has_thumb = self.video.kind != "comment"
        if self._has_thumb:
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
        else:
            # Add a small spacer for alignment if no thumbnail
            spacer = Gtk.Box()
            spacer.set_size_request(16, 1) # Small spacer
            self.append(spacer)

        # Texts
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)

        # Title with watched indicator
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label=video.title, wrap=True, xalign=0.0, hexpand=True)
        title.add_css_class("title-3")
        title_box.append(title)

        # NEW: Watched indicator
        if video.is_playable and is_watched(video.id):
            watched_label = Gtk.Label(label="✓ Watched")
            watched_label.add_css_class("dim-label")
            watched_label.set_tooltip_text("You've watched this video")
            title_box.append(watched_label)

        box.append(title_box)

        meta = Gtk.Label(label=_fmt_meta(video), xalign=0.0)
        meta.add_css_class("dim-label")
        box.append(meta)
        self.append(box)

        # Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        if video.is_playable:
            # Primary action: Play
            play_btn = Gtk.Button(label="▶️ Play")
            play_btn.connect("clicked", self._on_play_clicked)
            btn_box.append(play_btn)
            
            # Personal management: Watch Later
            self._in_watch_later = is_in_watch_later(video.id)
            self.wl_btn = Gtk.Button()
            self._update_wl_button_label()
            self.wl_btn.connect("clicked", self._on_watch_later_clicked)
            btn_box.append(self.wl_btn)
            
            # Content availability: Download actions (high priority for users who want to save)
            # Download section: Quick downloads first, then advanced options
            quick_dl_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
            quick_dl_box.set_homogeneous(True)
            
            # Get enabled presets from settings
            enabled_presets = get_enabled_presets(
                self._get_setting("quick_quality_presets") if self._get_setting else None
            )
            
            for preset_key in enabled_presets:
                preset_btn = Gtk.Button(label=get_preset_label(preset_key))
                preset_btn.set_tooltip_text(get_preset_tooltip(preset_key))
                preset_btn.add_css_class("flat")
                preset_btn.connect("clicked", self._on_quick_download_handler, preset_key)
                quick_dl_box.append(preset_btn)
            
            btn_box.append(quick_dl_box)
            
            # Advanced download options - make it clearer this is for the single video
            dl_opts_btn = Gtk.Button(label="⬇️ More…")
            dl_opts_btn.set_tooltip_text("More download options for this video")
            dl_opts_btn.connect("clicked", self._on_download_clicked)
            btn_box.append(dl_opts_btn)
            
            # Content discovery: Related videos (medium priority)
            related_btn = Gtk.Button(label="🔍 Related")
            related_btn.set_tooltip_text("Show related videos")
            related_btn.connect("clicked", lambda *_: self.on_related(self.video))
            btn_box.append(related_btn)
            
            # Content interaction: Comments (lower priority)
            comments_btn = Gtk.Button(label="💬 Comments")
            comments_btn.set_tooltip_text("Show comments")
            comments_btn.connect("clicked", lambda *_: self.on_comments(self.video))
            btn_box.append(comments_btn)
            
            # Compact "More…" menu with remaining actions
            more = Gtk.MenuButton(label="⋮ Actions")
            more.set_tooltip_text("Other actions")
            pop = Gtk.Popover()
            vbx = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
            
            # Content management
            watched = is_watched(self.video.id)
            b_watch = Gtk.Button(label="👁️ Mark as Unwatched" if watched else "👁️ Mark as Watched")
            b_watch.connect("clicked", self._on_toggle_watched)
            vbx.append(b_watch)
            
            # Channel interaction
            b_ch = Gtk.Button(label="📺 Open channel")
            b_ch.set_tooltip_text("Open the uploader's channel")
            b_ch.connect("clicked", lambda *_: self.on_open_channel(self.video))
            
            # Sharing actions
            b_web = Gtk.Button(label="🌐 Open in Browser")
            b_web.connect("clicked", lambda *_: self._open_in_browser())
            b_cu = Gtk.Button(label="🔗 Copy URL")
            b_cu.connect("clicked", lambda *_: self._copy_url())
            b_ct = Gtk.Button(label="📋 Copy Title")
            b_ct.connect("clicked", lambda *_: self._copy_title())
            
            # Group remaining actions
            for b in (b_ch, b_web, b_cu, b_ct):
                vbx.append(b)
            
            pop.set_child(vbx)
            more.set_popover(pop)
            btn_box.append(more)
        else:
            # Non-playable kinds
            if self.video.kind == "playlist":
                open_btn = Gtk.Button(label="▶️ Open")
                open_btn.set_tooltip_text("Open this playlist")
                open_btn.connect("clicked", lambda *_: self.on_open(self.video))
                btn_box.append(open_btn)
                # Playlist may be downloaded (folder structure) - using a clearer icon
                dl_btn = Gtk.Button(label="📦 Download")
                dl_btn.set_tooltip_text("Download this entire playlist")
                dl_btn.connect("clicked", lambda *_: self.on_download_opts(self.video))
                btn_box.append(dl_btn)
            elif self.video.kind == "channel":
                open_btn = Gtk.Button(label="▶️ Open")
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
            more = Gtk.MenuButton(label="⋮ Actions")
            more.set_tooltip_text("Other actions")
            pop = Gtk.Popover()
            vbx = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
            b_web = Gtk.Button(label="🌐 Open in Browser")
            b_web.connect("clicked", lambda *_: self._open_in_browser())
            b_cu = Gtk.Button(label="🔗 Copy URL")
            b_cu.connect("clicked", lambda *_: self._copy_url())
            b_ct = Gtk.Button(label="📋 Copy Title")
            b_ct.connect("clicked", lambda *_: self._copy_title())
            for b in (b_web, b_cu, b_ct):
                vbx.append(b)
            pop.set_child(vbx)
            more.set_popover(pop)
            btn_box.append(more)
        self.append(btn_box)

        # Load thumbnail
        if self._has_thumb:
            if video.thumb_url:
                self._thumb_future = self.thumb_loader_pool.submit(self._load_thumb)
            else:
                # No URL -> placeholder
                GLib.idle_add(self._set_thumb_placeholder)

    def _on_play_clicked(self, *_a):
        import logging
        log = logging.getLogger("whirltube.ui.widgets.result_row")
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
        log = logging.getLogger("whirltube.ui.widgets.result_row")
        log.debug("ResultRow Download clicked: %s", self.video.title)
        if callable(self.on_download_opts):
            self.on_download_opts(self.video)

    def _load_thumb(self) -> None:
        with timed(f"Thumbnail load: {self.video.title[:30]}"):
            # Check cancellation early
            if not hasattr(self, '_thumb_future') or self._thumb_future is None:
                return
            
            # Also check if already done (cancelled or completed)
            try:
                if self._thumb_future.done():
                    return
            except Exception:
                return
            
            # Check cache first
            cached_path = get_cached_thumbnail(self.video.thumb_url)
            if cached_path:
                try:
                    data = cached_path.read_bytes()
                    # Check cancellation before updating UI
                    if not hasattr(self, '_thumb_future') or self._thumb_future is None:
                        return
                    try:
                        if self._thumb_future.done():
                            return
                    except Exception:
                        return
                    
                    GLib.idle_add(self._set_thumb, data)
                    return
                except Exception as e:
                    log.debug(f"Failed to read cached thumbnail: {e}")
                    # Fall through to download
            
            # Try download with shared client
            data: bytes | None = None
            try:
                # For httpx 0.28.1+, use proxy parameter directly
                client = _get_http_client(self._http_proxy)
                r = client.get(self.video.thumb_url)
                r.raise_for_status()
                data = r.content
            except Exception:
                data = None
                # Fallback: retry without proxy if we had one
                try:
                    # Create temporary client without proxy
                    temp_client = httpx.Client(timeout=10.0, follow_redirects=True, headers=HEADERS)
                    r2 = temp_client.get(self.video.thumb_url)
                    r2.raise_for_status()
                    data = r2.content
                    temp_client.close()
                except Exception:
                    data = None
            
            if data is None:
                # Check cancellation before updating UI
                if not hasattr(self, '_thumb_future') or self._thumb_future is None:
                    return
                try:
                    if self._thumb_future.done():
                        return
                except Exception:
                    return
                GLib.idle_add(self._set_thumb_placeholder)
                return
            
            # Check cancellation before caching
            if not hasattr(self, '_thumb_future') or self._thumb_future is None:
                return
            try:
                if self._thumb_future.done():
                    return
            except Exception:
                return
            
            # Cache the downloaded thumbnail
            try:
                cache_thumbnail(self.video.thumb_url, data)
            except Exception as e:
                log.debug(f"Failed to cache thumbnail: {e}")
            
            # Check cancellation before updating UI
            if not hasattr(self, '_thumb_future') or self._thumb_future is None:
                return
            try:
                if self._thumb_future.done():
                    return
            except Exception:
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
                # Validate URL scheme
                if not is_valid_youtube_url(self.video.url):
                    if self.on_toast:
                        self.on_toast("Cannot open: invalid URL")
                    return
                Gio.AppInfo.launch_default_for_uri(self.video.url, None)
        except Exception as e:
            if self.on_toast:
                self.on_toast(f"Failed to open browser: {e}")

    def _copy_url(self) -> None:
        text = self.video.url or ""
        if not text:
            return
        self._do_copy_text(text, "URL copied to clipboard")

    def _copy_title(self) -> None:
        text = self.video.title or ""
        if not text:
            return
        self._do_copy_text(text, "Title copied to clipboard")

    def _do_copy_text(self, text: str, toast_msg: str) -> None:
        """
        Copy text to clipboard with Wayland-safe async handling.
        Keeps a reference to the ContentProvider to avoid GC before paste.
        """
        def copy_on_main():
            try:
                disp = Gdk.Display.get_default()
                if not disp:
                    return False
                clipboard = disp.get_clipboard()
                
                # Create a ContentProvider for text
                # Store it as an instance variable so it doesn't get GC'd (Wayland needs this)
                self._clipboard_provider = Gdk.ContentProvider.new_for_value(text)
                clipboard.set_content(self._clipboard_provider)
                
                if self.on_toast:
                    self.on_toast(toast_msg)
            except Exception:
                # Fallback: try the primary clipboard (X11 middle-click selection)
                try:
                    if disp:
                        primary = disp.get_primary_clipboard()
                        if primary:
                            self._clipboard_provider_primary = Gdk.ContentProvider.new_for_value(text)
                            primary.set_content(self._clipboard_provider_primary)
                except Exception:
                    pass
            return False
        
        GLib.idle_add(copy_on_main)

    def cancel_thumbnail_loading(self) -> None:
        """
        Cancel pending thumbnail loading if still in progress.
        This helps prevent memory leaks when rows are scrolled away.
        """
        if self._thumb_future and not self._thumb_future.done():
            self._thumb_future.cancel()
            self._thumb_future = None

    def _update_wl_button_label(self) -> None:
        """Update Watch Later button label based on current state"""
        if self._in_watch_later:
            self.wl_btn.set_label("✓ Saved")
            self.wl_btn.set_tooltip_text("Remove from Watch Later")
        else:
            self.wl_btn.set_label("Watch Later")
            self.wl_btn.set_tooltip_text("Save for later")

    def _on_watch_later_clicked(self, *_a) -> None:
        """Toggle Watch Later status"""
        if self._in_watch_later:
            # Remove from watch later
            if remove_from_watch_later(self.video.id):
                self._in_watch_later = False
                self._update_wl_button_label()
                if self.on_toast:
                    self.on_toast("Removed from Watch Later")
            else:
                if self.on_toast:
                    self.on_toast("Failed to remove from Watch Later")
        else:
            # Add to watch later
            if add_to_watch_later(self.video):
                self._in_watch_later = True
                self._update_wl_button_label()
                if self.on_toast:
                    self.on_toast("Added to Watch Later")
            else:
                if self.on_toast:
                    self.on_toast("Already in Watch Later")

    def _on_quick_download_handler(self, btn: Gtk.Button, preset_key: str) -> None:
        """Handle quick quality download button click"""
        try:
            opts = get_quick_quality_options(preset_key)
            
            # Call the MainWindow callback if it exists
            if self._on_quick_download and callable(self._on_quick_download):
                # Ensure we're passing the right parameters: Video object and DownloadOptions
                self._on_quick_download(self.video, opts)
            else:
                # Fallback to regular download dialog
                self.on_download_opts(self.video)
            
            if self.on_toast:
                quality = get_preset_label(preset_key)
                self.on_toast(f"Downloading {self.video.title} ({quality})")
        except Exception as e:
            log.exception(f"Quick download failed: {e}")
            if self.on_toast:
                self.on_toast(f"Download failed: {e}")

    def _on_toggle_watched(self, btn: Gtk.Button) -> None:
        """Toggle watched status and remove from watch later if watched"""
        if is_watched(self.video.id):
            mark_as_unwatched(self.video.id)
            btn.set_label("Mark as Watched")
            if self.on_toast:
                self.on_toast("Marked as unwatched")
        else:
            mark_as_watched(self.video.id)
            btn.set_label("Mark as Unwatched")
            
            # NEW: Auto-remove from watch later when marked watched
            if is_in_watch_later(self.video.id):
                from ...watch_later import remove_from_watch_later
                remove_from_watch_later(self.video.id)
                if self.on_toast:
                    self.on_toast("Marked as watched and removed from Watch Later")
            else:
                if self.on_toast:
                    self.on_toast("Marked as watched")

        # This would open a dialog to mark segment boundaries
        # and submit them to the SponsorBlock database

def _fmt_meta(v: Video) -> str:
    """Format metadata line with duration, views, date, channel"""
    parts = []
    
    # Channel name
    if v.channel:
        parts.append(v.channel)
    
    # View count (if available)
    if v.view_count_str:
        parts.append(v.view_count_str)
    
    # Upload date (if available)
    if v.upload_date_str:
        parts.append(v.upload_date_str)
    
    # Duration (for videos)
    if v.duration_str and v.kind == "video":
        parts.append(v.duration_str)
    
    # Kind indicator for non-videos
    if v.kind in ("playlist", "channel"):
        parts.append(f"[{v.kind.title()}]")
    
    return " • ".join(parts) if parts else "Unknown"