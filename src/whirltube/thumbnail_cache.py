"""Thumbnail caching system to reduce bandwidth and improve performance."""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Optional

from .util import xdg_cache_dir

log = logging.getLogger(__name__)

CACHE_DIR = xdg_cache_dir() / "thumbnails"
CACHE_MAX_AGE_DAYS = 30  # Clean thumbnails older than 30 days
CACHE_MAX_SIZE_MB = 500  # Maximum cache size in MB


def _ensure_cache_dir() -> None:
    """Ensure cache directory exists"""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.warning(f"Failed to create thumbnail cache directory: {e}")


def _get_cache_path(url: str) -> Path:
    """
    Get cache file path for a thumbnail URL.
    
    Args:
        url: Thumbnail URL
        
    Returns:
        Path to cached file
    """
    # Use MD5 hash of URL as filename
    cache_key = hashlib.md5(url.encode('utf-8')).hexdigest()
    return CACHE_DIR / f"{cache_key}.jpg"


def get_cached_thumbnail(url: str) -> Optional[Path]:
    """
    Get cached thumbnail path if it exists and is valid.
    
    Args:
        url: Thumbnail URL
        
    Returns:
        Path to cached file if valid, None otherwise
    """
    if not url:
        return None
    
    try:
        cache_path = _get_cache_path(url)
        
        if not cache_path.exists():
            return None
        
        # Check file is not empty
        if cache_path.stat().st_size == 0:
            log.debug(f"Cached thumbnail is empty, removing: {cache_path}")
            cache_path.unlink()
            return None
        
        # Check file is not too old (optional freshness check)
        age_days = (time.time() - cache_path.stat().st_mtime) / 86400
        if age_days > CACHE_MAX_AGE_DAYS:
            log.debug(f"Cached thumbnail expired ({age_days:.1f} days old): {cache_path}")
            cache_path.unlink()
            return None
        
        log.debug(f"Thumbnail cache hit: {url[:50]}...")
        return cache_path
        
    except Exception as e:
        log.debug(f"Error checking thumbnail cache: {e}")
        return None


def cache_thumbnail(url: str, data: bytes) -> Optional[Path]:
    """
    Save thumbnail data to cache.
    
    Args:
        url: Thumbnail URL
        data: Thumbnail image data
        
    Returns:
        Path to cached file, or None on failure
    """
    if not url or not data:
        return None
    
    try:
        _ensure_cache_dir()
        cache_path = _get_cache_path(url)
        
        # Write atomically using temporary file
        tmp_path = cache_path.with_suffix('.tmp')
        tmp_path.write_bytes(data)
        tmp_path.replace(cache_path)
        
        log.debug(f"Cached thumbnail ({len(data)} bytes): {url[:50]}...")
        return cache_path
        
    except Exception as e:
        log.warning(f"Failed to cache thumbnail: {e}")
        return None


def get_cache_size() -> int:
    """
    Get total size of thumbnail cache in bytes.
    
    Returns:
        Cache size in bytes
    """
    if not CACHE_DIR.exists():
        return 0
    
    try:
        total = 0
        for path in CACHE_DIR.iterdir():
            if path.is_file():
                total += path.stat().st_size
        return total
    except Exception as e:
        log.debug(f"Error calculating cache size: {e}")
        return 0


def clear_cache() -> int:
    """
    Clear all cached thumbnails.
    
    Returns:
        Number of files removed
    """
    if not CACHE_DIR.exists():
        return 0
    
    try:
        count = 0
        for path in CACHE_DIR.iterdir():
            if path.is_file():
                path.unlink()
                count += 1
        log.info(f"Cleared {count} cached thumbnails")
        return count
    except Exception as e:
        log.error(f"Failed to clear cache: {e}")
        return 0


def cleanup_old_cache() -> int:
    """
    Remove thumbnails older than CACHE_MAX_AGE_DAYS.
    
    Returns:
        Number of files removed
    """
    if not CACHE_DIR.exists():
        return 0
    
    try:
        count = 0
        cutoff = time.time() - (CACHE_MAX_AGE_DAYS * 86400)
        
        for path in CACHE_DIR.iterdir():
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                count += 1
        
        if count > 0:
            log.info(f"Cleaned up {count} old cached thumbnails")
        return count
    except Exception as e:
        log.error(f"Failed to cleanup old cache: {e}")
        return 0


def enforce_cache_size_limit() -> int:
    """
    Remove oldest thumbnails if cache exceeds size limit.
    
    Returns:
        Number of files removed
    """
    if not CACHE_DIR.exists():
        return 0
    
    try:
        max_bytes = CACHE_MAX_SIZE_MB * 1024 * 1024
        current_size = get_cache_size()
        
        if current_size <= max_bytes:
            return 0
        
        # Get all files sorted by modification time (oldest first)
        files = []
        for path in CACHE_DIR.iterdir():
            if path.is_file():
                files.append((path.stat().st_mtime, path.stat().st_size, path))
        
        files.sort()
        
        # Remove oldest files until under limit
        count = 0
        for mtime, size, path in files:
            if current_size <= max_bytes:
                break
            path.unlink()
            current_size -= size
            count += 1
        
        if count > 0:
            log.info(f"Removed {count} thumbnails to enforce size limit")
        return count
        
    except Exception as e:
        log.error(f"Failed to enforce cache size limit: {e}")
        return 0


def get_cache_stats() -> dict[str, any]:
    """
    Get statistics about the thumbnail cache.
    
    Returns:
        Dictionary with cache statistics
    """
    if not CACHE_DIR.exists():
        return {
            'file_count': 0,
            'total_size_bytes': 0,
            'total_size_mb': 0.0,
            'oldest_file_age_days': 0.0,
        }
    
    try:
        files = list(CACHE_DIR.iterdir())
        file_count = len([f for f in files if f.is_file()])
        total_size = get_cache_size()
        
        oldest_age = 0.0
        if file_count > 0:
            oldest_mtime = min(f.stat().st_mtime for f in files if f.is_file())
            oldest_age = (time.time() - oldest_mtime) / 86400
        
        return {
            'file_count': file_count,
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'oldest_file_age_days': round(oldest_age, 1),
        }
    except Exception as e:
        log.debug(f"Error getting cache stats: {e}")
        return {
            'file_count': 0,
            'total_size_bytes': 0,
            'total_size_mb': 0.0,
            'oldest_file_age_days': 0.0,
        }