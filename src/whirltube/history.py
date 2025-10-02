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


def list_search_history(limit: int = 20) -> list[str]:
    """
    Get recent unique search terms for autocomplete.
    
    Args:
        limit: Maximum number of terms to return
        
    Returns:
        List of search terms, most recent first
    """
    if not SEARCH.exists():
        return []
    
    try:
        lines = SEARCH.read_text(encoding="utf-8").splitlines()
        
        # Extract search terms (skip timestamp)
        terms = []
        seen = set()
        
        # Process in reverse (most recent first)
        for line in reversed(lines):
            if not line.strip():
                continue
            
            # Format: "TIMESTAMP\tQUERY"
            parts = line.split('\t', 1)
            if len(parts) == 2:
                term = parts[1].strip()
                # Only add if we haven't seen it (dedup)
                if term and term not in seen:
                    terms.append(term)
                    seen.add(term)
                    
                    if len(terms) >= limit:
                        break
        
        return terms
        
    except Exception as e:
        from .util import log
        log.debug(f"Failed to list search history: {e}")
        return []


def search_history_suggestions(prefix: str, limit: int = 10) -> list[str]:
    """
    Get search suggestions based on prefix matching.
    
    Args:
        prefix: Search prefix to match
        limit: Maximum suggestions to return
        
    Returns:
        List of matching search terms
    """
    if not prefix or not prefix.strip():
        # Return recent searches if no prefix
        return list_search_history(limit)
    
    prefix_lower = prefix.strip().lower()
    all_terms = list_search_history(limit * 3)  # Get more to filter
    
    # Filter by prefix match
    matches = [term for term in all_terms if term.lower().startswith(prefix_lower)]
    
    return matches[:limit]


def clear_search_history() -> int:
    """
    Clear all search history.
    
    Returns:
        Number of entries cleared
    """
    if not SEARCH.exists():
        return 0
    
    try:
        count = len(SEARCH.read_text(encoding="utf-8").splitlines())
        SEARCH.unlink()
        from .util import log
        log.info(f"Cleared {count} search history entries")
        return count
    except Exception as e:
        from .util import log
        log.exception(f"Failed to clear search history: {e}")
        return 0


def get_search_history_count() -> int:
    """
    Get count of search history entries.
    
    Returns:
        Number of searches
    """
    if not SEARCH.exists():
        return 0
    
    try:
        return len([line for line in SEARCH.read_text(encoding="utf-8").splitlines() if line.strip()])
    except Exception:
        return 0
