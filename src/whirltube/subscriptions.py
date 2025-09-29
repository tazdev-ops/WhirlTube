from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .util import xdg_data_dir

_SUBS_PATH = xdg_data_dir() / "subscriptions.json"

@dataclass(slots=True)
class Subscription:
    url: str
    title: str | None = None

def _load_raw() -> list[dict[str, Any]]:
    if not _SUBS_PATH.exists():
        return []
    try:
        data = json.loads(_SUBS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except Exception:
        pass
    return []

def _save_raw(items: list[dict[str, Any]]) -> None:
    _SUBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _SUBS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
    tmp.replace(_SUBS_PATH)

def list_subscriptions() -> list[Subscription]:
    out: list[Subscription] = []
    for it in _load_raw():
        url = (it.get("url") or "").strip()
        if not url:
            continue
        # normalize trailing /videos to channel root (keep as-is if not a channel)
        if "/channel/" in url and url.endswith("/videos"):
            url = url[:-7]
        title = (it.get("title") or None)
        out.append(Subscription(url=url, title=title))
    return out

def is_followed(url: str) -> bool:
    u = (url or "").strip()
    if not u:
        return False
    for it in _load_raw():
        if (it.get("url") or "").strip() == u:
            return True
    return False

def add_subscription(url: str, title: str | None = None) -> bool:
    u = (url or "").strip()
    if not u:
        return False
    data = _load_raw()
    for it in data:
        if (it.get("url") or "").strip() == u:
            return False  # already present
    data.append({"url": u, "title": title or None})
    _save_raw(data)
    return True

def remove_subscription(url: str) -> bool:
    u = (url or "").strip()
    if not u:
        return False
    data = _load_raw()
    new = [it for it in data if (it.get("url") or "").strip() != u]
    if len(new) == len(data):
        return False
    _save_raw(new)
    return True
def export_subscriptions(dest: Path) -> bool:
    """
    Write current subscriptions to dest as pretty JSON.
    Returns True on success.
    """
    try:
        items = _load_raw()
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
        tmp.replace(dest)
        return True
    except Exception:
        return False

def import_subscriptions(src: Path) -> int:
    """
    Merge subscriptions from src (list of {url, title}) with existing ones.
    Returns number of new entries added.
    """
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return 0
        existing = _load_raw()
        have = { (it.get("url") or "").strip() for it in existing if isinstance(it, dict) }
        added = 0
        for it in data:
            if not isinstance(it, dict):
                continue
            u = (it.get("url") or "").strip()
            if not u or u in have:
                continue
            existing.append({"url": u, "title": (it.get("title") or None)})
            have.add(u)
            added += 1
        if added:
            _save_raw(existing)
        return added
    except Exception:
        return 0
