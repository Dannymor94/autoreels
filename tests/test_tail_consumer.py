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

from autoreels.local.render import (
    _tail_from_smap, _smap_word_lookup,
    _synth_tail_params, _find_room_tone,
)


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


# ── helpers for new-rule tests ────────────────────────────────────────────────

def _call(ae: float, gap: float | None, t0: float = 5.0, **kw):
    """Build a minimal smap with ae=ae and next_onset=ae+gap (or no next word), call _tail_from_smap."""
    if gap is None:
        smap = _make_smap([_make_word(t0, t0 + 0.9, ae=ae)], [])
    else:
        nxt_as = ae + gap
        smap = _make_smap(
            [_make_word(t0, t0 + 0.9, ae=ae), _make_word(nxt_as, nxt_as + 0.5)],
            [_make_boundary(gap)],
        )
    lookup = _smap_word_lookup(smap)
    return _tail_from_smap(last_t0=t0, seg_end=t0 + 10.0, smap=smap, lookup=lookup, **kw)


# ── new rule: end/fade_start/fade_len for key gaps ───────────────────────────

def test_tail_n_none_no_next_speech():
    """N=None (no next speech): end = ae + tail_pad_sec; full fade at end."""
    end, fs, fl = _call(ae=5.8, gap=None)
    assert end == pytest.approx(5.8 + 1.50, abs=0.01)   # ae + tail_pad_sec (1.50)
    assert fs >= 5.8, "fade_start must be >= audible_end"
    assert fl == pytest.approx(0.35, abs=0.01)           # tail_fade_sec = 0.35


def test_tail_gap_1_2s_beyond_pad():
    """Gap 1.2s > tail_pad_sec (0.7s) → N=None → same as no next speech."""
    end, fs, fl = _call(ae=5.8, gap=1.2, tail_pad_sec=0.70)
    assert end == pytest.approx(5.8 + 0.70, abs=0.01)
    assert fs >= 5.8
    assert fl == pytest.approx(0.35, abs=0.01)


def test_tail_gap_0_9s_beyond_pad():
    """Gap 0.9s > tail_pad_sec (0.7s) → N=None → end = ae + 0.7."""
    end, fs, fl = _call(ae=5.8, gap=0.9, tail_pad_sec=0.70)
    assert end == pytest.approx(5.8 + 0.70, abs=0.01)
    assert fs >= 5.8
    assert fl == pytest.approx(0.35, abs=0.01)


def test_tail_gap_0_4s_within_pad():
    """Gap 0.4s within tail_pad_sec → N set; end = N − onset_margin; partial fade."""
    ae = 5.8
    end, fs, fl = _call(ae=ae, gap=0.4)
    N = ae + 0.4
    assert end == pytest.approx(N - 0.06, abs=0.01)  # min(N-onset_margin, ae+tail_pad)
    assert end < N                                    # never reaches next onset
    assert fs >= ae, "fade_start must be >= audible_end"
    # room=0.34, fade_keep=0.20 → fade_len=0.14
    assert fl == pytest.approx(0.14, abs=0.01)


def test_tail_gap_0_1s_tight():
    """Gap 0.1s: end just before onset; fade floor = 2 frames (room < fade_keep)."""
    ae = 5.8
    end, fs, fl = _call(ae=ae, gap=0.1)
    N = ae + 0.1
    two_frames = 2.0 / 30.0
    assert end < N                         # strictly before onset
    assert end >= ae                       # end not before audible_end
    assert fl >= two_frames - 1e-9        # floor: 2 frames
    assert fs == pytest.approx(end - fl, abs=1e-6)  # fade_start = end − fade_len


def test_tail_gap_0_0s_zero_gap():
    """Gap 0s (next onset == ae): end before ae (onset_margin); fade = 2 frames, starts before ae."""
    ae = 5.8
    end, fs, fl = _call(ae=ae, gap=0.0)
    two_frames = 2.0 / 30.0
    assert end < ae                        # N == ae → end = ae − onset_margin
    assert fl >= two_frames - 1e-9        # floor: 2 frames
    assert fs < ae                         # fade starts before ae (room < 0)
    assert fs == pytest.approx(end - fl, abs=1e-6)


# ── fade_len minimum ─────────────────────────────────────────────────────────

def test_fade_len_minimum_two_frames():
    """fade_len >= 2/fps in every case, even when room is zero or negative."""
    two_frames = 2.0 / 30.0
    for gap in [0.0, 0.02, 0.05, 0.1, 0.4, 1.5]:
        end, fs, fl = _call(ae=5.8, gap=gap)
        assert fl >= two_frames - 1e-9, f"gap={gap}: fade_len={fl:.5f} < 2 frames"
        assert fs == pytest.approx(end - fl, abs=1e-6), f"gap={gap}: fs+fl != end"


# ── silence case ─────────────────────────────────────────────────────────────

def test_tail_silence_case():
    """Gap = tail_pad_sec → N is set; end = N − onset_margin = ae + 0.64."""
    # last word: t0=5.0, ae=5.8; next word: as=6.5 → gap=0.7 = tail_pad_sec
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8), _make_word(6.5, 7.0)],
        [_make_boundary(0.7)],
    )
    lookup = _smap_word_lookup(smap)
    end, fs, fl = _tail_from_smap(
        last_t0=5.0, seg_end=6.0, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35,
    )
    # gap=0.7 = tail_pad_sec → N=6.5; end = min(6.5-0.06, 5.8+0.70) = 6.44
    assert end == pytest.approx(6.44, abs=0.01)
    assert end < 6.5  # never at or past onset


def test_tail_silence_case_capped_by_next_onset():
    """End is always before next word audible_start."""
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8), _make_word(5.95, 6.5)],
        [_make_boundary(0.15)],
    )
    lookup = _smap_word_lookup(smap)
    end, fs, fl = _tail_from_smap(
        last_t0=5.0, seg_end=6.0, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35,
    )
    assert end < 5.95   # never at or past next audible_start


# ── speech-next case ─────────────────────────────────────────────────────────

def test_tail_speech_next_case():
    """Gap < tail_pad_sec → end strictly before next speech onset."""
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8), _make_word(5.95, 6.5)],
        [_make_boundary(0.15)],
    )
    lookup = _smap_word_lookup(smap)
    end, fs, fl = _tail_from_smap(
        last_t0=5.0, seg_end=6.0, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35,
    )
    assert end < 5.95
    assert end > 5.0


def test_tail_speech_next_zero_gap():
    """Gap = 0: end clamped to ae, never past onset (PXL r08 case)."""
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8), _make_word(5.8, 7.0)],
        [_make_boundary(0.0)],
    )
    lookup = _smap_word_lookup(smap)
    end, fs, fl = _tail_from_smap(
        last_t0=5.0, seg_end=7.0, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35,
    )
    assert end <= 5.8, f"end {end:.4f} overshoots onset 5.8"
    assert end > 5.0


# ── untranscribed speech in gap ───────────────────────────────────────────────

def test_tail_untranscribed_speech_is_next_onset():
    """Untranscribed speech onset within pad window → end before it."""
    # ae=5.8; untr speech at [6.0, 6.3]; gap=0.2 < tail_pad_sec → end before 6.0
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8), _make_word(7.0, 7.5)],
        [_make_boundary(0.7, untr=[[6.0, 6.3]])],
    )
    lookup = _smap_word_lookup(smap)
    end, fs, fl = _tail_from_smap(
        last_t0=5.0, seg_end=7.5, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35,
    )
    assert end < 6.0
    assert end > 5.0


def test_tail_pxl_r08_speech_next_real_numbers():
    """PXL r08 actual numbers: untranscribed speech triggers near-onset end.

    Render log: last='сильнее.' t0=2146.195 ae=2146.790; untr onset=2147.000 (gap=0.21);
    first transcribed word t0=2147.255 audible_start=2147.270; seg_end=2148.767.
    """
    smap = _make_smap(
        [
            _make_word(2146.195, 2146.500, ae=2146.790),
            _make_word(2147.255, 2147.700),
        ],
        [_make_boundary(0.21, untr=[[2147.000, 2147.200]])],
    )
    lookup = _smap_word_lookup(smap)
    end, fs, fl = _tail_from_smap(
        last_t0=2146.195, seg_end=2148.767, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35, last_t1=2146.500,
    )
    # gap to untr onset = 0.21; end = min(2147.000-0.06, 2146.790+0.70) = 2146.940
    assert end <= 2147.000, f"render end {end:.3f} overshoots untranscribed onset 2147.000"
    assert end >= 2146.790, f"render end {end:.3f} precedes last-word ae 2146.790"


def test_tail_untr_far_from_ae_silence_case():
    """Untranscribed speech onset within pad window → end = N − onset_margin."""
    # ae=5.8; untr at [6.2, 6.5]; gap=0.4 < tail_pad_sec=0.7 → N=6.2, end=6.14
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8), _make_word(7.0, 7.5)],
        [_make_boundary(0.7, untr=[[6.2, 6.5]])],
    )
    lookup = _smap_word_lookup(smap)
    end, fs, fl = _tail_from_smap(
        last_t0=5.0, seg_end=7.5, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35,
    )
    # end = min(6.2-0.06, 5.8+0.70) = 6.14; capped at min(6.14, 6.2)=6.14
    assert end == pytest.approx(6.14, abs=0.01)
    assert end < 6.2  # before untr onset


# ── own-word-tail filter ─────────────────────────────────────────────────────

def test_tail_own_word_tail_extended_b():
    """Short untranscribed interval close after ae + real gap → own tail, ae extended."""
    # ae=5.8; untr at [5.95, 6.10] dur=0.15 < 0.25, gap from ae=0.15 < 0.30, gap_after=0.40
    # Without filter: N=5.95, end=5.89
    # With filter: ae→6.10, next_as=6.50 gap=0.40, N=6.50, end=min(6.44, 7.60)=6.44
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8), _make_word(6.5, 7.0)],
        [_make_boundary(0.7, untr=[[5.95, 6.10]])],
    )
    lookup = _smap_word_lookup(smap)
    end, fs, fl = _tail_from_smap(
        last_t0=5.0, seg_end=7.5, smap=smap, lookup=lookup,
        own_tail_window_sec=0.30, own_tail_short_sec=0.25, own_tail_gap_min_sec=0.10,
    )
    assert end >= 6.10, f"end {end:.3f} must be past own-tail interval end 6.10"
    assert end < 6.5, f"end {end:.3f} must be before next word onset 6.5"
    assert end == pytest.approx(6.44, abs=0.01)


def test_tail_own_word_tail_t1_inside_interval_fires_regardless_of_length():
    """t1 inside interval → own tail even when dur >= own_tail_short_sec (PXL r05-like)."""
    # word t1=5.68 is inside untr [5.60, 5.95] (dur=0.35 >= 0.25 → duration rule would fail)
    # t1_hint fires: ae → 5.95; next word as=6.5 → N=6.5, end=min(6.44, 7.45)=6.44
    smap = _make_smap(
        [_make_word(5.0, 5.68, ae=5.45), _make_word(6.5, 7.0)],
        [_make_boundary(0.9, untr=[[5.60, 5.95]])],
    )
    lookup = _smap_word_lookup(smap)
    end, fs, fl = _tail_from_smap(
        last_t0=5.0, seg_end=7.5, smap=smap, lookup=lookup,
    )
    assert end >= 5.95, f"end {end:.3f} must be past own-tail interval end 5.95"
    assert end < 6.5, f"end {end:.3f} must be before next word onset"
    assert end == pytest.approx(6.44, abs=0.01)


def test_tail_own_word_tail_t1_just_past_end_margin_fires(  # PXL r10-like
):
    """iv_e <= t1 + t1_margin → own tail even when t1 is slightly past interval end."""
    # word t1=5.95 just past iv_e=5.88 but within margin 0.15 → t1_hint fires
    # (t1 is NOT inside the interval; iv_e <= t1+0.15 = 6.10 is the condition)
    # ae → 5.88; next untr starts at 6.50 → N=6.50, end=min(6.44, 7.38)=6.44
    smap = _make_smap(
        [_make_word(5.0, 5.95, ae=5.45), _make_word(7.0, 7.5)],
        [_make_boundary(1.6, untr=[[5.60, 5.88], [6.50, 6.80]])],
    )
    lookup = _smap_word_lookup(smap)
    end, fs, fl = _tail_from_smap(
        last_t0=5.0, seg_end=8.0, smap=smap, lookup=lookup,
    )
    assert end >= 5.88, f"end {end:.3f} must be past own-tail interval end 5.88"
    assert end < 6.50, f"end {end:.3f} must be before next onset 6.50"
    assert end == pytest.approx(6.44, abs=0.01)


def test_tail_own_word_tail_not_filtered_when_too_long_and_t1_before():
    """Interval too long AND t1 before interval → neither rule fires → end before onset."""
    # ae=5.8; untr at [5.95, 6.25] dur=0.30 >= 0.25; word t1=5.9 before interval start
    # t1_hint: 5.9 < 5.95 (not inside), iv_e=6.25 > t1+0.15=6.05 (not within margin)
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8), _make_word(6.5, 7.0)],
        [_make_boundary(0.7, untr=[[5.95, 6.25]])],
    )
    lookup = _smap_word_lookup(smap)
    end, fs, fl = _tail_from_smap(
        last_t0=5.0, seg_end=7.5, smap=smap, lookup=lookup,
        own_tail_window_sec=0.30, own_tail_short_sec=0.25, own_tail_gap_min_sec=0.10,
    )
    assert end < 5.95, f"long interval with t1 before it must still be next speech, end={end:.3f}"


def test_tail_own_word_tail_not_filtered_when_gap_too_small():
    """Gap from interval end to next word < gap_min → NOT own tail → end before onset."""
    # ae=5.8; untr at [5.95, 6.10] dur=0.15 (short), but gap_after=5.95+0.15 to 6.15 = 0.05 < 0.10
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8), _make_word(6.15, 7.0)],
        [_make_boundary(0.35, untr=[[5.95, 6.10]])],
    )
    # Make next word audible_start = 6.15 (gap_after = 6.15 - 6.10 = 0.05 < 0.10)
    smap["words"][1]["audible_start"] = 6.15
    lookup = _smap_word_lookup(smap)
    end, fs, fl = _tail_from_smap(
        last_t0=5.0, seg_end=7.5, smap=smap, lookup=lookup,
        own_tail_window_sec=0.30, own_tail_short_sec=0.25, own_tail_gap_min_sec=0.10,
    )
    assert end < 5.95, f"small gap: must still be next speech, end={end:.3f}"


# ── last word of transcript ───────────────────────────────────────────────────

def test_tail_last_word_of_transcript():
    """Last word has no next word → N=None, end = ae + tail_pad_sec."""
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8)],
        [],
    )
    lookup = _smap_word_lookup(smap)
    end, fs, fl = _tail_from_smap(
        last_t0=5.0, seg_end=6.0, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35,
    )
    assert end == pytest.approx(5.8 + 1.50, abs=0.01)   # ae + tail_pad_sec (1.50)
    assert fs >= 5.8


# ── word not found → None ─────────────────────────────────────────────────────

def test_tail_word_not_in_smap_returns_none():
    """Word with t0 not in smap → return None."""
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8), _make_word(6.5, 7.0)],
        [_make_boundary(0.7)],
    )
    lookup = _smap_word_lookup(smap)
    result = _tail_from_smap(
        last_t0=99.0,
        seg_end=6.0, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35,
    )
    assert result is None


# ── map-always-applies ────────────────────────────────────────────────────────

def test_tail_map_applies_even_when_seg_end_far():
    """Map path always applies — no window guard."""
    # gap=0.7 = tail_pad_sec → N=6.5; end = 6.44
    smap = _make_smap(
        [_make_word(5.0, 5.9, ae=5.8), _make_word(6.5, 7.0)],
        [_make_boundary(0.7)],
    )
    lookup = _smap_word_lookup(smap)
    end, fs, fl = _tail_from_smap(
        last_t0=5.0, seg_end=10.0, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35,
    )
    assert end is not None
    assert end == pytest.approx(6.44, abs=0.01)


# ── residue attribution ───────────────────────────────────────────────────────

def test_tail_residue_adjacent_word_attributed_to_last():
    """Smap word whose Whisper t0 == last_word.t1 is residue — merged, not treated as next speech."""
    # ae after residue = 5.8; real next at 7.2, gap=1.4 > tail_pad_sec 0.7 → N=None, end=6.5
    smap = _make_smap(
        [_make_word(5.0, 5.5, ae=5.6), _make_word(5.5, 5.9, ae=5.8), _make_word(7.2, 7.7)],
        [_make_boundary(0.0), _make_boundary(1.4)],
    )
    smap["words"][1]["audible_start"] = 5.62
    lookup = _smap_word_lookup(smap)
    end, fs, fl = _tail_from_smap(
        last_t0=5.0, seg_end=8.0, smap=smap, lookup=lookup,
        tail_pad_sec=0.70, cut_pause_min_sec=0.35, last_t1=5.5,
    )
    # After residue: ae=5.8, next real onset=7.2 > ae+0.7=6.5 → N=None → end=6.5
    assert end == pytest.approx(5.8 + 0.70, abs=0.01)
    assert end > 5.5  # NOT cut to before residue


# ── invariant: new_end >= audible_end ─────────────────────────────────────────

def test_tail_new_end_never_before_audible_end():
    """Invariant holds: new_end >= audible_end after residue attribution."""
    smap = _make_smap(
        [_make_word(5.0, 5.5, ae=5.8), _make_word(5.5, 6.0, ae=6.0)],
        [_make_boundary(0.0)],
    )
    lookup = _smap_word_lookup(smap)
    end, fs, fl = _tail_from_smap(
        last_t0=5.0, seg_end=7.0, smap=smap, lookup=lookup,
        cut_pause_min_sec=0.35, last_t1=5.5,
    )
    assert end >= 5.8  # >= original audible_end


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


def test_check_fade_audible_clip_too_short_for_min_fade():
    """Defect 3 (r05 case): clip ends only 0.1s after audible_end.
    The min tail-video-fade (0.25s) would be pulled back before ae.
    lw_end >= ae passes the old check; new clip-too-short guard must fire.
    """
    from autoreels.__main__ import _check_fade_audible, _TAIL_VIDEO_FADE_MIN_SEC
    from autoreels.core.models import Reel, Segment, Word

    # ae=9.6, r.end=9.7 → gap=0.1 < 0.25 = min_fade
    r = Reel(id="r05", start=0.0, end=9.7, score=80, hook="h",
             title="t", description="d",
             segments=[Segment(start=0.0, end=9.7)],
             subtitles=[Word(word="слово", t0=9.0, t1=9.7)])
    r.tail_last_word_end = 9.7   # lw_end >= ae — old check wouldn't fire
    smap_lookup = {round(9.0 * 1000): (0, {"audible_end": 9.6})}
    errs, warns = _check_fade_audible([r], smap_lookup=smap_lookup)
    assert len(errs) == 1, "clip-too-short must be an error"
    assert "too short" in errs[0] or "gap" in errs[0]
    assert warns == []


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


# ── render post-trim invariant ────────────────────────────────────────────────

def test_check_silence_at_clip_end_fires_for_manifest_overshoot():
    """Post-trim ERROR fires when rendered clip end still overlaps next-speech audible_start."""
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

    errors = _check_silence_at_clip_end("r01", last_word, 10.5, smap, lookup)
    assert errors, "invariant must fire (non-empty list)"
    assert any("[ERROR]" in e for e in errors), f"errors must contain [ERROR]; got: {errors}"


def test_check_silence_at_clip_end_silent_when_end_before_onset():
    """No [ERROR] when clip_end (ae + 0.1) is before next-speech audible_start."""
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

    errors = _check_silence_at_clip_end("r01", last_word, 10.0, smap, lookup)
    assert errors == [], f"invariant must be silent (empty list); got: {errors}"


# ── synthetic tail helpers ────────────────────────────────────────────────────

def test_synth_tail_params_room_below_threshold_fires():
    """room=0.2s < min_room_sec=0.6 → params returned; cut_point, bridge, flags correct."""
    # ae=5.8, N=6.1 → room=0.2 < 0.6 → synthetic
    params = _synth_tail_params(
        audible_end=5.8, N=6.1, end=6.04,
        min_room_sec=0.60, keep_sec=0.15, tail_sec=1.0,
    )
    assert params is not None, "should fire"
    # cut_point = min(N - onset_margin=0.06, ae + keep_sec=0.15) = min(6.04, 5.95) = 5.95
    assert params["cut_point"] == pytest.approx(5.95, abs=1e-6)
    # bridge_dur = min(gap/2, 0.25) = min((6.1-5.8)/2, 0.25) = min(0.15, 0.25) = 0.15
    assert params["bridge_dur"] == pytest.approx(0.15, abs=1e-6)
    assert params["use_freeze"] is True   # always freeze (slow-mo removed)
    assert params["tail_sec"] == 1.0
    assert params["room"] == pytest.approx(0.24, abs=0.01)


def test_synth_tail_params_room_above_threshold_unchanged():
    """room=0.7s >= min_room_sec=0.6 → None returned; existing tail rule keeps working."""
    params = _synth_tail_params(
        audible_end=5.0, N=8.0, end=5.7,
        min_room_sec=0.60, keep_sec=0.15, tail_sec=1.0,
    )
    assert params is None


def test_synth_tail_params_freeze_branch_short_gap():
    """bridge_dur < 0.1 → use_freeze=True (no slow-mo when gap tiny)."""
    # ae=5.8, N=5.87 → gap=0.07, bridge_dur=min(0.035, 0.25)=0.035 < 0.1 → freeze
    params = _synth_tail_params(
        audible_end=5.8, N=5.87, end=5.81,
        min_room_sec=0.60, keep_sec=0.15, tail_sec=1.0,
    )
    assert params is not None
    assert params["use_freeze"] is True
    assert params["bridge_dur"] == pytest.approx(0.035, abs=1e-6)


def test_find_room_tone_finds_longest_silence_within_window():
    """_find_room_tone returns margin-adjusted start of the longest silence within ±3s."""
    # window [2, 8]; gaps: [1.0,1.5] out, [2.0,3.5]=1.5s ≥ 0.6s best, [4.0,4.5]=0.5s < 0.6s skip
    smap = {
        "intervals": [
            [0.0, 1.0],
            [1.5, 2.0],
            [3.5, 4.0],
            [4.5, 9.0],
            [10.0, 11.0],
        ],
    }
    result = _find_room_tone(smap, near_t=5.0, window_sec=3.0)
    assert result is not None
    # start is gap_s + margin = 2.0 + 0.3 = 2.3 (0.3s margin from speech at 2.0)
    assert result[0] == pytest.approx(2.3, abs=1e-6)
    assert result[1] == pytest.approx(3.5, abs=1e-6)


def test_find_room_tone_speech_inside_silence_rejected():
    """A gap containing a quiet word (interval inside) is split; both sub-gaps may be too short.

    Regression: room tone was picked starting right at the speech boundary (0 margin),
    so quiet trailing speech was audible. Fix: 0.3s margin on both sides + gaps < 2*margin skipped.
    """
    # [5.0, 5.8] is a gap — but [5.3, 5.6] is a quiet word inside it (sub-gap each 0.3s wide)
    smap = {
        "intervals": [
            [0.0, 5.0],
            [5.3, 5.6],   # quiet word in the middle of the silence
            [5.8, 6.0],
            [10.0, 11.0],
        ],
    }
    # Sub-gaps: [5.0,5.3]=0.3s < 2*0.3=0.6s → skip; [5.6,5.8]=0.2s → skip; [6.0,10.0]=4s → best
    result = _find_room_tone(smap, near_t=5.5, window_sec=60.0)
    assert result is not None
    # The only qualifying gap is [6.0, 10.0]; start = 6.0 + 0.3 = 6.3
    assert result[0] == pytest.approx(6.3, abs=1e-6)
    assert result[1] == pytest.approx(10.0, abs=1e-6)


def test_find_room_tone_margin_skips_short_gaps():
    """Gaps shorter than 2 * margin_sec are skipped entirely."""
    smap = {
        "intervals": [
            [0.0, 5.0],
            [5.5, 10.0],  # gap [5.0, 5.5] = 0.5s < 2*0.3=0.6s → skip
        ],
    }
    result = _find_room_tone(smap, near_t=5.0, window_sec=60.0)
    assert result is None, "gap < 2*margin_sec must be rejected"


# ── overlap-error tolerance (1 output frame) ─────────────────────────────────

def test_overlap_error_suppressed_within_one_frame(capsys):
    """[ERROR] must NOT fire when ae - end <= 1 output frame (1/fps).

    PXL r09: ae=2515.910, end=2515.900 → overlap=0.010s. At 30fps one frame=0.033s.
    0.010 < 0.033 → no message.
    """
    from autoreels.local.render import _tail_from_smap_full, _smap_word_lookup

    fps = 30.0
    # next word starts at N=2515.960, ae=2515.910, so end will be N-onset_margin < ae
    smap = _make_smap(
        [_make_word(2513.800, 2514.540, ae=2515.910),
         _make_word(2515.960, 2516.500)],
        [_make_boundary(1.42)],
    )
    lookup = _smap_word_lookup(smap)
    result = _tail_from_smap_full(
        last_t0=2513.800, seg_end=2517.0, smap=smap, lookup=lookup,
        fps=fps, onset_margin_sec=0.06,
    )
    assert result is not None
    captured = capsys.readouterr()
    assert "[ERROR]" not in captured.out, (
        f"must be silent when ae-end <= 1 frame; got: {captured.out!r}"
    )


def test_overlap_error_fires_beyond_one_frame(capsys):
    """[ERROR] must fire when ae - end > 1 output frame."""
    from autoreels.local.render import _tail_from_smap_full, _smap_word_lookup

    fps = 30.0
    # N very close to last word t1: next word starts only 0.05s after t1=2514.540
    # so end = N - onset_margin = 2514.540+0.05 - 0.06 = 2514.530
    # ae=2515.910 → ae - end = 1.380 >> 1 frame
    smap = _make_smap(
        [_make_word(2513.800, 2514.540, ae=2515.910),
         _make_word(2514.590, 2515.000)],
        [_make_boundary(0.05)],
    )
    lookup = _smap_word_lookup(smap)
    result = _tail_from_smap_full(
        last_t0=2513.800, seg_end=2517.0, smap=smap, lookup=lookup,
        fps=fps, onset_margin_sec=0.06,
    )
    assert result is not None
    captured = capsys.readouterr()
    assert "[ERROR]" in captured.out, "must print [ERROR] when ae-end > 1 frame"
