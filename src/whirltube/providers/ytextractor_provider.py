"""
YtExtractor-based provider for native stream resolution without yt-dlp dependency.
Uses ytextractor for playback URL resolution, yt-dlp as fallback for downloads.
"""
from __future__ import annotations

import logging
from typing import Optional

# Check if ytextractor is available
try:
    from yt_extractor import YouTubeStreamExtractor
    from yt_extractor.http_client import HttpClient as YtHttpClient
    HAS_YTEXTRACTOR = True
except ImportError:
    HAS_YTEXTRACTOR = False
    YouTubeStreamExtractor = None
    YtHttpClient = None

from ..models import Video
from ..util import safe_httpx_proxy
from .base import Provider
from .ytdlp import YTDLPProvider

log = logging.getLogger(__name__)


class YtExtractorProvider(Provider):
    """
    Provider using ytextractor for fast native stream resolution.
    Falls back to yt-dlp for search/browse/downloads.
    """
    
    def __init__(self, proxy: str | None = None, hl: str = "en", gl: str = "US"):
        if not HAS_YTEXTRACTOR:
            raise RuntimeError(
                "ytextractor not installed. Install with: pip install ytextractor"
            )
        
        self.proxy = safe_httpx_proxy(proxy)
        self.hl = hl
        self.gl = gl
        
        # ytextractor HTTP client
        self._yt_http = YtHttpClient(consent_accepted=True, timeout=15)
        
        # ytextractor stream extractor
        self._extractor = YouTubeStreamExtractor(
            self._yt_http,
            hl=self.hl,
            gl=self.gl,
            fetch_ios=True  # Fetch iOS client for best compatibility
        )
        
        # Fallback yt-dlp provider for search/browse/downloads
        self._fallback = YTDLPProvider(proxy=proxy)
    
    def get_video_info(self, url: str) -> Video | None:
        """Extract video info using ytextractor (fast native resolution)."""
        try:
            from yt_extractor.link import video_id_from_url
            
            # Parse video ID
            vid = video_id_from_url(url) if "://" in url else url
            
            # Extract using ytextractor
            info = self._extractor.extract(vid)
            
            # Convert to Video model
            vd = info.get("videoDetails", {})
            return Video(
                id=vid,
                title=vd.get("title", ""),
                url=f"https://www.youtube.com/watch?v={vid}",
                channel=vd.get("author"),
                duration=int(vd.get("lengthSeconds", 0)) or None,
                thumb_url=self._get_best_thumbnail(vd.get("thumbnail", {})),
                kind="video",
                view_count=int(vd.get("viewCount", 0)) or None,
            )
        except Exception as e:
            log.warning(f"ytextractor get_video_info failed: {e}, falling back to yt-dlp")
            return self._fallback.get_video_info(url)
    
    def fetch_formats(self, url: str) -> list[tuple[str, str]]:
        """
        Fetch available formats using ytextractor.
        Returns list of (format_id, label) tuples.
        """
        try:
            from yt_extractor.link import video_id_from_url
            
            vid = video_id_from_url(url) if "://" in url else url
            info = self._extractor.extract(vid)
            
            formats = []
            for stream in info.get("streams", []):
                itag = stream.get("itag", 0)
                mime = stream.get("mimeType", "")
                width = stream.get("width")
                height = stream.get("height")
                bitrate = stream.get("bitrate", 0)
                
                # Build label
                if height:
                    label = f"{height}p {mime.split(';')[0]} @ {bitrate//1000}k"
                else:
                    # Audio-only
                    label = f"Audio {mime.split(';')[0]} @ {bitrate//1000}k"
                
                formats.append((str(itag), label))
            
            return formats
        except Exception as e:
            log.warning(f"ytextractor fetch_formats failed: {e}, falling back")
            return self._fallback.fetch_formats(url)
    
    def _get_best_thumbnail(self, thumb_obj: dict) -> str | None:
        """Extract best thumbnail URL from videoDetails.thumbnail."""
        thumbnails = thumb_obj.get("thumbnails", [])
        if not thumbnails:
            return None
        
        # Pick highest resolution
        best = max(thumbnails, key=lambda t: t.get("width", 0) * t.get("height", 0))
        return best.get("url")
    
    # Delegate all other methods to yt-dlp fallback
    
    def search(self, query: str, limit: int, order: str | None = None, 
               duration: str | None = None, period: str | None = None) -> list[Video]:
        """Search delegates to yt-dlp (more robust filtering)."""
        return self._fallback.search(query, limit, order, duration, period)
    
    def trending(self) -> list[Video]:
        return self._fallback.trending()
    
    def related(self, video_id: str) -> list[Video]:
        return self._fallback.related(video_id)
    
    def comments(self, video_id: str) -> list[Video]:
        return self._fallback.comments(video_id)
    
    def channel_tab(self, channel_url: str, tab: str) -> list[Video]:
        return self._fallback.channel_tab(channel_url, tab)
    
    def suggestions(self, query: str, max_items: int = 10) -> list[str]:
        """Use ytextractor for fast suggestions."""
        try:
            from yt_extractor.endpoints.suggestions import get_suggestions
            return get_suggestions(self._yt_http, query, gl=self.gl)[:max_items]
        except Exception:
            return self._fallback.suggestions(query, max_items)
    
    def set_cookies_from_browser(self, spec: str) -> None:
        """Cookies only needed for yt-dlp fallback."""
        self._fallback.set_cookies_from_browser(spec)
    
    def get_proxy(self) -> str | None:
        return self.proxy