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
    view_count: int | None = None  # NEW: Number of views
    upload_date: str | None = None  # NEW: Upload date in YYYYMMDD format

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
    def view_count_str(self) -> str:
        """Format view count as human-readable"""
        if not self.view_count:
            return ""
        v = self.view_count
        if v >= 1_000_000:
            return f"{v / 1_000_000:.1f}M views"
        elif v >= 1_000:
            return f"{v / 1_000:.1f}K views"
        return f"{v} views"
    
    @property
    def upload_date_str(self) -> str:
        """Format upload date as human-readable"""
        if not self.upload_date or len(self.upload_date) != 8:
            return ""
        try:
            from datetime import datetime
            dt = datetime.strptime(self.upload_date, "%Y%m%d")
            # Relative time
            now = datetime.now()
            delta = now - dt
            if delta.days == 0:
                return "Today"
            elif delta.days == 1:
                return "Yesterday"
            elif delta.days < 7:
                return f"{delta.days} days ago"
            elif delta.days < 30:
                return f"{delta.days // 7} weeks ago"
            elif delta.days < 365:
                return f"{delta.days // 30} months ago"
            else:
                return f"{delta.days // 365} years ago"
        except Exception:
            return ""

    @property
    def is_playable(self) -> bool:
        return self.kind == "video"
