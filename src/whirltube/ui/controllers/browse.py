from __future__ import annotations

import threading
from gi.repository import Gtk, GLib

from ...models import Video
from ...providers.base import Provider
from ...navigation_controller import NavigationController
from ...util import is_valid_youtube_url

import logging
log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}





def open_url_dialog(main_window, provider: Provider, navigation_controller: NavigationController, 
                   extract_ytid_from_url, show_error, populate_results, _play_video, show_loading_cb) -> None:
    """Show dialog for opening a URL"""
    dlg = Gtk.Dialog(title="Open URL", transient_for=main_window, modal=True)
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
                    if bool(main_window.settings.get("use_invidious")):
                        host = (main_window.settings.get("invidious_instance") or "").strip()
                        if host:
                            from urllib.parse import urlparse
                            host_parsed = urlparse(host).hostname
                            if host_parsed:
                                extra.append(host_parsed)
                                # common subdomain case
                                if not host_parsed.startswith("www."):
                                    extra.append("www." + host_parsed)
                    if not is_valid_youtube_url(url, extra):
                        show_error("This doesn't look like a YouTube/Invidious URL.")
                    else:
                        # If this looks like a direct video URL, play immediately
                        vid = extract_ytid_from_url(url)
                        if vid:
                            v = Video(id=vid, title=url, url=url, channel=None, duration=None, thumb_url=None, kind="video")
                            _play_video(v)
                        else:
                            # Otherwise open as a listing (playlist/channel/etc.)
                            browse_url(url, provider, navigation_controller, show_error, populate_results, show_loading_cb)
        finally:
            d.destroy()

    dlg.connect("response", on_response)


def browse_url(url: str, provider: Provider, navigation_controller: NavigationController, 
              show_error, populate_results, show_loading_cb) -> None:
    """Browse a URL (playlist, channel, etc.)"""


    def worker():
        show_loading_cb("Opening URL...")
        vids = provider.browse_url(url)
        GLib.idle_add(populate_results, vids)

    threading.Thread(target=worker, daemon=True).start()


def open_playlist(url: str, provider: Provider, navigation_controller: NavigationController, 
                 show_error, populate_results, show_loading_cb) -> None:
    """Open a playlist URL"""


    def worker():
        show_loading_cb("Opening playlist...")
        vids = provider.playlist(url)
        GLib.idle_add(populate_results, vids)

    threading.Thread(target=worker, daemon=True).start()


def open_channel(url: str, provider: Provider, navigation_controller: NavigationController, 
                show_error, populate_results, show_loading_cb) -> None:
    """Open a channel URL"""


    def worker():
        show_loading_cb("Opening channel...")
        try:
            vids = provider.channel_tab(url, "videos")
            GLib.idle_add(populate_results, vids)
        except Exception as e:
            log.error("Failed to open channel %s: %s", url, e)
            GLib.idle_add(show_error, "Could not open channel or fetch videos.")

    threading.Thread(target=worker, daemon=True).start()


def on_related(video: Video, provider: Provider, navigation_controller: NavigationController, 
              show_error, populate_results, show_loading_cb) -> None:
    """Show related videos to a given video"""


    def worker():
        show_loading_cb("Fetching related videos...")
        try:
            vids = provider.related(video.url)
            GLib.idle_add(populate_results, vids)
            if not vids:
                GLib.idle_add(show_error, "No related videos found.")
        except Exception as e:
            log.error("Failed to get related videos for %s: %s", video.url, e)
            GLib.idle_add(show_error, "Failed to fetch related videos.")

    threading.Thread(target=worker, daemon=True).start()


def on_comments(video: Video, provider: Provider, navigation_controller: NavigationController, 
               show_error, populate_results, show_loading_cb) -> None:
    """Show comments for a given video"""
    show_loading_cb(f"Comments for: {video.title}")

    # Use Event for proper thread coordination
    completed = threading.Event()
    
    def watchdog():
        # Wait for 20 seconds or until completed
        if not completed.wait(timeout=20.0):
            # Timeout occurred, worker hasn't completed
            GLib.idle_add(show_error, "Comments timed out (YouTube may be rate-limiting)")
    
    def worker():
        try:
            vids = provider.comments(video.url, max_comments=100)
        except Exception as e:
            if not completed.is_set():
                completed.set()
                GLib.idle_add(show_error, f"Comments failed: {e}")
            return
        
        if not completed.is_set():
            completed.set()
            GLib.idle_add(populate_results, vids)
    
    threading.Thread(target=watchdog, daemon=True).start()
    threading.Thread(target=worker, daemon=True).start()


def open_channel_from_video(video: Video, provider: Provider, navigation_controller: NavigationController, 
                           show_error, populate_results, open_channel_func, show_loading_cb) -> None:
    """Resolve channel URL from a video, then open channel view"""

    
    def worker():
        show_loading_cb("Resolving channel...")
        try:
            url = provider.channel_url_of(video.url)
        except Exception:
            url = None
        if not url:
            GLib.idle_add(show_error, "Unable to resolve channel for this video.")
            return
        # Reuse existing channel opener
        def go():
            open_channel_func(url)
            return False
        GLib.idle_add(go)
    
    threading.Thread(target=worker, daemon=True).start()


def open_item(video: Video, provider: Provider, navigation_controller: NavigationController, 
             show_error, populate_results, _play_video, open_playlist_func, open_channel_func, show_loading_cb) -> None:
    """Generic open item function that handles different video kinds"""
    # For playlists/channels/comments: open URL to list inner entries or view.
    if video.kind == "playlist":
        open_playlist_func(video.url)
    elif video.kind == "channel":
        open_channel_func(video.url)
    elif video.kind == "comment":
        browse_url(video.url, provider, navigation_controller, show_error, populate_results, show_loading_cb)
    else:
        _play_video(video)