"""M1.7 step 1b, Part B: two_shot_auto — automatic wide/close alternation at seams.

Tests:
1. flag off → segments unchanged
2. alternation at seams (3 segments: wide, close, wide)
3. manual c: assignment not overridden
4. min-length suppresses flip at a short seam
5. max-wide inserts close_intervals at a pause boundary
6. human-path stage list includes _stage_two_shot_auto
"""
from types import SimpleNamespace

import pytest

from autoreels.core.models import Reel, Segment, Word


def _seg(start, end, shot="wide", close_intervals=None):
    return Segment(start=start, end=end, shot=shot, close_intervals=close_intervals or [])


def _reel(segs, id="r01", subtitles=None):
    r = Reel(
        id=id, start=segs[0].start, end=segs[-1].end,
        score=80, hook="", title="", description="",
        subtitles=subtitles or [],
    )
    r.segments = list(segs)
    return r


def _cfg(**kw):
    d = dict(two_shot=True, two_shot_auto=True, two_shot_max_wide_sec=9.0, two_shot_min_sec=2.5)
    d.update(kw)
    return SimpleNamespace(**d)


def _apply(segs, words=None, **cfg_kw):
    from autoreels.__main__ import _stage_two_shot_auto
    reel = _reel(segs)
    _stage_two_shot_auto([reel], words or [], render_cfg=_cfg(**cfg_kw))
    return reel.effective_segments()


# ── Test 1: flag off → no change ─────────────────────────────────────────────

def test_flag_off_returns_identical():
    segs = [_seg(0, 5), _seg(6, 12)]
    reel = _reel(segs)
    orig = list(reel.segments)
    from autoreels.__main__ import _stage_two_shot_auto
    _stage_two_shot_auto([reel], [], render_cfg=_cfg(two_shot_auto=False))
    assert reel.segments == orig


# ── Test 2: alternation wide→close→wide at seams ─────────────────────────────

def test_alternation_at_three_seams():
    segs = [_seg(0, 5), _seg(6, 12), _seg(13, 20)]
    out = _apply(segs)
    assert out[0].shot == "wide"
    assert out[1].shot == "close"
    assert out[2].shot == "wide"


# ── Test 3: manual assignment preserved ──────────────────────────────────────

def test_manual_close_not_overridden():
    # seg[1] manually close: auto should leave it; seg[2] sees close→wide transition
    segs = [_seg(0, 5), _seg(6, 12, shot="close"), _seg(13, 20)]
    out = _apply(segs)
    assert out[1].shot == "close"       # manual preserved
    assert out[0].shot == "wide"        # initial wide
    # After manual close, next auto is wide
    assert out[2].shot == "wide"


# ── Test 4: min-length suppresses flip ───────────────────────────────────────

def test_min_length_suppresses_flip():
    # seg[0] is only 1s < min_shot=2.5s → flip at seam[0→1] suppressed
    segs = [_seg(0, 1.0), _seg(1.5, 10)]
    out = _apply(segs, two_shot_min_sec=2.5)
    # Flip suppressed: seg[1] stays wide (same as seg[0])
    assert out[1].shot == "wide"


# ── Test 5: max-wide inserts close_intervals at pause boundary ────────────────

def test_max_wide_inserts_close_intervals_at_pause():
    # One wide segment of 12s > max_wide=9s. Pause of 0.5s after "б." at t=3.0.
    words = [
        Word(word="а", t0=0.0, t1=1.0),
        Word(word="б.", t0=1.5, t1=3.0),   # sentence ends here
        # gap 0.5s
        Word(word="в", t0=3.5, t1=5.0),
        Word(word="г.", t0=6.0, t1=10.0),
    ]
    out = _apply([_seg(0, 12)], words, two_shot_max_wide_sec=9.0, two_shot_min_sec=2.5)
    assert out[0].close_intervals, "max-wide must trigger a close_intervals switch"
    rel = out[0].close_intervals[0][0]
    assert 2.9 <= rel <= 3.6, f"switch expected near pause boundary ~3.0s, got {rel}"


# ── Test 6: human-path stage list includes _stage_two_shot_auto ───────────────

def test_human_path_stage_list_includes_two_shot_auto():
    from autoreels import __main__ as cli
    assert "_stage_two_shot_auto" in cli._MANUAL_FORMATTING_STAGES, (
        "_stage_two_shot_auto must be in _MANUAL_FORMATTING_STAGES so the human "
        "path runs it (formatting, not deciding)"
    )
    assert "_stage_two_shot_auto(" in inspect_src(), (
        "_stage_two_shot_auto must be called inside _blocks_do_apply"
    )


def inspect_src():
    import inspect
    from autoreels import __main__ as cli
    return inspect.getsource(cli._blocks_do_apply)
