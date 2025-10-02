from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import httpx
from typing import Any

from ...models import Video
from ...metrics import timed
from ...util import safe_httpx_proxy, is_valid_youtube_url
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}

import gi
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

log = logging.getLogger(__name__)


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
            except Exception as e:
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


def _fmt_meta(v: Video) -> str:
    ch = v.channel or "Unknown channel"
    dur = v.duration_str
    base = f"{ch} • {dur}" if dur else ch
    if v.kind in ("playlist", "channel"):
        return f"{base} • {v.kind}"
    return base