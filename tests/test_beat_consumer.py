"""M1.8 Stage B consumer 2: beat segment ends from speech map.

Tests are synthetic and hermetic.
"""
from __future__ import annotations

import pytest

from autoreels.core.models import Segment
from autoreels.local.render import _beat_segs_from_smap


def _make_smap(words: list[dict], boundaries: list[dict]) -> dict:
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


def _w(t0: float, t1: float, ae: float | None = None) -> dict:
    return {"t0": t0, "t1": t1, "ae": ae if ae is not None else t1}


def _bnd(pause: float, untr: list | None = None) -> dict:
    return {"pause": pause, "untranscribed_speech": untr or []}


def _seg(start: float, end: float) -> Segment:
    return Segment(start=start, end=end)


# ── no gap (adjacent beat or last beat) ──────────────────────────────────────

def test_beat_end_moves_to_audible_end():
    """Segment end = Whisper t1 (no gap) → replaced by audible_end."""
    # word: t0=5.0, t1=5.9, ae=5.7; seg.end=5.9; expected new_end≈5.7
    smap = _make_smap([_w(5.0, 5.9, ae=5.7), _w(7.0, 7.5)], [_bnd(1.0)])
    result = _beat_segs_from_smap([_seg(5.0, 5.9)], smap, beat_gap_sec=0.25)
    assert result[0].end == pytest.approx(5.7, abs=0.02)


def test_beat_end_not_earlier_than_ae():
    """new_end is always >= audible_end."""
    smap = _make_smap([_w(5.0, 5.9, ae=5.7)], [])
    result = _beat_segs_from_smap([_seg(5.0, 5.9)], smap, beat_gap_sec=0.25)
    assert result[0].end >= 5.7


# ── gap preserved (non-adjacent beat) ────────────────────────────────────────

def test_beat_gap_shifted_from_t1_to_ae():
    """Non-adjacent beat: gap delta preserved, shifted from t1 to audible_end."""
    # word: t1=5.9, ae=5.7; seg.end=6.15 (t1+0.25); delta=0.25
    # expected: 5.7 + 0.25 = 5.95
    smap = _make_smap([_w(5.0, 5.9, ae=5.7), _w(7.0, 7.5)], [_bnd(1.0)])
    result = _beat_segs_from_smap([_seg(5.0, 6.15)], smap, beat_gap_sec=0.25)
    assert result[0].end == pytest.approx(5.95, abs=0.02)


# ── cap at next source speech ─────────────────────────────────────────────────

def test_beat_capped_at_next_word_audible_start():
    """new_end capped below next word's audible_start.

    The next word's audible_start starts early (before its Whisper t0).
    seg.end < next_src.t0 (realistic — apply already capped there).
    ae + delta > next_word_audible_start − margin → cap fires.
    """
    # last word: t0=5.0, t1=5.4, ae=5.2; gap adds 0.5 → seg.end=5.9
    # next word: t0=6.0, audible_start=5.7 (early onset, "as" key)
    # delta = 5.9 - 5.4 = 0.5; raw new_end = 5.2 + 0.5 = 5.7
    # next_onset = 5.7; cap = 5.7 - 0.04 = 5.66 → 5.7 > 5.66 → capped
    smap = _make_smap(
        [{"t0": 5.0, "t1": 5.4, "ae": 5.2},
         {"t0": 6.0, "t1": 6.5, "ae": 6.4, "as": 5.7}],
        [_bnd(0.3)],
    )
    result = _beat_segs_from_smap([_seg(5.0, 5.9)], smap, beat_gap_sec=0.25)
    assert result[0].end < 5.7  # strictly below next word's audible_start
    assert result[0].end >= 5.2  # at least past ae


def test_beat_capped_at_untr_onset():
    """Untranscribed speech onset used as cap when closer than next word."""
    # ae=5.7; untr at [6.1, 6.4]; next word as=7.0
    # raw new_end = 5.7+0.25 = 5.95; untr_onset=6.1; cap = 6.1-0.04 = 6.06 > 5.95 → no change
    # → test with shorter gap to need the cap: seg.end=6.5 → delta=0.6; raw=6.3 → capped at 6.06
    smap = _make_smap(
        [_w(5.0, 5.9, ae=5.7), _w(7.0, 7.5)],
        [_bnd(0.7, untr=[[6.1, 6.4]])],
    )
    result = _beat_segs_from_smap([_seg(5.0, 6.5)], smap, beat_gap_sec=0.25)
    assert result[0].end < 6.1
    assert result[0].end >= 5.7


def test_beat_untr_closer_than_next_word_used_as_cap():
    """When untr onset < next word audible_start, untr wins."""
    # ae=5.7; next word as=7.0; untr at [6.0, 6.2]
    # raw new_end = 5.7+0.5 = 6.2; untr_onset=6.0 < 7.0 → cap at 6.0-0.04=5.96
    smap = _make_smap(
        [_w(5.0, 5.9, ae=5.7), _w(7.0, 7.5)],
        [_bnd(0.7, untr=[[6.0, 6.2]])],
    )
    result = _beat_segs_from_smap([_seg(5.0, 6.2)], smap, beat_gap_sec=0.25)
    assert result[0].end < 6.0
    assert result[0].end >= 5.7


# ── edge cases ────────────────────────────────────────────────────────────────

def test_beat_no_smap_word_in_seg_unchanged():
    """Segment with no smap words at or before seg.end → unchanged."""
    smap = _make_smap([_w(1.0, 1.5)], [])
    result = _beat_segs_from_smap([_seg(5.0, 9.0)], smap, beat_gap_sec=0.25)
    assert result[0].end == pytest.approx(9.0)


def test_beat_multiple_segs_each_adjusted():
    """Non-adjacent segments (gap 2.2s > _ADJACENT_MAX_GAP=2.0) both use audible_end."""
    # seg0: word at t0=2.0, t1=2.8, ae=2.6; seg.end=2.8 → new_end=2.6 (non-adjacent: gap=2.2s)
    # seg1: word at t0=5.0, t1=5.9, ae=5.7; seg.end=6.15 (gap 0.25) → new_end=5.95 (last)
    smap = _make_smap(
        [_w(2.0, 2.8, ae=2.6), _w(5.0, 5.9, ae=5.7), _w(8.0, 8.5)],
        [_bnd(0.5), _bnd(1.0)],
    )
    segs = [_seg(2.0, 2.8), _seg(5.0, 6.15)]
    result = _beat_segs_from_smap(segs, smap, beat_gap_sec=0.25)
    assert result[0].end == pytest.approx(2.6, abs=0.02)
    assert result[1].end == pytest.approx(5.95, abs=0.02)


# ── adjacent join: natural source pause preserved ────────────────────────────

def test_beat_adjacent_extends_to_next_start():
    """Adjacent join (gap 0.02s): seg.end extended to next_seg.start."""
    smap = _make_smap([_w(5.0, 5.9, ae=5.7), _w(7.0, 7.5)], [_bnd(1.0)])
    # beat2.end=5.9, beat3.start=5.92 → gap=0.02 → adjacent → end=5.92
    segs = [_seg(5.0, 5.9), _seg(5.92, 7.0)]
    result = _beat_segs_from_smap(segs, smap, beat_gap_sec=0.25)
    assert result[0].end == pytest.approx(5.92)


def test_beat_adjacent_larger_gap_preserved():
    """Adjacent join (gap 0.84s < 2.0s): source pause preserved."""
    smap = _make_smap([_w(5.0, 5.9, ae=5.7), _w(8.0, 8.5)], [_bnd(1.0)])
    # beat2.end=5.9, beat3.start=6.74 → gap=0.84 → adjacent → end=6.74
    segs = [_seg(5.0, 5.9), _seg(6.74, 8.0)]
    result = _beat_segs_from_smap(segs, smap, beat_gap_sec=0.25)
    assert result[0].end == pytest.approx(6.74)


def test_beat_nonadjacent_backward_uses_audible_end():
    """Non-adjacent (backward jump in source): audible_end cap applies."""
    smap = _make_smap([_w(5.0, 5.9, ae=5.7), _w(7.0, 7.5)], [_bnd(1.0)])
    # beat1.end=5.9, beat2.start=2.0 → gap=-3.9s → non-adjacent → audible_end
    segs = [_seg(5.0, 5.9), _seg(2.0, 3.0)]
    result = _beat_segs_from_smap(segs, smap, beat_gap_sec=0.25)
    assert result[0].end == pytest.approx(5.7, abs=0.02)  # audible_end


def test_beat_adjacent_last_seg_uses_audible_end():
    """Last segment is never adjacent — audible_end cap applies."""
    smap = _make_smap([_w(5.92, 7.0, ae=6.9), _w(8.0, 8.5)], [_bnd(1.0)])
    segs = [_seg(5.0, 5.9), _seg(5.92, 7.0)]
    result = _beat_segs_from_smap(segs, smap, beat_gap_sec=0.25)
    # seg[0] is adjacent → end=5.92; seg[1] is last → audible_end
    assert result[0].end == pytest.approx(5.92)
    assert result[1].end == pytest.approx(6.9, abs=0.02)
