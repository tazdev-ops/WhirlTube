from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import Video
from .util import xdg_data_dir

_DL = xdg_data_dir() / "download_history.jsonl"

@dataclass(slots=True)
class DownloadEntry:
    id: str
    title: str
    url: str
    channel: str | None
    duration: int | None
    thumb_url: str | None
    kind: str
    dest_dir: str
    filename: str | None
    ts: int

def add_download(video: Video, dest_dir: Path, filename: str | None) -> None:
    _DL.parent.mkdir(parents=True, exist_ok=True)
    e = DownloadEntry(
        id=video.id,
        title=video.title,
        url=video.url,
        channel=video.channel,
        duration=video.duration,
        thumb_url=video.thumb_url,
        kind=video.kind,
        dest_dir=str(dest_dir),
        filename=filename,
        ts=int(time.time()),
    )
    with _DL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(e), ensure_ascii=False) + "\n")

def list_downloads(limit: int = 300) -> list[Video]:
    if not _DL.exists():
        return []
    out: list[Video] = []
    lines = _DL.read_text(encoding="utf-8").splitlines()
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
                    kind=str(it.get("kind") or "video"),
                )
            )
            if len(out) >= limit:
                break
        except Exception:
            continue
    return out
