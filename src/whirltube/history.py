from __future__ import annotations

import json
import time
from typing import Any

from .models import Video
from .util import xdg_cache_dir

_CACHE = xdg_cache_dir()
SEARCH = _CACHE / "search_history.txt"
WATCH = _CACHE / "watch_history.jsonl"


def add_search_term(query: str) -> None:
    q = query.strip()
    if not q:
        return
    SEARCH.parent.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime())
    with SEARCH.open("a", encoding="utf-8") as f:
        f.write(f"{ts}\t{q}\n")


def add_watch(video: Video) -> None:
    WATCH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "id": video.id,
        "title": video.title,
        "url": video.url,
        "channel": video.channel,
        "duration": video.duration,
        "thumb_url": video.thumb_url,
        "kind": video.kind,
        "ts": int(time.time()),
    }
    with WATCH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")


def list_watch(limit: int = 200) -> list[Video]:
    if not WATCH.exists():
        return []
    out: list[Video] = []
    lines = WATCH.read_text(encoding="utf-8").splitlines()
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            it: dict[str, Any] = json.loads(line)
            out.append(
                Video(
                    id=str(it.get("id") or ""),
                    title=it.get("title") or "",
                    url=it.get("url") or "",
                    channel=it.get("channel"),
                    duration=it.get("duration"),
                    thumb_url=it.get("thumb_url"),
                    kind=it.get("kind") or "video",
                )
            )
            if len(out) >= limit:
                break
        except Exception:
            continue
    return out
