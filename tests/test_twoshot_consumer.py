"""M1.8 Stage B consumer 3: two_shot_auto level-1 candidates from speech map.

Tests _find_pause_boundary with smap parameter.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


def _w(word: str, t0: float, t1: float) -> SimpleNamespace:
    return SimpleNamespace(word=word, t0=t0, t1=t1)


def _make_smap_lookup(words_t0: list[float], pauses: list[float]) -> tuple[dict, dict]:
    """Returns (smap, lookup) with one boundary per word."""
    words = [{"idx": i, "t0": t, "t1": t + 0.3, "audible_start": t, "audible_end": t + 0.28}
             for i, t in enumerate(words_t0)]
    boundaries = [{"pause": p, "untranscribed_speech": []} for p in pauses]
    smap = {"version": "4", "words": words, "boundaries": boundaries, "intervals": []}
    lookup = {round(w["t0"] * 1000): (i, w) for i, w in enumerate(words)}
    return smap, lookup


# Import target
from autoreels.__main__ import _find_pause_boundary


# ── level-1 with Whisper gaps (baseline, smap=None) ──────────────────────────

def test_level1_uses_whisper_gap_when_no_smap():
    """Without smap: level-1 = sentence boundary with Whisper gap >= min_pause."""
    # Two sentences: s1 ends at t1=1.0, s2 starts at t0=1.4 → gap=0.4 >= 0.3 → Level 1
    words = [_w("Привет.", 0.0, 1.0), _w("Мир.", 1.4, 2.0)]
    result = _find_pause_boundary(words, 0.0, 2.0, target=1.0, min_pause=0.3,
                                  search_start=0.5, search_end=1.5)
    assert result is not None
    sw, level, pause_val = result
    assert "pause" in level or level == "pause≥0.3s"
    assert pause_val >= 0.3


def test_level1_falls_to_level2_when_gap_too_small():
    """Whisper gap < min_pause → Level 1 misses, falls back to Level 2 (sentence, no pause req)."""
    # Gap = 0.1 < 0.3
    words = [_w("Привет.", 0.0, 1.0), _w("Мир.", 1.1, 2.0)]
    result = _find_pause_boundary(words, 0.0, 2.0, target=1.0, min_pause=0.3,
                                  search_start=0.5, search_end=1.5)
    assert result is not None
    sw, level, pause_val = result
    assert level == "sentence"  # Level 2, not Level 1


# ── level-1 with map pauses ───────────────────────────────────────────────────

def test_level1_uses_map_pause_when_smap_provided():
    """With smap: level-1 uses map pause, not Whisper gap."""
    # Whisper gap = 0.05 (tiny — would miss Level 1 without smap)
    # Map pause at boundary after word[0] = 0.5 (large) → Level 1 fires
    words = [_w("Привет.", 0.0, 1.0), _w("Мир.", 1.05, 2.0)]
    smap, lookup = _make_smap_lookup([0.0, 1.05], [0.50, 0.0])
    result = _find_pause_boundary(words, 0.0, 2.0, target=1.0, min_pause=0.3,
                                  search_start=0.5, search_end=1.5, smap=smap)
    assert result is not None
    sw, level, pause_val = result
    # map pause = 0.5 >= 0.3 → Level 1
    assert "pause" in level
    assert abs(pause_val - 0.5) < 0.01


def test_level1_map_pause_below_threshold_falls_to_level2():
    """Map pause < cut_pause_min_sec → not Level 1, falls to Level 2."""
    # Whisper gap = 0.5 (large — would be Level 1 without smap)
    # Map pause = 0.1 (small) → should fall through to Level 2
    words = [_w("Привет.", 0.0, 1.0), _w("Мир.", 1.5, 2.0)]
    smap, lookup = _make_smap_lookup([0.0, 1.5], [0.10, 0.0])
    result = _find_pause_boundary(words, 0.0, 2.0, target=1.0, min_pause=0.3,
                                  search_start=0.5, search_end=1.5, smap=smap)
    assert result is not None
    sw, level, pause_val = result
    # map pause = 0.1 < 0.3 → misses Level 1, gets Level 2
    assert level == "sentence"


def test_smap_none_behavior_unchanged():
    """smap=None (default) → same as no smap (backward compatible)."""
    words = [_w("Привет.", 0.0, 1.0), _w("Мир.", 1.4, 2.0)]
    r_no_smap = _find_pause_boundary(words, 0.0, 2.0, target=1.0, min_pause=0.3,
                                     search_start=0.5, search_end=1.5)
    r_smap_none = _find_pause_boundary(words, 0.0, 2.0, target=1.0, min_pause=0.3,
                                       search_start=0.5, search_end=1.5, smap=None)
    # Both return (sw, level, pause_val); should be identical.
    assert r_no_smap == r_smap_none
