from __future__ import annotations

import logging

from ..models import Video, Format
from .base import Provider
from .innertube_web import InnerTubeWeb
from .ytdlp import YTDLPProvider

log = logging.getLogger(__name__)

class HybridProvider(Provider):
    """
    A provider that intelligently delegates calls to a fast provider (InnerTubeWeb)
    for lightweight tasks (suggestions, trending) and a robust provider (YTDLPProvider)
    for heavy tasks (search, formats, comments).
    """
    def __init__(self, fast_provider: InnerTubeWeb, robust_provider: YTDLPProvider) -> None:
        self._fast = fast_provider
        self._robust = robust_provider

    # --- Fast Path (InnerTubeWeb) ---

    def suggestions(self, query: str, max_items: int = 10) -> list[str]:
        return self._fast.suggestions(query, max_items)

    def trending(self) -> list[Video]:
        # InnerTubeWeb delegates to its fallback (which is YTDLPProvider)
        # so calling _fast.trending() is sufficient.
        return self._fast.trending()

    # --- Robust Path (YTDLPProvider) ---

    def search(self, query: str, limit: int, order: str | None = None, duration: str | None = None, period: str | None = None) -> list[Video]:
        # Forward separate filter params to YTDLPProvider
        return self._robust.search(query, limit, order=order, duration=duration, period=period)

    def related(self, video_id: str) -> list[Video]:
        return self._robust.related(video_id)

    def comments(self, video_id: str) -> list[Video]:
        return self._robust.comments(video_id)

    def channel_tab(self, channel_url: str, tab: str) -> list[Video]:
        return self._robust.channel_tab(channel_url, tab)

    def fetch_formats(self, url: str) -> list[Format]:
        return self._robust.fetch_formats(url)

    def get_video_info(self, url: str) -> Video | None:
        # This is a robust operation, delegate to ytdlp
        return self._robust.get_video_info(url)

    def set_cookies_from_browser(self, spec: str) -> None:
        # Cookies are primarily for yt-dlp to access region-locked content
        self._robust.set_cookies_from_browser(spec)

    def get_proxy(self) -> str | None:
        return self._robust.get_proxy()
