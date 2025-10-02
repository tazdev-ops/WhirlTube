from __future__ import annotations

import logging
from typing import Optional, List, Tuple

# Optional import for NewPipe extractor
NP_AVAILABLE = False
try:
    from yt_extractor import (
        YouTubeStreamExtractor,
        search as np_search,
        search_next as np_search_next,
        channel_videos,
        channel_videos_next,
        playlist_first_page,
        playlist_next,
        comments_initial,
        comments_next,
        suggestions as np_suggestions,
        kiosk_live,
        kiosk_gaming
    )
    from yt_extractor.http_client import HttpClient as NPHttpClient
    from yt_extractor.link import video_id_from_url
    NP_AVAILABLE = True
except ImportError:
    logging.getLogger(__name__).warning("yt_extractor not available; NewPipeProvider disabled")

from ..models import Video
from .base import Provider
from ..util import safe_httpx_proxy

log = logging.getLogger(__name__)


class NewPipeProvider(Provider):
    """Lightweight InnerTube-based provider using yt_extractor."""

    def __init__(self, proxy: str | None = None, hl: str = "en", gl: str = "US"):
        if not NP_AVAILABLE:
            raise RuntimeError("yt_extractor not installed. Use another provider.")
        self.proxy = safe_httpx_proxy(proxy)
        self.hl = hl
        self.gl = gl
        self._http = NPHttpClient(timeout=15, consent_accepted=False)
        # Note: HttpClient proxy handling may need extension if not supported
        if self.proxy:
            log.debug("Proxy configured but HttpClient proxy support pending")

    def search(self, query: str, limit: int = 20, filters: dict | None = None) -> List[Video]:
        try:
            result = np_search(self._http, query, hl=self.hl, gl=self.gl)
            items = result.get("items", [])[:limit]
            return [self._to_video(it) for it in items]
        except Exception as e:
            log.error(f"NewPipe search failed: {e}")
            return []

    def trending(self) -> List[Video]:
        try:
            result = kiosk_live(self._http, hl=self.hl, gl=self.gl)
            items = result.get("items", [])
            return [self._to_video(it) for it in items]
        except Exception as e:
            log.error(f"NewPipe trending failed: {e}")
            return []

    def related(self, video_id: str) -> List[Video]:
        log.warning("NewPipe related() not implemented")
        return []

    def comments(self, video_id: str) -> List[Video]:
        try:
            result = comments_initial(self._http, video_id, hl=self.hl, gl=self.gl)
            items = result.get("comments", [])
            return [
                Video(
                    id=c.get("id", ""),
                    title=c.get("textHtml", ""),
                    url=f"https://youtube.com/watch?v={video_id}&lc={c.get('id')}",
                    channel=c.get("author"),
                    duration=None,
                    thumb_url=None,
                    kind="comment"
                ) for c in items
            ]
        except Exception as e:
            log.error(f"NewPipe comments failed: {e}")
            return []

    def channel_tab(self, channel_url: str, tab: str) -> List[Video]:
        try:
            result = channel_videos(self._http, channel_url, hl=self.hl, gl=self.gl)
            items = result.get("items", [])
            return [self._to_video(it) for it in items]
        except Exception as e:
            log.error(f"NewPipe channel_tab failed: {e}")
            return []

    def fetch_formats(self, url: str) -> List[Tuple[str, str]]:
        try:
            vid = video_id_from_url(url)
            extractor = YouTubeStreamExtractor(self._http, hl=self.hl, gl=self.gl, fetch_ios=False)
            data = extractor.extract(vid)
            streams = data.get("streams", [])
            out = []
            for s in streams:
                itag = s.get("itag", 0)
                mime = s.get("mimeType", "")
                w = s.get("width", "?")
                h = s.get("height", "?")
                label = f"{w}x{h} {mime.split(';')[0]}"
                out.append((str(itag), label))
            return out
        except Exception as e:
            log.error(f"NewPipe fetch_formats failed: {e}")
            return []

    def get_video_info(self, url: str) -> Optional[Video]:
        try:
            vid = video_id_from_url(url)
            extractor = YouTubeStreamExtractor(self._http, hl=self.hl, gl=self.gl, fetch_ios=False)
            data = extractor.extract(vid)
            vd = data.get("videoDetails", {})
            return Video(
                id=vid,
                title=vd.get("title", ""),
                url=url,
                channel=vd.get("author"),
                duration=int(vd.get("lengthSeconds", 0)) or None,
                thumb_url=None,
                kind="video"
            )
        except Exception as e:
            log.error(f"NewPipe get_video_info failed: {e}")
            return None

    def set_cookies_from_browser(self, spec: str) -> None:
        log.warning("NewPipe provider does not support cookies-from-browser")

    def suggestions(self, query: str, max_items: int = 10) -> List[str]:
        try:
            return np_suggestions(self._http, query, hl=self.hl, gl=self.gl)[:max_items]
        except Exception:
            return []

    def get_proxy(self) -> Optional[str]:
        return self.proxy

    def _to_video(self, item: dict) -> Video:
        """Convert extractor item to Video model."""
        return Video(
            id=item.get("videoId", ""),
            title=item.get("title", ""),
            url=item.get("url", ""),
            channel=item.get("uploader"),
            duration=None,  # Often not in search results
            thumb_url=None,
            kind=item.get("type", "video")
        )