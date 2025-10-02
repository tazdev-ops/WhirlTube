from __future__ import annotations
from .base import Provider
from .ytdlp import YTDLPProvider
from .innertube_web import InnerTubeWeb
from ..models import Video
import re
import urllib.parse

def _extract_id(url: str) -> str | None:
    try:
        u = urllib.parse.urlparse(url)
        host = (u.hostname or "").lower()
        if host == "youtu.be":
            m = re.match(r"^/([0-9A-Za-z_-]{11})", u.path or "")
            return m.group(1) if m else None
        if host.endswith("youtube.com"):
            if (u.path or "").startswith("/watch"):
                q = urllib.parse.parse_qs(u.query or "")
                v = q.get("v", [None])[0]
                if v and re.fullmatch(r"[0-9A-Za-z_-]{11}", v):
                    return v
            m = re.match(r"^/(?:shorts|embed)/([0-9A-Za-z_-]{11})", u.path or "")
            return m.group(1) if m else None
    except Exception:
        return None
    return None

class HybridProvider(Provider):
    def __init__(self, web: InnerTubeWeb, fallback: YTDLPProvider):
        self._web = web
        self._fb = fallback

    # Keep yt-dlp paths for everything else
    def search(self, *a, **k): return self._fb.search(*a, **k)
    def browse_url(self, *a, **k): return self._fb.browse_url(*a, **k)
    def playlist(self, *a, **k): return self._fb.playlist(*a, **k)
    def related(self, *a, **k): return self._fb.related(*a, **k)
    def fetch_formats(self, *a, **k): return self._fb.fetch_formats(*a, **k)
    def channel_url_of(self, *a, **k): return self._fb.channel_url_of(*a, **k)

    def trending(self) -> list[Video]:
        try:
            vids = self._web.trending()
            return vids or self._fb.trending()
        except Exception:
            return self._fb.trending()

    def comments(self, video_url: str, max_comments: int = 100) -> list[Video]:
        vid = _extract_id(video_url)
        if not vid:
            return []
        try:
            out = self._web.comments(vid, limit=max_comments)
            return out or self._fb.comments(video_url, max_comments=max_comments)
        except Exception:
            return self._fb.comments(video_url, max_comments=max_comments)
