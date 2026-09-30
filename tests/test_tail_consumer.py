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


def test_tail_speech_next_zero_gap():
    """Gap = 0 (ae == next audible_start) → end at onset, never past it (PXL r08 case)."""
    # last word ae=5.8; next word audible_start=5.8 → gap=0 < 0.35 → speech-next
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8), _make_word(5.8, 7.0)],
        [_make_boundary(0.0)],
    )
    lookup = _smap_word_lookup(smap)
    result = _tail_from_smap(
        last_t0=5.0, seg_end=7.0, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35,
    )
    assert result is not None
    assert result <= 5.8, f"end {result:.4f} overshoots onset 5.8"
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


# ── invariant: new_end >= audible_end ─────────────────────────────────────────

def test_tail_new_end_never_before_audible_end():
    """Invariant holds: new_end >= audible_end after residue attribution."""
    # residue attributed → audible_end = max(5.8, 6.0) = 6.0; last real word → silence
    smap = _make_smap(
        [_make_word(5.0, 5.5, ae=5.8), _make_word(5.5, 6.0, ae=6.0)],
        [_make_boundary(0.0)],
    )
    lookup = _smap_word_lookup(smap)
    result = _tail_from_smap(
        last_t0=5.0, seg_end=7.0, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35, last_t1=5.5,
    )
    assert result is not None
    assert result >= 5.8  # >= original audible_end; actual ≈ 6.1 (6.0 + _TAIL_PAD)


# ── PART 3: deflate-capped tail_last_word_end ─────────────────────────────────

def test_apply_tail_air_deflate_sets_tail_last_word_end():
    """Deflate cap: last word that fully fits before the cap gets its t1 stored."""
    from autoreels.__main__ import _apply_tail_air
    from autoreels.core.models import Reel, Segment, Word

    def _w(t0, t1, word="x"):
        return Word(word=word, t0=t0, t1=t1)

    # Scenario: clip ends at 10.0 (deflate cap).
    # "keep_word" fits fully (t1=9.5 < 10.0); "overflow_word" starts at 9.6 but t1=10.4 overshoots.
    words = [
        _w(8.0, 9.5, "keep_word"),
        _w(9.6, 10.4, "overflow_word"),   # t1 overshoots cap
        _w(10.1, 11.0, "next_sent"),      # first word after cap
    ]
    r = Reel(id="r01", start=0.0, end=10.0, score=80, hook="h",
             title="t", description="d",
             segments=[Segment(start=0.0, end=10.0)], subtitles=[])
    r._deflate_end_cap = 10.0

    _apply_tail_air([r], words, tail_pad_sec=1.5, video_duration=None)

    assert r.tail_last_word_end == pytest.approx(9.5), (
        f"expected t1 of last fully-fit word (9.5), got {r.tail_last_word_end}"
    )


def test_apply_tail_air_deflate_tail_last_word_end_none_when_no_word_fits():
    """Deflate cap: no word finishes before the cap → tail_last_word_end stays None."""
    from autoreels.__main__ import _apply_tail_air
    from autoreels.core.models import Reel, Segment, Word

    def _w(t0, t1, word="x"):
        return Word(word=word, t0=t0, t1=t1)

    # All words that start before cap (10.0) have t1 > 10.0 → none fit fully
    words = [
        _w(9.0, 11.0, "overflow"),
        _w(10.2, 12.0, "next"),
    ]
    r = Reel(id="r01", start=0.0, end=10.0, score=80, hook="h",
             title="t", description="d",
             segments=[Segment(start=0.0, end=10.0)], subtitles=[])
    r._deflate_end_cap = 10.0

    _apply_tail_air([r], words, tail_pad_sec=1.5, video_duration=None)

    assert r.tail_last_word_end is None


def test_apply_tail_air_explicit_e_caps_from_next_speech_t0():
    """PART 2: explicit_e without _deflate_end_cap; cap from _next_speech_t0 in _apply_tail_air.

    Scenario: "last?" Whisper t1=10.0 (inflated), smap ae=9.74, next speech t0=9.78.
    Cap = 9.78 - _DEFLATE_CAP_MARGIN = 9.76 > ae=9.74 → word fits → lw_end = smap ae.
    """
    from autoreels.__main__ import _apply_tail_air, _DEFLATE_CAP_MARGIN
    from autoreels.core.models import Reel, Segment, Word

    def _w(t0, t1, word="x"):
        return Word(word=word, t0=t0, t1=t1)

    words = [_w(9.0, 9.4, "prev"), _w(9.5, 10.0, "last?"), _w(9.78, 10.5, "next")]
    smap_lookup = {round(9.5 * 1000): (1, {"audible_end": 9.74})}
    r = Reel(id="r01", start=0.0, end=9.76, score=80, hook="h",
             title="t", description="d",
             segments=[Segment(start=0.0, end=9.76)], subtitles=[])
    r.has_explicit_e = True
    r._next_speech_t0 = 9.78  # set by _move_reel_end_to_sentence in deflate step 1

    _apply_tail_air([r], words, tail_pad_sec=1.5, video_duration=None,
                    smap_lookup=smap_lookup)

    assert r.tail_last_word_end == pytest.approx(9.74), (
        f"expected smap ae of 'last?' (9.74), got {r.tail_last_word_end}"
    )
    assert r.end == pytest.approx(9.78 - _DEFLATE_CAP_MARGIN)


def test_apply_tail_air_normal_smap_ae_overrides_whisper_t1():
    """Non-deflate path: smap audible_end > Whisper t1 → lw_end and desired both bump to ae."""
    from autoreels.__main__ import _apply_tail_air
    from autoreels.core.models import Reel, Segment, Word

    def _w(t0, t1, word="x"):
        return Word(word=word, t0=t0, t1=t1)

    # "last_word": Whisper t1=9.540, smap ae=9.600.
    words = [_w(8.0, 9.0, "prev"), _w(9.0, 9.54, "last")]
    smap_lookup = {round(9.0 * 1000): (1, {"audible_end": 9.6})}
    r = Reel(id="r01", start=0.0, end=12.0, score=80, hook="h",
             title="t", description="d",
             segments=[Segment(start=0.0, end=12.0)], subtitles=[])

    _apply_tail_air([r], words, tail_pad_sec=1.5, video_duration=None,
                    smap_lookup=smap_lookup)

    assert r.tail_last_word_end == pytest.approx(9.6), (
        f"expected smap ae (9.6), got {r.tail_last_word_end}"
    )
    assert r.end == pytest.approx(9.6 + 1.5), f"expected end=11.1, got {r.end}"


def test_apply_tail_air_deflate_smap_ae_overrides_whisper_t1():
    """Word with inflated Whisper t1 > cap but smap audible_end ≤ cap is kept; lw_end = smap ae."""
    from autoreels.__main__ import _apply_tail_air
    from autoreels.core.models import Reel, Segment, Word

    def _w(t0, t1, word="x"):
        return Word(word=word, t0=t0, t1=t1)

    # "last_word": Whisper t1=11.0 overshoots cap=10.5, but smap ae=10.4 fits.
    # Without smap it would be excluded and "prev_word" (t1=9.5) would be picked.
    words = [
        _w(8.0, 9.5, "prev_word"),
        _w(9.5, 11.0, "last_word"),   # Whisper t1 overshoots cap; smap ae fits
        _w(10.6, 12.0, "next_sent"),
    ]
    smap_lookup = {
        round(9.5 * 1000): (1, {"audible_end": 10.4}),  # ae ≤ cap 10.5
    }
    r = Reel(id="r01", start=0.0, end=10.5, score=80, hook="h",
             title="t", description="d",
             segments=[Segment(start=0.0, end=10.5)], subtitles=[])
    r._deflate_end_cap = 10.5

    _apply_tail_air([r], words, tail_pad_sec=1.5, video_duration=None,
                    smap_lookup=smap_lookup)

    assert r.tail_last_word_end == pytest.approx(10.4), (
        f"expected smap ae of last_word (10.4), got {r.tail_last_word_end}"
    )


# ── _check_fade_audible ───────────────────────────────────────────────────────

def test_check_fade_audible_violation():
    """PART 4: reports [CONTENT] when lw_end < ae and ae <= r.end."""
    from autoreels.__main__ import _check_fade_audible
    from autoreels.core.models import Reel, Segment, Word

    r = Reel(id="r01", start=0.0, end=10.0, score=80, hook="h",
             title="t", description="d",
             segments=[Segment(start=0.0, end=10.0)],
             subtitles=[Word(word="last", t0=9.0, t1=9.5)])
    r.tail_last_word_end = 9.2
    smap_lookup = {round(9.0 * 1000): (0, {"audible_end": 9.6})}  # ae=9.6 <= r.end=10.0
    errs, warns = _check_fade_audible([r], smap_lookup=smap_lookup)
    assert len(errs) == 1
    assert "[CONTENT]" in errs[0] and "r01" in errs[0]
    assert warns == []


def test_check_fade_audible_clip_cut_auto_is_error():
    """PART 2: auto-path reel with ae > r.end → error (not skip)."""
    from autoreels.__main__ import _check_fade_audible
    from autoreels.core.models import Reel, Segment, Word

    r = Reel(id="r03", start=0.0, end=9.5, score=80, hook="h",
             title="t", description="d",
             segments=[Segment(start=0.0, end=9.5)],
             subtitles=[Word(word="end_word", t0=9.0, t1=9.8)])
    r.tail_last_word_end = 9.1
    r.has_explicit_e = False
    smap_lookup = {round(9.0 * 1000): (0, {"audible_end": 9.7})}  # ae=9.7 > r.end=9.5
    errs, warns = _check_fade_audible([r], smap_lookup=smap_lookup)
    assert len(errs) == 1, "auto-path clip-cut must be an error"
    assert "clip end" in errs[0]
    assert warns == []


def test_check_fade_audible_clip_cut_explicit_e_is_warning():
    """PART 2: explicit_e reel with ae > r.end → warning in reel.warnings, not an error."""
    from autoreels.__main__ import _check_fade_audible
    from autoreels.core.models import Reel, Segment, Word

    r = Reel(id="r03", start=0.0, end=9.5, score=80, hook="h",
             title="t", description="d",
             segments=[Segment(start=0.0, end=9.5)],
             subtitles=[Word(word="end_word", t0=9.0, t1=9.8)])
    r.tail_last_word_end = 9.1
    r.has_explicit_e = True
    smap_lookup = {round(9.0 * 1000): (0, {"audible_end": 9.7})}  # ae=9.7 > r.end=9.5
    errs, warns = _check_fade_audible([r], smap_lookup=smap_lookup)
    assert errs == [], "explicit_e clip-cut must not be an error"
    assert len(warns) == 1 and "clip end" in warns[0]
    assert any("clip end" in w for w in r.warnings), "warning must be in reel.warnings"


# ── _apply_tail_air: cap at next speech onset ─────────────────────────────────

def test_apply_tail_air_records_intruder_manifest_keeps_full_pad():
    """Next speech within 1.5s → intruder recorded in tail_next_word_start; manifest end = lw_end + pad.
    The render (_tail_from_smap) trims the actual clip before onset; apply only records the intruder."""
    from autoreels.__main__ import _apply_tail_air
    from autoreels.core.models import Reel, Segment, Word

    def _w(t0, t1, word="x"):
        return Word(word=word, t0=t0, t1=t1)

    # "next" at t0=10.5 is within the 1.5s pad window (lw_end=10.0, desired=11.5).
    words = [_w(9.0, 10.0, "last"), _w(10.5, 11.0, "next")]
    r = Reel(id="r01", start=0.0, end=10.1, score=80, hook="h",
             title="t", description="d",
             segments=[Segment(start=0.0, end=10.1)], subtitles=[])

    _apply_tail_air([r], words, tail_pad_sec=1.5, video_duration=None)

    assert r.end == pytest.approx(10.0 + 1.5), f"expected lw_end+pad=11.5 (full pad), got {r.end}"
    assert r.tail_next_word_start == pytest.approx(10.5)  # intruder recorded for render-time trim


def test_apply_tail_air_no_intruder_when_no_next_speech_in_window():
    """No next speech within 1.5s → r.end = lw_end + 1.5s, no intruder recorded."""
    from autoreels.__main__ import _apply_tail_air
    from autoreels.core.models import Reel, Segment, Word

    def _w(t0, t1, word="x"):
        return Word(word=word, t0=t0, t1=t1)

    # "far_next" at t0=12.0 is beyond the 1.5s tail window (lw_end + 1.5 = 11.5 < 12.0).
    words = [_w(9.0, 10.0, "last"), _w(12.0, 13.0, "far_next")]
    r = Reel(id="r01", start=0.0, end=10.1, score=80, hook="h",
             title="t", description="d",
             segments=[Segment(start=0.0, end=10.1)], subtitles=[])

    _apply_tail_air([r], words, tail_pad_sec=1.5, video_duration=None)

    assert r.end == pytest.approx(10.0 + 1.5), f"expected lw_end+1.5=11.5, got {r.end}"
    assert r.tail_next_word_start is None  # 12.0 > 11.5, outside window


# ── render pre-trim invariant ─────────────────────────────────────────────────

def test_check_silence_at_clip_end_fires_for_manifest_overshoot():
    """Pre-trim invariant fires when manifest segment end exceeds next-speech audible_start."""
    import io, contextlib
    from autoreels.local.render import _smap_word_lookup, _check_silence_at_clip_end
    from autoreels.core.models import Word

    # clip_end=10.5 overshoots: next word has audible_start=10.2 which is in (ae=9.9, 10.5)
    smap = {
        "words": [
            {"idx": 0, "t0": 8.5, "t1": 9.5, "audible_start": 8.6, "audible_end": 9.9},
            {"idx": 1, "t0": 10.0, "t1": 10.8, "audible_start": 10.2, "audible_end": 10.8},
        ],
        "boundaries": [],
    }
    lookup = _smap_word_lookup(smap)
    last_word = Word(word="last", t0=8.5, t1=9.5)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _check_silence_at_clip_end("r01", last_word, 10.5, smap, lookup)
    out = buf.getvalue()
    assert "[AUDIO-INV]" in out, f"invariant must fire; got: {out!r}"


def test_check_silence_at_clip_end_silent_when_end_before_onset():
    """Invariant is silent when clip_end (ae + 0.1) is before next-speech audible_start."""
    import io, contextlib
    from autoreels.local.render import _smap_word_lookup, _check_silence_at_clip_end
    from autoreels.core.models import Word

    # clip_end=10.0 (= ae + 0.1): next word audible_start=10.2 is NOT in (9.9, 10.0)
    smap = {
        "words": [
            {"idx": 0, "t0": 8.5, "t1": 9.5, "audible_start": 8.6, "audible_end": 9.9},
            {"idx": 1, "t0": 10.0, "t1": 10.8, "audible_start": 10.2, "audible_end": 10.8},
        ],
        "boundaries": [],
    }
    lookup = _smap_word_lookup(smap)
    last_word = Word(word="last", t0=8.5, t1=9.5)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _check_silence_at_clip_end("r01", last_word, 10.0, smap, lookup)
    out = buf.getvalue()
    assert "[AUDIO-INV]" not in out, f"invariant must be silent; got: {out!r}"
