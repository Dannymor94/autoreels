"""Read-only facts from manifests, ONLY through the Pydantic models (UI-HANDOFF §8).

A manifest that does not validate is ignored (UI shows less, never crashes).
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

_cache: dict[tuple[str, int], dict[str, str]] = {}


def reel_titles(root: Path, stem: str) -> dict[str, str]:
    """clip id (r01) → title for display: the title plate (title_overlay) if set, else reel.title."""
    path = root / "manifests" / f"{stem}.json"
    if not path.is_file():
        return {}
    key = (str(path), path.stat().st_mtime_ns)
    if key in _cache:
        return _cache[key]
    try:
        from autoreels.core.models import Manifest  # the shared contract — models only

        m = Manifest.model_validate_json(path.read_bytes())
    except Exception as exc:  # validation or IO: show less, never crash
        log.warning("manifest %s not readable: %s", path.name, exc)
        _cache[key] = {}
        return {}
    titles = {r.id: (r.title_overlay or r.title or "").strip() for r in m.reels}
    _cache[key] = {k: v for k, v in titles.items() if v}
    return _cache[key]
