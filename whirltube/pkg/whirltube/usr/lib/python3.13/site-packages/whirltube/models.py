from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Video:
    id: str
    title: str
    url: str
    channel: str | None
    duration: int | None  # seconds
    thumb_url: str | None
    kind: str = "video"  # video|playlist|channel|comment

    @property
    def duration_str(self) -> str:
        if not self.duration or self.duration <= 0:
            return ""
        s = self.duration
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        if h:
            return f"{h:d}:{m:02d}:{sec:02d}"
        return f"{m:d}:{sec:02d}"

    @property
    def is_playable(self) -> bool:
        return self.kind == "video"
