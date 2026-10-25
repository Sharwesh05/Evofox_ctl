"""Tiny persistent user settings (last used mouse, refresh interval)."""

from __future__ import annotations

import json
import os
from pathlib import Path


def _path() -> Path:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "ghostx" / "settings.json"


def load() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(**values) -> None:
    try:
        data = load()
        data.update(values)
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass   # settings are a convenience only


def macro_library() -> list[dict]:
    """Saved macros: ``[{"name": str, "macro": {...}}, ...]``."""
    data = load().get("macros", [])
    return [m for m in data if isinstance(m, dict) and "name" in m and "macro" in m]


def save_macro_library(items: list[dict]) -> None:
    save(macros=items)
