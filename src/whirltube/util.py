from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

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
