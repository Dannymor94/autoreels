"""Part 2: frame-level shot-span check uses real thresholds (two_shot_min_sec, two_shot_min_middle_sec).

Violations produce [ERROR] warnings via Pass 4 of _apply_two_shot_auto_reel.
"""
from types import SimpleNamespace

from autoreels.core.models import Reel, Segment


def _seg(start, end, shot="wide", close_intervals=None):
    return Segment(start=start, end=end, shot=shot, close_intervals=close_intervals or [])


def _reel(segs, id="r01"):
    r = Reel(id=id, start=segs[0].start, end=segs[-1].end,
             score=80, hook="", title="", description="", subtitles=[])
    r.segments = list(segs)
    return r


def _cfg(**kw):
    d = dict(two_shot=True, two_shot_auto=True, two_shot_max_shot_sec=9.0,
             two_shot_min_sec=2.5, two_shot_min_middle_sec=4.0)
    d.update(kw)
    return SimpleNamespace(**d)


def _apply(segs, **kw):
    from autoreels.__main__ import _stage_two_shot_auto
    reel = _reel(segs)
    _stage_two_shot_auto([reel], [], render_cfg=_cfg(**kw))
    return reel


# ── short span below two_shot_min_sec → [ERROR] ─────────────────────────────

def test_short_span_below_min_shot_produces_error():
    """A wide span of 0.3 s (< min_shot=2.5 s) not snappable → [ERROR]."""
    # ci starting 0.3 s in — wide span before ci = 0.3 s
    segs = [_seg(0.0, 10.0, "wide", [[0.3, 8.0]])]
    reel = _apply(segs)
    warns = getattr(reel, "_two_shot_warnings", [])
    errors = [w for w in warns if "[ERROR]" in w]
    assert errors, f"expected [ERROR] for 0.3 s wide span; got warns={warns}"
    assert any("short" in e for e in errors), f"expected 'short' in [ERROR]; got {errors}"


# ── A-B-A middle below two_shot_min_middle_sec → [ERROR] ────────────────────

def test_aba_middle_below_min_middle_produces_error():
    """An A-B-A middle of 2.0 s (< min_middle=4.0 s) that was forced by a jump seam
    (_js_forced) is not removed by A-B-A guard, so Pass 4 must emit [ERROR].

    Setup: beat reel, 3 segments.
    seg0(close 5 s) → jump seam → seg1(forced wide 2 s) → non-jump → seg2(close 5 s).
    A-B-A guard skips seg1 (in _js_forced). Pass 4 sees: close→wide(2s)→close A-B-A middle.
    """
    from autoreels.__main__ import _stage_two_shot_auto
    segs = [
        _seg(0.0, 5.0, "close"),    # close 5 s
        _seg(15.0, 17.0, "close"),  # gap=10 s (jump seam) → forced wide 2 s
        _seg(17.5, 22.5, "close"),  # gap=0.5 s (non-jump) → close 5 s
    ]
    reel = _reel(segs)
    reel.beat_gap_sec = 0.25
    _stage_two_shot_auto([reel], [], render_cfg=_cfg(beat_clip_shots_only_at_seams=False))
    warns = getattr(reel, "_two_shot_warnings", [])
    errors = [w for w in warns if "[ERROR]" in w]
    result = reel.effective_segments()
    # seg1 must be wide (forced by jump seam, protected by _js_forced from A-B-A)
    assert result[1].shot == "wide", (
        f"seg1 must be forced wide by jump seam; got {result[1].shot}"
    )
    # A-B-A middle = 2.0 s < min_middle=4.0 s → [ERROR]
    assert any("A-B-A" in e or "middle" in e for e in errors), (
        f"expected [ERROR] A-B-A middle for 2.0 s wide span; got warns={warns}"
    )


# ── synthetic wide–close–wide sequence spanning min_shot boundary ────────────

def test_synthetic_frame_sequence_no_error_when_spans_ok():
    """Spans of exactly min_shot (2.5 s) and min_middle (4.0 s) must NOT produce [ERROR]."""
    # close(5s) → wide(4.0s) → close(5s): A-B-A middle exactly = min_middle → no [ERROR]
    segs = [
        _seg(0.0, 5.0),             # auto → close
        _seg(5.5, 9.5),             # auto → wide (4.0 s, exactly min_middle)
        _seg(10.0, 15.0),           # auto → close
    ]
    reel = _apply(segs)
    warns = getattr(reel, "_two_shot_warnings", [])
    errors = [w for w in warns if "[ERROR]" in w]
    assert not errors, f"no [ERROR] expected for spans at threshold; got: {errors}"


# ── Part 2: cold_open excluded from A-B-A check (body-only) ──────────────────

def test_p4_cold_open_aba_close_wide_close_error():
    """cold_open is NOT included in Pass 4 span check (it is structural, not two-shot body).

    body[0]=wide+ci=[[0,0.6]] (close 0.6s, wide 3.4s tail) → body[1]=close 8s.
    A-B-A: close(0.6s)→wide(3.4s)→close fires on body spans, NOT shifted by cold_open.
    Output times are body-relative (< 4s), proving cold_open was excluded.
    """
    from autoreels.__main__ import _stage_two_shot_auto
    segs = [
        _seg(0.0, 4.0, "wide", [[0.0, 0.6]]),  # wide+ci: close(0.6s)+wide(3.4s tail)
        _seg(5.0, 13.0, "close"),               # close 8s
    ]
    reel = _reel(segs)
    reel.cold_open = _seg(50.0, 54.0, "close")  # 4s cold_open, excluded from check

    _stage_two_shot_auto([reel], [], render_cfg=_cfg())

    warns = getattr(reel, "_two_shot_warnings", [])
    errors = [w for w in warns if "[ERROR]" in w]
    # A-B-A fires for the body: close(0.6s)→wide(3.4s)→close
    assert any("A-B-A" in e or "middle" in e for e in errors), (
        f"expected [ERROR] A-B-A middle for body close→wide(3.4s)→close; got {warns}"
    )
    # Output times must be body-relative (≤ 4s), proving cold_open was NOT prepended
    assert all(
        not (("A-B-A" in e or "middle" in e) and
             any(float(t) > 4.0 for t in __import__("re").findall(r"\d+\.\d+", e)))
        for e in errors
    ), f"[ERROR] output times must be body-relative (≤4s, cold_open excluded); got {errors}"
