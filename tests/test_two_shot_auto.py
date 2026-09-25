"""M1.7 step 1b gate: two_shot_auto — seam alternation + symmetric max-shot rule."""
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
    # two_shot_max_wide_sec kept as backward-compat alias; canonical is two_shot_max_shot_sec
    d = dict(two_shot=True, two_shot_auto=True, two_shot_max_shot_sec=9.0, two_shot_min_sec=2.5)
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
    segs = [_seg(0, 5), _seg(6, 12, shot="close"), _seg(13, 20)]
    out = _apply(segs)
    assert out[1].shot == "close"
    assert out[0].shot == "wide"
    assert out[2].shot == "wide"


# ── Test 4: min-length suppresses flip ───────────────────────────────────────

def test_min_length_suppresses_flip():
    segs = [_seg(0, 1.0), _seg(1.5, 10)]
    out = _apply(segs, two_shot_min_sec=2.5)
    assert out[1].shot == "wide"


# ── Test 5: max-wide fires (backward-compat alias) ────────────────────────────

def test_max_wide_inserts_close_intervals_at_pause():
    words = [
        Word(word="а", t0=0.0, t1=1.0),
        Word(word="б.", t0=1.5, t1=3.0),
        Word(word="в", t0=3.5, t1=5.0),
        Word(word="г.", t0=6.0, t1=10.0),
    ]
    # Use the old alias key to verify backward compat
    cfg = SimpleNamespace(two_shot=True, two_shot_auto=True,
                          two_shot_max_wide_sec=9.0, two_shot_min_sec=2.5)
    from autoreels.__main__ import _stage_two_shot_auto
    reel = _reel([_seg(0, 12)])
    _stage_two_shot_auto([reel], words, render_cfg=cfg)
    out = reel.effective_segments()
    assert out[0].close_intervals, "max-wide must trigger a close_intervals switch"
    rel = out[0].close_intervals[0][0]
    assert 2.9 <= rel <= 3.6, f"switch expected near pause boundary ~3.0s, got {rel}"


# ── Test 6: symmetric max — close shot too long fires wide switch ─────────────

def test_symmetric_max_close_too_long():
    # close stretch = 14s > max_shot=9s; pause at t=3 in the close segment
    words = [
        Word(word="а", t0=0.0, t1=1.0),
        Word(word="б.", t0=2.0, t1=3.0),
        Word(word="в", t0=3.5, t1=5.0),
        Word(word="г.", t0=7.0, t1=8.0),
        Word(word="д", t0=8.5, t1=13.0),
    ]
    segs = [_seg(0.0, 5.0), _seg(5.5, 19.5, shot="close")]
    out = _apply(segs, words, two_shot_max_shot_sec=9.0)
    # The close segment should become wide+ci=[0, switch_rel]
    assert out[1].shot == "wide", "symmetric max must change close to wide+ci"
    ci = out[1].close_intervals
    assert ci and ci[0][0] == 0.0, "ci must start at 0 (close begins at segment start)"
    rel = ci[0][1]
    assert rel >= 2.5, f"close portion >= min_shot, got {rel:.2f}"
    assert (out[1].end - out[1].start) - rel >= 2.5, "wide tail must be >= min_shot"


# ── Test 7: no pause → warning reported, no ci inserted ──────────────────────

def test_no_pause_reported_when_no_boundary():
    # One long word with no sentence boundary → no pause found
    words = [Word(word="а", t0=0.0, t1=12.0)]
    segs = [_seg(0.0, 12.0)]
    reel = _reel(segs)
    from autoreels.__main__ import _stage_two_shot_auto
    _stage_two_shot_auto([reel], words, render_cfg=_cfg(two_shot_max_shot_sec=9.0))
    warns = getattr(reel, "_two_shot_warnings", [])
    assert any("no pause" in w for w in warns), f"expected 'no pause' warning, got {warns}"
    assert not reel.effective_segments()[0].close_intervals


# ── Test 8: final min-shot check — no span < min_shot (incl. filler-as-wide) ─

def test_no_short_spans_after_max_wide_with_filler():
    # 12s wide, then 0.7s filler, then close: ci must adjust to leave wide_tail+filler >= min_shot
    words = [
        Word(word="а", t0=0.0, t1=2.0),
        Word(word="б.", t0=2.5, t1=4.0),
        Word(word="в", t0=4.5, t1=7.0),
        Word(word="г.", t0=8.0, t1=9.0),
        Word(word="д", t0=9.5, t1=12.0),
    ]
    segs = [_seg(0.0, 12.0), _seg(12.7, 20.0, shot="close")]
    out = _apply(segs, words, two_shot_max_shot_sec=9.0, two_shot_min_sec=2.5)
    from autoreels.__main__ import _shot_spans_merged
    for stype, dur in _shot_spans_merged(out):
        assert dur >= 2.5, f"short {stype} span: {dur:.2f}s < 2.5s"


# ── Test 9: human-path stage list includes _stage_two_shot_auto ───────────────

def test_human_path_stage_list_includes_two_shot_auto():
    from autoreels import __main__ as cli
    assert "_stage_two_shot_auto" in cli._MANUAL_FORMATTING_STAGES, (
        "_stage_two_shot_auto must be in _MANUAL_FORMATTING_STAGES"
    )
    assert "_stage_two_shot_auto(" in inspect_src(), (
        "_stage_two_shot_auto must be called inside _blocks_do_apply"
    )


def inspect_src():
    import inspect
    from autoreels import __main__ as cli
    return inspect.getsource(cli._blocks_do_apply)
