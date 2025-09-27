from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .models import Video
from .provider import YTDLPProvider  # reuse helpers where helpful
from .util import safe_httpx_proxy

log = logging.getLogger(__name__)

@dataclass(slots=True)
class _Cfg:
    base: str
    proxy: str | None = None
    timeout: float = 12.0

class InvidiousProvider:
    """
    Minimal Invidious API provider for search and channel videos.
    Falls back to YTDLPProvider for unsupported operations.
    """
    def __init__(self, base_url: str, proxy: str | None = None, fallback: YTDLPProvider | None = None) -> None:
        self.cfg = _Cfg(base=base_url.rstrip("/"), proxy=proxy)
        self._fallback = fallback or YTDLPProvider()
        self._client: httpx.Client | None = None
        self._init_client()

    def set_proxy(self, proxy: str | None) -> None:
        self.cfg.proxy = proxy or None
        self._init_client()

    def _init_client(self) -> None:
        try:
            if self._client:
                self._client.close()
        except Exception:
            pass
        proxy = safe_httpx_proxy(self.cfg.proxy)
        self._client = httpx.Client(timeout=self.cfg.timeout, proxies=proxy, headers={"User-Agent": "whirltube/0.4"})

    # ---------- Search ----------

    def search(self, query: str, limit: int = 20, order: str | None = None, duration: str | None = None, period: str | None = None) -> list[Video]:
        q = (query or "").strip()
        if not q:
            return []
        params: dict[str, Any] = {
            "q": q,
            "type": "video",
            "page": 1,
        }
        # Map order
        ordv = (order or "").lower().strip()
        if ordv == "date":
            params["sort_by"] = "upload_date"
        elif ordv == "views":
            params["sort_by"] = "view_count"
        else:
            params["sort_by"] = "relevance"

        # Optional search filters (best effort)
        # period -> time; Invidious may support 'hour','day','week','month','year' in some instances. We'll approximate client-side below as well.
        per = (period or "").lower().strip()
        if per == "today":
            params["date"] = "today"
        elif per == "week":
            params["date"] = "week"
        elif per == "month":
            params["date"] = "month"

        # Fetch
        try:
            assert self._client is not None
            r = self._client.get(f"{self.cfg.base}/api/v1/search", params=params)
            r.raise_for_status()
            data = r.json()
            items: list[dict] = data if isinstance(data, list) else []
        except Exception as e:
            log.debug("Invidious search failed (%s); fallback to yt-dlp", e)
            # Fallback to yt-dlp provider with same filters
            return self._fallback.search(query, limit=limit, order=order, duration=duration, period=period)

        vids: list[Video] = []
        now = int(time.time())

        def _dur_ok(seconds: int | None) -> bool:
            d = int(seconds or 0)
            dtag = (duration or "").lower().strip()
            if not dtag or dtag == "any":
                return True
            if dtag == "short":
                return 0 < d < 4 * 60
            if dtag == "medium":
                return 4 * 60 <= d <= 20 * 60
            if dtag == "long":
                return d > 20 * 60
            return True

        def _time_ok(published: int | None) -> bool:
            ptag = (period or "").lower().strip()
            if not ptag or ptag == "any":
                return True
            if not published:
                return True  # keep unknowns
            day = 86400
            cutoff = now - (day if ptag == "today" else 7 * day if ptag == "week" else 30 * day)
            return published >= cutoff

        for it in items:
            try:
                if it.get("type") != "video":
                    continue
                dur = int(it.get("lengthSeconds") or 0)
                pub = int(it.get("published") or 0)
                if not _dur_ok(dur) or not _time_ok(pub):
                    continue
                vid = str(it.get("videoId") or "")
                url = f"https://www.youtube.com/watch?v={vid}" if vid else (it.get("videoThumbnails") or [{}])[0].get("url", "")
                thumb = None
                thumbs = it.get("videoThumbnails") or []
                if thumbs and isinstance(thumbs, list):
                    # pick the widest
                    best = max((t for t in thumbs if isinstance(t, dict)), key=lambda x: int(x.get("width") or 0), default=None)
                    if best:
                        thumb = best.get("url")
                vids.append(
                    Video(
                        id=vid or url,
                        title=it.get("title") or "(untitled)",
                        url=url,
                        channel=it.get("author") or None,
                        duration=dur or None,
                        thumb_url=thumb,
                        kind="video",
                    )
                )
                if len(vids) >= limit:
                    break
            except Exception:
                continue
        return vids

    # ---------- Browse helpers ----------

    def _channel_id_from_url(self, url: str) -> str | None:
        u = (url or "").strip()
        # Only support /channel/UC... robustly; other forms fallback
        i = u.find("/channel/")
        if i >= 0:
            cid = u[i + len("/channel/") :].split("/")[0]
            if cid:
                return cid
        return None

    def channel_tab(self, chan_url: str, tab: str = "videos") -> list[Video]:
        cid = self._channel_id_from_url(chan_url)
        if not cid:
            return self._fallback.channel_tab(chan_url, tab=tab)
        try:
            assert self._client is not None
            r = self._client.get(f"{self.cfg.base}/api/v1/channels/{cid}/videos", params={"page": 1})
            r.raise_for_status()
            data = r.json()
            items: list[dict] = data.get("videos") if isinstance(data, dict) else []
        except Exception as e:
            log.debug("Invidious channel_tab failed (%s); fallback to yt-dlp", e)
            return self._fallback.channel_tab(chan_url, tab=tab)

        out: list[Video] = []
        for it in items or []:
            try:
                vid = str(it.get("videoId") or "")
                url = f"https://www.youtube.com/watch?v={vid}" if vid else ""
                dur = int(it.get("lengthSeconds") or 0) or None
                thumb = None
                thumbs = it.get("videoThumbnails") or []
                if thumbs and isinstance(thumbs, list):
                    best = max((t for t in thumbs if isinstance(t, dict)), key=lambda x: int(x.get("width") or 0), default=None)
                    if best:
                        thumb = best.get("url")
                out.append(
                    Video(
                        id=vid or url,
                        title=it.get("title") or "(untitled)",
                        url=url or it.get("authorUrl") or "",
                        channel=it.get("author") or None,
                        duration=dur,
                        thumb_url=thumb,
                        kind="video",
                    )
                )
            except Exception:
                continue
        return out

    def browse_url(self, url: str) -> list[Video]:
        # We can only handle channels robustly when /channel/UC...; otherwise fallback
        if "/channel/" in (url or ""):
            return self.channel_tab(url, "videos")
        return self._fallback.browse_url(url)

    # ---------- Delegated methods ----------

    def playlist(self, playlist_url: str) -> list[Video]:
        return self._fallback.playlist(playlist_url)

    def related(self, video_url: str) -> list[Video]:
        return self._fallback.related(video_url)

    def comments(self, video_url: str, max_comments: int = 100) -> list[Video]:
        return self._fallback.comments(video_url, max_comments=max_comments)

    def fetch_formats(self, url: str) -> list[tuple[str, str]]:
        return self._fallback.fetch_formats(url)