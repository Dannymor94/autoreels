"""Owner-given display names for sources. Folder names on disk never change.

Stored in <root>/reviews/ui/sources.json — reviews/ is the only place the UI writes owner data.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

SCHEMA_VERSION = 1
MAX_NAME = 120


def _path(root: Path) -> Path:
    return root / "reviews" / "ui" / "sources.json"


def load(root: Path) -> dict[str, dict]:
    p = _path(root)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data.get("sources", {}) if isinstance(data, dict) else {}


def display_name(root: Path, stem: str) -> str | None:
    return load(root).get(stem, {}).get("display_name")


def set_display_name(root: Path, stem: str, name: str | None) -> str | None:
    """Set (or with None/blank: remove) the display name. Atomic write. Returns the stored value."""
    clean = (name or "").strip()[:MAX_NAME] or None
    sources = load(root)
    if clean is None:
        sources.pop(stem, None)
    else:
        sources[stem] = {**sources.get(stem, {}), "display_name": clean}
    p = _path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=p.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"schema_version": SCHEMA_VERSION, "sources": sources}, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, p)
    return clean
