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
    """A close span of 0.3 s (< min_shot=2.5 s) not fixable by snap or A-B-A → [ERROR].

    ci=[[0.0, 0.3]] creates close(0.3s) + wide(9.7s).
    Snap only extends WIDE prefixes/suffixes, not close spans.
    Only 2 spans — no A-B-A triplet context → A-B-A merge cannot fire.
    Pass 4 short-span check fires for close(0.3s) < 2.5s.
    """
    segs = [_seg(0.0, 10.0, "wide", [[0.0, 0.3]])]
    reel = _apply(segs)
    warns = getattr(reel, "_two_shot_warnings", [])
    errors = [w for w in warns if "[ERROR]" in w]
    assert errors, f"expected [ERROR] for 0.3 s close span; got warns={warns}"
    assert any("short" in e for e in errors), f"expected 'short' in [ERROR]; got {errors}"


def test_c_annotation_short_span_produces_warning_not_error():
    """c: annotation on a short sentence → [WARNING], not [ERROR].

    When _c_close_ranges matches the ci source time, Pass 4 downgrades to [WARNING].
    Without _c_close_ranges, the same ci still produces [ERROR] (auto-path stays strict).
    """
    from autoreels.__main__ import _stage_two_shot_auto

    # Segment with ci=[0.0, 0.72] matching a c: range of (0.0, 0.72)
    segs = [_seg(10.0, 20.72, "wide", [[0.0, 0.72]])]
    reel = _reel(segs)
    reel._c_close_ranges = [(10.0, 10.72)]  # source-time range matching the ci
    _stage_two_shot_auto([reel], [], render_cfg=_cfg())
    warns = getattr(reel, "_two_shot_warnings", [])
    errors = [w for w in warns if "[ERROR]" in w]
    warnings_only = [w for w in warns if "[WARNING]" in w and "short" in w]
    assert not errors, f"c: short span must not produce [ERROR]; got {errors}"
    assert warnings_only, f"expected [WARNING] for c: short span; got warns={warns}"

    # Same span without _c_close_ranges → still [ERROR]
    segs2 = [_seg(10.0, 20.72, "wide", [[0.0, 0.72]])]
    reel2 = _reel(segs2)
    _stage_two_shot_auto([reel2], [], render_cfg=_cfg())
    warns2 = getattr(reel2, "_two_shot_warnings", [])
    errors2 = [w for w in warns2 if "[ERROR]" in w and "short" in w]
    assert errors2, f"auto-path short span must still produce [ERROR]; got {warns2}"


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


# ── IMG_6848 r07: x:-cut segments with short ci spans fixed by snap+A-B-A ────

def test_img_r07_short_ci_spans_no_error():
    """r07 layout: wide+ci prefix 2.436s and ci close 1.993s → snap+A-B-A merge leaves no [ERROR].

    seg1(close 9.35s) → jump → seg2(wide ci=[[2.436,12.536],[20.176,26.517]] 26.517s)
    → jump → seg3(close 10.15s) → seg4(wide ci=[[3.74,5.64]] 5.733s)

    Snap: extends seg2 ci[0][0] from 2.436 to 0.0 (wide prefix < min_shot=2.5s).
    Snap: extends seg4 ci[-1][1] from 5.64 to 5.733 (wide tail < min_shot=2.5s).
    A-B-A merge: close→wide(3.74s)→close fires; seg4 becomes close (ci dropped + warn).
    Result: close(21.886s), wide(7.64s), close(22.224s) — no short spans.
    """
    from autoreels.__main__ import _stage_two_shot_auto, _shot_spans_output
    segs = [
        _seg(0.0,    9.35,  "close"),
        _seg(12.784, 39.301, "wide", [[2.436, 12.536], [20.176, 26.517]]),
        _seg(42.831, 52.981, "close"),
        _seg(53.771, 59.504, "wide", [[3.74, 5.64]]),
    ]
    reel = _reel(segs)
    _stage_two_shot_auto([reel], [], render_cfg=_cfg())
    warns = getattr(reel, "_two_shot_warnings", [])
    errors = [w for w in warns if "[ERROR]" in w]
    assert not errors, f"expected no [ERROR] for r07 layout; got {errors}"
    spans = _shot_spans_output(reel.effective_segments())
    short = [(t, a, e) for t, a, e in spans if e - a < 2.5]
    assert not short, f"expected no short spans after fix; got {short}"


# ── IMG_6848 r08: trailing wide < min_shot fixed by CI snap ──────────────────

def test_img_r08_trailing_ci_wide_no_error():
    """r08 layout: two wide+ci segs; seg1 has 0.35s wide tail, seg2 has 0.575s wide tail.

    seg1(wide ci=[[11.16,20.32],[20.32,21.94]] dur=22.29)
    → jump(9.48s) → seg2(wide ci=[[0,5.715],[14.195,20.945]] dur=21.52)

    Snap: extends seg1 ci[-1][1] from 21.94→22.29 (tail 0.35 < 2.5).
    Snap: extends seg2 ci[-1][1] from 20.945→21.52 (tail 0.575 < 2.5).
    Option-2: seg1 short tail absorbed into seg2's leading close.
    Result: wide(11.16s), close(16.845s), wide(8.48s), close(7.325s) — no short spans.
    """
    from autoreels.__main__ import _stage_two_shot_auto, _shot_spans_output
    segs = [
        _seg(1841.710, 1864.000, "wide", [[11.160, 20.32], [20.32, 21.94]]),
        _seg(1873.480, 1895.000, "wide", [[0.0, 5.715], [14.195, 20.945]]),
    ]
    reel = _reel(segs)
    _stage_two_shot_auto([reel], [], render_cfg=_cfg())
    warns = getattr(reel, "_two_shot_warnings", [])
    errors = [w for w in warns if "[ERROR]" in w]
    assert not errors, f"expected no [ERROR] for r08 layout; got {errors}"
    spans = _shot_spans_output(reel.effective_segments())
    short = [(t, a, e) for t, a, e in spans if e - a < 2.5]
    assert not short, f"expected no short spans after fix; got {short}"
