from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

APP_NAME = "whirltube"

def xdg_config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p

def xdg_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p

def xdg_data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p

def settings_path() -> Path:
    return xdg_config_dir() / "settings.json"

def load_settings() -> dict[str, Any]:
    p = settings_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_settings(data: dict[str, Any]) -> None:
    p = settings_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(p)

def safe_httpx_proxy(val: str | None) -> str | None:
    """
    Validate a proxy string for httpx. Returns a usable proxy string or None.
    Accepts schemes: http, https, socks4, socks5, socks5h.
    """
    if not val:
        return None
    s = val.strip()
    try:
        u = urlparse(s)
    except Exception:
        return None
    scheme = (u.scheme or "").lower()
    if scheme in {"http", "https", "socks4", "socks5", "socks5h"} and (u.netloc or u.path):
        return s
    return None

def is_valid_youtube_url(url: str, allowed_hosts: Iterable[str] | None = None) -> bool:
    """
    Return True if the URL is http(s) and points to YouTube/YouTu.be or an explicitly
    allowed host (e.g., an Invidious instance). This is a light validation to help
    users avoid pasting arbitrary or unsupported URLs into "Open URL…".
    """
    if not url or not isinstance(url, str):
        return False
    try:
        u = urlparse(url.strip())
    except Exception:
        return False
    if (u.scheme or "").lower() not in {"http", "https"}:
        return False
    host = (u.hostname or "").lower().strip()
    if not host:
        return False
    # Core YouTube hosts
    if host.endswith("youtube.com") or host == "youtu.be" or host.endswith("youtube-nocookie.com"):
        return True
    # Extra allowed hosts (e.g., Invidious)
    if allowed_hosts:
        suffixes = [h.lower().strip() for h in allowed_hosts if isinstance(h, str) and h.strip()]
        for suf in suffixes:
            # accept exact or subdomain match
            if host == suf or host.endswith("." + suf):
                return True
    return False
    return False
