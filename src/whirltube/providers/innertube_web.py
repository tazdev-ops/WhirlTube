from __future__ import annotations
import httpx
import logging
from typing import Any, Iterable
from ..models import Video

log = logging.getLogger(__name__)

WEB_VER = "2.20250122.04.00"

def _headers():
    return {
        "Origin": "https://www.youtube.com",
        "Referer": "https://www.youtube.com",
        "Content-Type": "application/json",
        "X-YouTube-Client-Name": "1",
        "X-YouTube-Client-Version": WEB_VER,
    }

def _ctx(hl: str, gl: str):
    return {
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": WEB_VER,
                "hl": hl, "gl": gl,
                "platform": "DESKTOP",
                "utcOffsetMinutes": 0,
            },
            "request": {"useSsl": True, "internalExperimentFlags": []},
            "user": {"lockedSafetyMode": False},
        }
    }

def _walk(obj: Any, key: str) -> Iterable[dict]:
    if isinstance(obj, dict):
        if key in obj:
            yield obj[key]
        for v in obj.values():
            yield from _walk(v, key)
    elif isinstance(obj, list):
        for it in obj:
            yield from _walk(it, key)

def _parse_duration(s: str | None) -> int | None:
    if not s:
        return None
    parts = s.strip().split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return None
    if len(parts) == 3:
        h, m, sec = parts
        return h*3600 + m*60 + sec
    if len(parts) == 2:
        m, sec = parts
        return m*60 + sec
    if len(parts) == 1:
        return parts[0]
    return None

def _thumb(thumbnails: list[dict] | None) -> str | None:
    if not thumbnails:
        return None
    best = max(thumbnails, key=lambda x: int(x.get("width") or 0))
    return best.get("url")

class InnerTubeWeb:
    def __init__(self, hl: str = "en", gl: str = "US", client: httpx.Client | None = None):
        self.hl = hl
        self.gl = gl
        self._c = client or httpx.Client(timeout=12.0)

    def trending(self) -> list[Video]:
        url = "https://www.youtube.com/youtubei/v1/browse?prettyPrint=false"
        body = _ctx(self.hl, self.gl) | {"browseId": "FEtrending"}
        r = self._c.post(url, headers=_headers(), json=body)
        r.raise_for_status()
        data = r.json()
        out: list[Video] = []
        for vr in _walk(data, "videoRenderer"):
            vid = vr.get("videoId")
            title = (vr.get("title") or {}).get("simpleText") or \
                    " ".join([run.get("text","") for run in (vr.get("title") or {}).get("runs",[])])
            ch = (vr.get("ownerText") or {}).get("runs", [{}])[0].get("text")
            dur_str = (vr.get("lengthText") or {}).get("simpleText")
            duration = _parse_duration(dur_str)
            thumb = _thumb((vr.get("thumbnail") or {}).get("thumbnails"))
            if not vid or not title:
                continue
            out.append(Video(
                id=vid, title=title, url=f"https://www.youtube.com/watch?v={vid}",
                channel=ch, duration=duration, thumb_url=thumb, kind="video"
            ))
        return out

    def comments(self, video_id: str, limit: int = 100) -> list[Video]:
        url = "https://www.youtube.com/youtubei/v1/next?prettyPrint=false"
        body = _ctx(self.hl, self.gl) | {"videoId": video_id}
        r = self._c.post(url, headers=_headers(), json=body)
        r.raise_for_status()
        data = r.json()

        # Find first continuation token
        cont = None
        for ci in _walk(data, "continuationItemRenderer"):
            endpoint = (ci.get("continuationEndpoint") or {}).get("continuationCommand") or {}
            cont = endpoint.get("token")
            if cont:
                break
        if not cont:
            return []

        out: list[Video] = []
        fetch = 0
        while cont and len(out) < limit:
            r2 = self._c.post(url, headers=_headers(), json={"context": _ctx(self.hl, self.gl)["context"], "continuation": cont})
            r2.raise_for_status()
            d2 = r2.json()

            threads = []
            for a in _walk(d2, "appendContinuationItemsAction"):
                threads.extend(a.get("continuationItems", []))

            for it in threads:
                ctr = it.get("commentThreadRenderer")
                if not ctr:
                    continue
                cr = ctr.get("comment", {}).get("commentRenderer") or {}
                author = (cr.get("authorText") or {}).get("simpleText") or "Comment"
                text_runs = (cr.get("contentText") or {}).get("runs") or []
                text = "".join([run.get("text","") for run in text_runs]) or "(empty)"
                cid = cr.get("commentId") or ""
                out.append(Video(
                    id=str(cid), title=text[:200], url=f"https://www.youtube.com/watch?v={video_id}&lc={cid}",
                    channel=author, duration=None, thumb_url=None, kind="comment"
                ))
                if len(out) >= limit:
                    break

            cont = None
            for ci in _walk(d2, "continuationItemRenderer"):
                endpoint = (ci.get("continuationEndpoint") or {}).get("continuationCommand") or {}
                cont = endpoint.get("token")
                if cont:
                    break

            fetch += 1
            if fetch > 20:
                break

        return out

    def suggestions(self, q: str, max_items: int = 10) -> list[str]:
        url = "https://suggestqueries.google.com/complete/search"
        params = {"client": "firefox", "ds": "yt", "q": q, "hl": self.hl, "gl": self.gl}
        try:
            resp = self._c.get(url, params=params, timeout=5.0)
            resp.raise_for_status()
            js = resp.json()
            if isinstance(js, list) and len(js) >= 2 and isinstance(js[1], list):
                return [s for s in js[1][:max_items] if isinstance(s, str)]
        except Exception:
            pass
        return []
