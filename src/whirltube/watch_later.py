"""Watch Later queue management."""
from __future__ import annotations

import json
import logging
import time

from .models import Video
from .util import xdg_data_dir

log = logging.getLogger(__name__)

_WATCH_LATER = xdg_data_dir() / "watch_later.jsonl"


def add_to_watch_later(video: Video) -> bool:
    """
    Add video to watch later queue.
    
    Args:
        video: Video to add
        
    Returns:
        True if added, False if already exists
    """
    try:
        _WATCH_LATER.parent.mkdir(parents=True, exist_ok=True)
        
        # Check if already exists
        if is_in_watch_later(video.id):
            log.debug(f"Video {video.id} already in watch later")
            return False
        
        data = {
            "id": video.id,
            "title": video.title,
            "url": video.url,
            "channel": video.channel,
            "duration": video.duration,
            "thumb_url": video.thumb_url,
            "kind": video.kind,
            "added": int(time.time()),
        }
        
        with _WATCH_LATER.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
        
        log.info(f"Added to watch later: {video.title}")
        return True
    except Exception as e:
        log.exception(f"Failed to add to watch later: {e}")
        return False


def remove_from_watch_later(video_id: str) -> bool:
    """
    Remove video from watch later queue.
    
    Args:
        video_id: Video ID to remove
        
    Returns:
        True if removed, False if not found
    """
    if not _WATCH_LATER.exists():
        return False
    
    try:
        lines = _WATCH_LATER.read_text(encoding="utf-8").splitlines()
        new_lines = []
        removed = False
        
        for line in lines:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                if data.get("id") != video_id:
                    new_lines.append(line)
                else:
                    removed = True
                    log.info(f"Removed from watch later: {video_id}")
            except json.JSONDecodeError:
                # Keep malformed lines to avoid data loss
                new_lines.append(line)
        
        if removed:
            # Write atomically
            tmp = _WATCH_LATER.with_suffix(".tmp")
            tmp.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
            tmp.replace(_WATCH_LATER)
        
        return removed
    except Exception as e:
        log.exception(f"Failed to remove from watch later: {e}")
        return False


def is_in_watch_later(video_id: str) -> bool:
    """
    Check if video is in watch later queue.
    
    Args:
        video_id: Video ID to check
        
    Returns:
        True if in queue, False otherwise
    """
    if not _WATCH_LATER.exists():
        return False
    
    try:
        for line in _WATCH_LATER.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                if data.get("id") == video_id:
                    return True
            except json.JSONDecodeError:
                continue
    except Exception as e:
        log.debug(f"Error checking watch later status: {e}")
    
    return False


def list_watch_later(limit: int | None = None) -> list[Video]:
    """
    Get all videos in watch later queue.
    
    Args:
        limit: Maximum number of videos to return (None for all)
        
    Returns:
        List of videos, most recently added first
    """
    if not _WATCH_LATER.exists():
        return []
    
    videos = []
    try:
        for line in _WATCH_LATER.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                videos.append(Video(
                    id=str(data.get("id", "")),
                    title=data.get("title", ""),
                    url=data.get("url", ""),
                    channel=data.get("channel"),
                    duration=data.get("duration"),
                    thumb_url=data.get("thumb_url"),
                    kind=data.get("kind", "video"),
                ))
            except Exception as e:
                log.debug(f"Failed to parse watch later entry: {e}")
                continue
    except Exception as e:
        log.exception(f"Failed to list watch later: {e}")
        return []
    
    # Most recent first
    videos.reverse()
    
    if limit is not None and limit > 0:
        videos = videos[:limit]
    
    return videos


def clear_watch_later() -> int:
    """
    Clear all videos from watch later queue.
    
    Returns:
        Number of videos cleared
    """
    if not _WATCH_LATER.exists():
        return 0
    
    try:
        count = len(list_watch_later())
        _WATCH_LATER.unlink()
        log.info(f"Cleared {count} videos from watch later")
        return count
    except Exception as e:
        log.exception(f"Failed to clear watch later: {e}")
        return 0


def get_watch_later_count() -> int:
    """
    Get count of videos in watch later queue.
    
    Returns:
        Number of videos
    """
    if not _WATCH_LATER.exists():
        return 0
    
    try:
        count = 0
        for line in _WATCH_LATER.read_text(encoding="utf-8").splitlines():
            if line.strip():
                count += 1
        return count
    except Exception:
        return 0