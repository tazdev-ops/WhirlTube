from __future__ import annotations
import json
from .util import xdg_data_dir

_WATCHED = xdg_data_dir() / "watched_videos.json"

def _load() -> dict[str, bool]:
    if not _WATCHED.exists():
        return {}
    try:
        return json.loads(_WATCHED.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save(data: dict):
    _WATCHED.parent.mkdir(parents=True, exist_ok=True)
    _WATCHED.write_text(json.dumps(data), encoding="utf-8")

def is_watched(video_id: str) -> bool:
    return _load().get(video_id, False)

def mark_as_watched(video_id: str):
    data = _load()
    data[video_id] = True
    _save(data)

def mark_as_unwatched(video_id: str):
    data = _load()
    data.pop(video_id, None)
    _save(data)