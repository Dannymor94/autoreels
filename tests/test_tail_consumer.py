"""M1.8 Stage B consumer 1: tail placement from speech map.

Tests are synthetic and hermetic — no real sources, no fixtures in git.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_smap(words: list[dict], boundaries: list[dict]) -> dict:
    """Minimal smap dict for tests."""
    return {
        "version": "4",
        "words": [
            {"idx": i, "t0": w["t0"], "t1": w["t1"],
             "audible_start": w.get("as", w["t0"]),
             "audible_end": w.get("ae", w["t1"])}
            for i, w in enumerate(words)
        ],
        "boundaries": boundaries,
        "intervals": [],
    }


def _make_word(t0: float, t1: float, ae: float | None = None) -> dict:
    return {"t0": t0, "t1": t1, "ae": ae if ae is not None else t1}


def _make_boundary(pause: float, untr: list[list[float]] | None = None) -> dict:
    return {"pause": pause, "untranscribed_speech": untr or []}


# ── import the consumer helper ────────────────────────────────────────────────

from autoreels.local.render import _tail_from_smap, _smap_word_lookup


# ── basic lookup ─────────────────────────────────────────────────────────────

def test_smap_word_lookup_by_t0():
    smap = _make_smap(
        [_make_word(0.0, 1.0, ae=0.9), _make_word(1.5, 2.5, ae=2.4)],
        [_make_boundary(0.6)],
    )
    lookup = _smap_word_lookup(smap)
    # lookup returns (word_idx, word_entry) by t0 key
    idx, entry = lookup[round(0.0, 3)]
    assert idx == 0
    assert entry["audible_end"] == pytest.approx(0.9)


# ── silence case ─────────────────────────────────────────────────────────────

def test_tail_silence_case():
    """Gap >= cut_pause_min_sec → end at audible_end + 0.10."""
    # last word: t0=5.0, ae=5.8; next word: as=6.5 → gap=0.7 >= 0.35
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8), _make_word(6.5, 7.0)],
        [_make_boundary(0.7)],
    )
    lookup = _smap_word_lookup(smap)
    result = _tail_from_smap(
        last_t0=5.0, seg_end=6.0, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35,
    )
    assert result is not None
    # silence case: audible_end + 0.10 = 5.9
    assert result == pytest.approx(5.9, abs=0.01)


def test_tail_silence_case_capped_by_next_onset():
    """Silence case: end is capped below next word audible_start."""
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8), _make_word(5.95, 6.5)],
        [_make_boundary(0.35)],  # exactly at threshold
    )
    lookup = _smap_word_lookup(smap)
    result = _tail_from_smap(
        last_t0=5.0, seg_end=6.0, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35,
    )
    assert result is not None
    # audible_end + 0.10 = 5.9, but must stay < 5.95 (next audible_start)
    assert result < 5.95


# ── speech-next case ─────────────────────────────────────────────────────────

def test_tail_speech_next_case():
    """Gap < cut_pause_min_sec → end strictly before next speech onset."""
    # last word ae=5.8; next word as=5.95 → gap=0.15 < 0.35
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8), _make_word(5.95, 6.5)],
        [_make_boundary(0.15)],
    )
    lookup = _smap_word_lookup(smap)
    result = _tail_from_smap(
        last_t0=5.0, seg_end=6.0, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35,
    )
    assert result is not None
    # speech-next: end < next onset (5.95)
    assert result < 5.95
    # but after last word start
    assert result > 5.0


# ── untranscribed speech in gap ───────────────────────────────────────────────

def test_tail_untranscribed_speech_is_next_onset():
    """Untranscribed speech onset < next word onset → speech-next case triggers."""
    # last word ae=5.8; next word as=7.0 (big gap: 1.2s); but untr speech at [6.0, 6.3]
    # gap to untr onset = 6.0 - 5.8 = 0.2 < 0.35 → speech-next (end before 6.0)
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8), _make_word(7.0, 7.5)],
        [_make_boundary(0.7, untr=[[6.0, 6.3]])],
    )
    lookup = _smap_word_lookup(smap)
    result = _tail_from_smap(
        last_t0=5.0, seg_end=7.5, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35,
    )
    assert result is not None
    # Gap to untr onset = 0.2 < 0.35 → speech-next
    assert result < 6.0
    assert result > 5.0


def test_tail_untr_far_from_ae_silence_case():
    """Untranscribed speech onset far enough → gap >= cut_pause_min_sec → silence case."""
    # last word ae=5.8; untr at [6.2, 6.5] → gap=0.4 >= 0.35 → silence case
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8), _make_word(7.0, 7.5)],
        [_make_boundary(0.7, untr=[[6.2, 6.5]])],
    )
    lookup = _smap_word_lookup(smap)
    result = _tail_from_smap(
        last_t0=5.0, seg_end=7.5, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35,
    )
    assert result is not None
    # silence case: audible_end + pad = ~5.9; capped below untr onset 6.2
    assert result == pytest.approx(5.9, abs=0.02)


# ── last word of transcript ───────────────────────────────────────────────────

def test_tail_last_word_of_transcript():
    """Last word has no next word → silence case with no onset cap."""
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8)],
        [],  # no boundaries
    )
    lookup = _smap_word_lookup(smap)
    result = _tail_from_smap(
        last_t0=5.0, seg_end=6.0, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35,
    )
    # No next speech → silence case: audible_end + 0.10
    assert result == pytest.approx(5.9, abs=0.02)


# ── word not found → None ─────────────────────────────────────────────────────

def test_tail_word_not_in_smap_returns_none():
    """Word with t0 not in smap → return None (fall back to silencedetect)."""
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8), _make_word(6.5, 7.0)],
        [_make_boundary(0.7)],
    )
    lookup = _smap_word_lookup(smap)
    result = _tail_from_smap(
        last_t0=99.0,  # not in map
        seg_end=6.0, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35,
    )
    assert result is None


# ── map-always-applies ────────────────────────────────────────────────────────

def test_tail_map_applies_even_when_seg_end_far():
    """Map path always applies — no window guard (map is better than silencedetect)."""
    # last word ae=5.8; next word as=6.5 → gap=0.7 >= 0.35 → silence case → end ≈ 5.9
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8), _make_word(6.5, 7.0)],
        [_make_boundary(0.7)],
    )
    lookup = _smap_word_lookup(smap)
    # Even with seg_end=10.0 (far beyond last word), map gives the right tail
    result = _tail_from_smap(
        last_t0=5.0, seg_end=10.0, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35,
    )
    assert result is not None
    # silence case: audible_end + pad = ~5.9
    assert result == pytest.approx(5.9, abs=0.02)


# ── residue attribution ───────────────────────────────────────────────────────

def test_tail_residue_adjacent_word_attributed_to_last():
    """Smap word whose Whisper t0 == last_word.t1 is residue — merged, not treated as next speech."""
    # last word: t0=5.0, t1=5.5, ae=5.6; residue: t0=5.5 (== t1), ae=5.8; real next: as=7.2
    # Without attribution: gap=7.2-5.6=1.6 → silence (fine). But without residue loop:
    # next audible_start = residue.as (somewhere near 5.5) → gap tiny → speech-next (wrong).
    smap = _make_smap(
        [_make_word(5.0, 5.5, ae=5.6), _make_word(5.5, 5.9, ae=5.8), _make_word(7.2, 7.7)],
        [_make_boundary(0.0), _make_boundary(1.4)],
    )
    # Residue word needs audible_start set close to last word's ae to trigger the bug without fix
    smap["words"][1]["audible_start"] = 5.62  # gap = 5.62 - 5.60 = 0.02 < 0.35 → speech-next without fix
    lookup = _smap_word_lookup(smap)
    result = _tail_from_smap(
        last_t0=5.0, seg_end=8.0, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35, last_t1=5.5,
    )
    assert result is not None
    # After residue attribution: audible_end=5.8, next real onset=7.2 → silence → end ≈ 5.9
    assert result == pytest.approx(5.9, abs=0.02)
    assert result > 5.5  # NOT speech-next (which would cut to ~5.42)
