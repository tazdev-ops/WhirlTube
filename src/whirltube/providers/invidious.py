from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ..models import Video
from .ytdlp import YTDLPProvider  # reuse helpers where helpful
from ..util import safe_httpx_proxy
from .base import Provider

DEFAULT_TIMEOUT = 12.0
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"

log = logging.getLogger(__name__)

@dataclass(slots=True)
class _Cfg:
    base: str
    proxy: str | None = None
    timeout: float = DEFAULT_TIMEOUT

class InvidiousProvider(Provider):
    """
    Minimal Invidious API provider for search and channel videos.
    Falls back to YTDLPProvider for unsupported operations.
    """
    def __init__(self, base_url: str, proxy: str | None = None, fallback: YTDLPProvider | None = None) -> None:
        self.cfg = _Cfg(base=base_url.rstrip("/"), proxy=proxy)
        
        # Ensure fallback is YTDLPProvider, not InvidiousProvider
        if fallback and not isinstance(fallback, YTDLPProvider):
            log.warning(f"Invalid fallback type: {type(fallback)}, using default YTDLPProvider")
            fallback = None
        
        self._fallback = fallback or YTDLPProvider()
        self._client: httpx.Client | None = None
        self._init_client()
        self._prefer_invidious_links = True  # return base/watch?v=ID
        
        # Create fallback clients once for reuse to avoid excessive client creation
        self._fallback_client_no_verify = httpx.Client(
            timeout=self.cfg.timeout,
            proxy=safe_httpx_proxy(self.cfg.proxy),
            headers={"User-Agent": UA},
            http2=False,
            verify=False
        )
        self._fallback_client_no_proxy = httpx.Client(
            timeout=self.cfg.timeout,
            headers={"User-Agent": UA},
            http2=False,
            verify=False,
            trust_env=False
        )

    def _watch_url(self, vid: str) -> str:
        if not vid:
            return ""
        if self._prefer_invidious_links:
            return f"{self.cfg.base}/watch?v={vid}"
        return f"https://www.youtube.com/watch?v={vid}"

    def set_proxy(self, proxy: str | None) -> None:
        self.cfg.proxy = proxy or None
        self._init_client()

    def _init_client(self) -> None:
        try:
            if self._client:
                self._client.close()
        except Exception:
            pass
        try:
            if self._fallback_client_no_verify:
                self._fallback_client_no_verify.close()
        except Exception:
            pass
        try:
            if self._fallback_client_no_proxy:
                self._fallback_client_no_proxy.close()
        except Exception:
            pass
        proxy = safe_httpx_proxy(self.cfg.proxy)
        # http2 off avoids some flaky proxies; UA set to a browser for compatibility
        self._client = httpx.Client(
            timeout=self.cfg.timeout,
            proxy=proxy,
            headers={"User-Agent": UA},
            http2=False,
        )
        # Recreate fallback clients with updated proxy setting
        self._fallback_client_no_verify = httpx.Client(
            timeout=self.cfg.timeout,
            proxy=proxy,  # Use the same proxy as main client
            headers={"User-Agent": UA},
            http2=False,
            verify=False
        )
        self._fallback_client_no_proxy = httpx.Client(
            timeout=self.cfg.timeout,
            headers={"User-Agent": UA},
            http2=False,
            verify=False,
            trust_env=False
        )

    def _robust_api_call(self, endpoint: str, params: dict | None = None) -> dict | list:
        """Try API call with multiple fallback strategies"""
        params = params or {}
        strategies = [
            (self._client, {}),  # Normal with proxy
            (self._fallback_client_no_verify, {'verify': False}),  # No verify
            (self._fallback_client_no_proxy, {'no_proxy': True, 'verify': False}),  # No proxy
        ]
        
        for client, opts in strategies:
            try:
                r = client.get(f"{self.cfg.base}{endpoint}", params=params)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                log.debug(f"Strategy {opts} failed for {endpoint}: {e}")
                continue
        
        raise RuntimeError(f"All strategies failed for {endpoint}")

    def trending(self, limit: int = 20, region: str | None = None) -> list[Video]:
        """
        Return trending videos. Tries Invidious API; falls back to yt-dlp.
        """
        params: dict[str, Any] = {"type": "video"}
        if region:
            params["region"] = region
        
        items: list[dict] = []
        try:
            data = self._robust_api_call("/api/v1/trending", params=params)
            items = data if isinstance(data, list) else []
        except RuntimeError:
            log.debug("Invidious trending failed; trying /popular fallback.")
            try:
                data = self._robust_api_call("/api/v1/popular")
                items = data if isinstance(data, list) else []
            except RuntimeError as e:
                log.debug("Invidious /popular also failed (%s); using yt-dlp", e)
                return self._fallback.trending()

        vids: list[Video] = []
        for it in items:
            try:
                if it.get("type") and it.get("type") != "video":
                    continue
                vid = str(it.get("videoId") or "")
                if not vid:
                    continue
                dur = int(it.get("lengthSeconds") or 0) or None
                thumbs = it.get("videoThumbnails") or []
                thumb = None
                if isinstance(thumbs, list):
                    best = max((t for t in thumbs if isinstance(t, dict)), key=lambda x: int(x.get("width") or 0), default=None)
                    if best:
                        thumb = best.get("url")
                vids.append(
                    Video(
                        id=vid,
                        title=it.get("title") or "(untitled)",
                        url=self._watch_url(vid),
                        channel=it.get("author") or None,
                        duration=dur,
                        thumb_url=thumb,
                        kind="video",
                    )
                )
                if len(vids) >= limit:
                    break
            except Exception:
                continue
        return vids

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
            data = self._robust_api_call("/api/v1/search", params=params)
            items: list[dict] = data if isinstance(data, list) else []
        except RuntimeError as e:
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
                url = self._watch_url(vid) if vid else (it.get("videoThumbnails") or [{}])[0].get("url", "")
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

    def suggestions(self, query: str) -> list[str]:
        q = (query or "").strip()
        if not q:
            return []
        params = {"q": q}
        try:
            data = self._robust_api_call("/api/v1/search/suggestions", params=params)
            if isinstance(data, dict):
                suggestions = data.get("suggestions")
                if isinstance(suggestions, list):
                    return [str(s) for s in suggestions if isinstance(s, str)]
        except RuntimeError as e:
            log.debug("Invidious suggestions failed (%s); fallback", e)
            return self._fallback.suggestions(query)
        return []

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
            data = self._robust_api_call(f"/api/v1/channels/{cid}/videos", params={"page": 1})
            items: list[dict] = data.get("videos") if isinstance(data, dict) else []
        except RuntimeError as e:
            log.debug("Invidious channel_tab failed (%s); fallback to yt-dlp", e)
            return self._fallback.channel_tab(chan_url, tab=tab)

        out: list[Video] = []
        for it in items or []:
            try:
                vid = str(it.get("videoId") or "")
                url = self._watch_url(vid) if vid else ""
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

    def channel_url_of(self, video_url: str) -> str | None:
        return self._fallback.channel_url_of(video_url)