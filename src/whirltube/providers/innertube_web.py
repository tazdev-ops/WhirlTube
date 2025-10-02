from __future__ import annotations

import logging
import httpx
import json

from ..models import Video, Format
from ..util import safe_httpx_proxy
from .base import Provider

log = logging.getLogger(__name__)

# Base URL for InnerTube API (used by web clients)
# This is a placeholder and would require a full InnerTube implementation
# For now, we will use a simple search suggestion endpoint.
_SUGGEST_URL = "https://suggestqueries-clients6.youtube.com/complete/search"
_TRENDING_URL = "https://www.youtube.com/feed/trending" # Fallback to scraping/ytdlp for now

class InnerTubeWeb(Provider):
    """
    Provider for fast, lightweight tasks using direct YouTube/InnerTube endpoints.
    Primarily for suggestions and trending.
    """
    def __init__(self, hl: str = "en", gl: str = "US", proxy: str | None = None, fallback: Provider | None = None) -> None:
        self.hl = hl
        self.gl = gl
        self.proxy = proxy
        self._fallback = fallback
        self._client: httpx.Client | None = None
        self._init_client()

    def _init_client(self) -> None:
        try:
            if self._client:
                self._client.close()
        except Exception:
            pass
        proxy = safe_httpx_proxy(self.proxy)
        self._client = httpx.Client(
            timeout=5.0,
            proxy=proxy,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"},
            http2=False,
        )

    def suggestions(self, query: str, max_items: int = 10) -> list[str]:
        """Get search suggestions/autocomplete using the suggestqueries endpoint."""
        if not query:
            return []
        
        params = {
            "client": "youtube",
            "ds": "yt",
            "q": query,
            "hl": self.hl,
            "gl": self.gl,
        }
        
        try:
            r = self._client.get(_SUGGEST_URL, params=params)
            r.raise_for_status()
            
            text = r.text
            log.debug(f"Suggestions response: {text[:100]}...")
            
            if text.startswith("window.google.ac.h("):
                text = text[len("window.google.ac.h("):-1]
            
            data = json.loads(text)
            
            if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
                results = [str(s[0]) for s in data[1] if isinstance(s, list) and len(s) > 0][:max_items]
                log.debug(f"InnerTubeWeb suggestions: {results}")
                return results
            else:
                log.warning(f"Unexpected data structure from suggestions API: {type(data)}")
            
        except Exception as e:
            log.warning(f"InnerTubeWeb suggestions failed: {e}", exc_info=True)
            if self._fallback:
                return self._fallback.suggestions(query, max_items)
        
        return []

    def trending(self) -> list[Video]:
        """
        For InnerTubeWeb, we delegate trending to the fallback (yt-dlp)
        as a full InnerTube implementation is complex.
        """
        if self._fallback:
            return self._fallback.trending()
        return []

    # --- Delegated/Unsupported methods ---

    def search(self, query: str, limit: int, filters: dict[str, str] | None = None) -> list[Video]:
        if self._fallback:
            return self._fallback.search(query, limit, filters)
        return []

    def related(self, video_id: str) -> list[Video]:
        if self._fallback:
            return self._fallback.related(video_id)
        return []

    def comments(self, video_id: str) -> list[Video]:
        if self._fallback:
            return self._fallback.comments(video_id)
        return []

    def channel_tab(self, channel_url: str, tab: str) -> list[Video]:
        if self._fallback:
            return self._fallback.channel_tab(channel_url, tab)
        return []

    def fetch_formats(self, url: str) -> list[Format]:
        if self._fallback:
            return self._fallback.fetch_formats(url)
        return []

    def get_video_info(self, url: str) -> Video | None:
        if self._fallback:
            return self._fallback.get_video_info(url)
        return None

    def set_cookies_from_browser(self, spec: str) -> None:
        # Not supported by this provider, delegate to fallback
        if self._fallback:
            self._fallback.set_cookies_from_browser(spec)

    def get_proxy(self) -> str | None:
        return self.proxy