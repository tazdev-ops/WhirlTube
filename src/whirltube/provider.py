from __future__ import annotations

import logging
import datetime
import time

from yt_dlp import YoutubeDL

from .models import Video

log = logging.getLogger(__name__)

_BASE_OPTS = {
    "quiet": True,
    "nocheckcertificate": True,
    "retries": 3,
    "fragment_retries": 2,
}


class YTDLPProvider:
    """YouTube operations via yt-dlp. No API keys required."""

    def __init__(self, proxy: str | None = None) -> None:
        self._opts_base: dict = dict(_BASE_OPTS)
        if proxy:
            self._opts_base["proxy"] = proxy
        self._reinit()

    def set_proxy(self, proxy: str | None) -> None:
        # Update base options and reinitialize internal extractors
        self._opts_base = dict(_BASE_OPTS)
        if proxy:
            self._opts_base["proxy"] = proxy
        self._reinit()

    def _reinit(self) -> None:
        # Flat for listings
        self._ydl_flat = YoutubeDL(dict(self._opts_base, **{"skip_download": True, "extract_flat": "in_playlist"}))
        # Full for details when needed
        self._ydl_full = YoutubeDL(dict(self._opts_base, **{"skip_download": True}))

    # ---------- Search ----------

    def search(self, query: str, limit: int = 20, order: str | None = None, duration: str | None = None, period: str | None = None) -> list[Video]:
        """
        order: None|"relevance"|"date"|"views"
        duration: None|"short"|"medium"|"long"
        period: None|"today"|"week"|"month"
        """
        query = query.strip()
        if not query:
            return []
        limit = max(1, min(limit, 50))
        ordv = (order or "").lower().strip()
        if ordv == "date":
            spec = f"ytsearchdate{limit}:{query}"
        else:
            spec = f"ytsearch{limit}:{query}"
        log.debug("yt-dlp search: %s (order=%s, duration=%s, period=%s)", spec, order, duration, period)
        info = self._ydl_flat.extract_info(spec, download=False)
        entries: list[dict] = [e for e in (info.get("entries") or []) if isinstance(e, dict)]

        # Optional sort by views if we didn't use ytsearchdate
        if ordv == "views":
            try:
                entries.sort(key=lambda e: int(e.get("view_count") or 0), reverse=True)
            except Exception:
                pass

        # Duration filter
        dur = (duration or "").lower().strip()
        if dur in {"short", "medium", "long"}:
            def _dur_ok(e: dict) -> bool:
                try:
                    d = int(e.get("duration") or 0)
                except Exception:
                    d = 0
                if dur == "short":
                    return d and d < 4 * 60
                if dur == "medium":
                    return 4 * 60 <= d <= 20 * 60
                if dur == "long":
                    return d and d > 20 * 60
                return True
            entries = [e for e in entries if _dur_ok(e)]

        # Period filter (best effort)
        per = (period or "").lower().strip()
        if per in {"today", "week", "month"}:
            now = int(time.time())
            day = 24 * 3600
            if per == "today":
                cutoff = now - day
            elif per == "week":
                cutoff = now - 7 * day
            else:
                cutoff = now - 30 * day
            def _ts(e: dict) -> int | None:
                t = e.get("timestamp")
                if isinstance(t, (int, float)):
                    return int(t)
                ud = e.get("upload_date")  # YYYYMMDD
                if isinstance(ud, str) and len(ud) == 8 and ud.isdigit():
                    try:
                        dt = datetime.datetime.strptime(ud, "%Y%m%d").replace(tzinfo=datetime.timezone.utc)
                        return int(dt.timestamp())
                    except Exception:
                        return None
                return None
            ent2 = []
            for e in entries:
                ts = _ts(e)
                if ts is None:
                    # keep when unknown (avoid over-filtering)
                    ent2.append(e)
                elif ts >= cutoff:
                    ent2.append(e)
            entries = ent2

        return [_entry_to_video(e) for e in entries]

    # ---------- Browse helpers ----------

    def trending(self) -> list[Video]:
        """List trending feed."""
        url = "https://www.youtube.com/feed/trending"
        log.debug("yt-dlp browse trending: %s", url)
        try:
            data = self._ydl_flat.extract_info(url, download=False)
            entries = data.get("entries") or []
            return [_entry_to_video(e) for e in entries if isinstance(e, dict)]
        except Exception as e:
            log.exception("trending failed: %s", e)
            return []

    def browse_url(self, url: str) -> list[Video]:
        """
        Generic "open URL" listing: video -> single entry; playlist/channel -> flat entries.
        """
        url = url.strip()
        if not url:
            return []
        log.debug("browse url: %s", url)
        try:
            data = self._ydl_flat.extract_info(url, download=False)
            entries = data.get("entries")
            if entries:
                return [_entry_to_video(e) for e in entries if isinstance(e, dict)]
            # Single item
            return [_info_to_video(data)]
        except Exception as e:
            log.exception("browse_url failed: %s", e)
            return []

    def channel_tab(self, chan_url: str, tab: str = "videos") -> list[Video]:
        """Browse a channel tab: /videos, /streams, /playlists."""
        tab = tab.strip("/").lower()
        base = _ensure_channel_root(chan_url)
        if not base.endswith(f"/{tab}"):
            url = base.rstrip("/") + f"/{tab}"
        else:
            url = base
        log.debug("channel_tab: %s", url)
        return self.browse_url(url)

    def playlist(self, playlist_url: str) -> list[Video]:
        """Browse a playlist entries."""
        return self.browse_url(playlist_url)

    def related(self, video_url: str) -> list[Video]:
        """Fetch related/suggested items. Falls back to title-based search if missing."""
        try:
            info = self._ydl_full.extract_info(video_url, download=False)
        except Exception as e:
            log.exception("related failed: %s", e)
            return []
        out: list[Video] = []
        if isinstance(info, dict):
            rel = info.get("related") or info.get("related_videos") or []
            if isinstance(rel, list):
                for e in rel:
                    if isinstance(e, dict):
                        out.append(_entry_to_video(e))
            if out:
                return out
            # Fallback: title search
            title = (info.get("title") or "").strip()
            if title:
                spec = f"ytsearch20:{title}"
                try:
                    s = self._ydl_flat.extract_info(spec, download=False)
                    entries = s.get("entries") or []
                    out = [_entry_to_video(e) for e in entries if isinstance(e, dict)]
                    # Filter out the same URL if present
                    out = [v for v in out if v.url != video_url]
                except Exception as e:
                    log.debug("related fallback search failed: %s", e)
        return out

    def comments(self, video_url: str, max_comments: int = 100) -> list[Video]:
        """Fetch top-level comments when available via yt-dlp API."""
        opts = dict(_BASE_OPTS, **{"skip_download": True, "getcomments": True})
        y = YoutubeDL(opts)
        try:
            info = y.extract_info(video_url, download=False)
        except Exception as e:
            log.exception("comments failed: %s", e)
            return []
        comments = info.get("comments") or []
        out: list[Video] = []
        for i, c in enumerate(comments):
            if i >= max_comments:
                break
            comment_id = c.get("id") or c.get("comment_id") or ""
            author = c.get("author") or c.get("uploader") or "Comment"
            url = f"{video_url}&lc={comment_id}" if comment_id else video_url
            out.append(
                Video(
                    id=str(comment_id),
                    title=author,
                    url=url,
                    channel=author,
                    duration=None,
                    thumb_url=None,
                    kind="comment",
                )
            )
        return out

    def fetch_formats(self, url: str) -> list[tuple[str, str]]:
        """Return list of (format_id, label) for a given URL."""
        opts = dict(_BASE_OPTS, **{"skip_download": True, "listformats": False})
        y = YoutubeDL(opts)
        info = y.extract_info(url, download=False)
        fmts = info.get("formats") or []
        out: list[tuple[str, str]] = []
        for f in fmts:
            fid = str(f.get("format_id"))
            v = f.get("vcodec") or "—"
            a = f.get("acodec") or "—"
            h = f.get("height") or "?"
            w = f.get("width") or "?"
            res = f"{w}x{h}"
            br = f.get("tbr") or f.get("abr") or f.get("vbr") or "?"
            label = f"{res} {v}/{a} @ {br}k"
            out.append((fid, label))
        return out


def _entry_to_video(e: dict) -> Video:
    vid = e.get("id") or e.get("url") or ""
    title = e.get("title") or "(untitled)"
    webpage = e.get("webpage_url") or e.get("original_url") or e.get("url") or _watch_url(vid)
    channel = e.get("channel") or e.get("uploader")
    duration = e.get("duration")
    thumb = _pick_thumb(e.get("thumbnails"))

    # Kind inference
    kind = "video"
    t = e.get("_type")
    ie = (e.get("ie_key") or "").strip()
    if t == "playlist" or ie in {"YoutubePlaylist", "YoutubeTab"}:
        kind = "playlist"
        webpage = e.get("webpage_url") or webpage
    elif ie in {"YoutubeChannel"} or e.get("channel_url") or (e.get("playlist_uploader") and not e.get("duration")):
        kind = "channel"
        ch = e.get("channel_url") or e.get("uploader_url") or webpage
        if ch:
            webpage = _ensure_channel_root(ch) + "/videos"
    elif t == "url" and "playlist" in (e.get("url") or ""):
        kind = "playlist"

    return Video(
        id=str(vid),
        title=title,
        url=webpage,
        channel=channel,
        duration=int(duration) if duration else None,
        thumb_url=thumb,
        kind=kind,
    )

def _info_to_video(info: dict) -> Video:
    return _entry_to_video(info)

def _watch_url(vid: str) -> str:
    return f"https://www.youtube.com/watch?v={vid}" if vid else ""

def _ensure_channel_root(url: str) -> str:
    """
    Return a canonical channel root or user/handle root:
    Works with /channel/UC..., /@handle, /user/..., /c/...
    """
    u = (url or "").rstrip("/")
    for seg in ("/channel/", "/user/", "/c/", "/@"):
        if seg in u:
            return u
    if "/" not in u:
        return "https://www.youtube.com/channel/" + u
    return u

def _pick_thumb(thumbs: object) -> str | None:
    if not isinstance(thumbs, list) or not thumbs:
        return None
    best = None
    best_w = -1
    for t in thumbs:
        if not isinstance(t, dict):
            continue
        w = t.get("width") or 0
        url = t.get("url")
        if url and w > best_w:
            best = url
            best_w = w
    return best
