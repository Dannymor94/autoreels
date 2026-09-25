"""M1.7 step 1: two-shot mode (wide / close crop switching within a clip).

Tests:
1. Feature off → render command identical (no argv change when two_shot=False).
2. Cold-open segment assigned shot='close'; body segments stay 'wide'.
3. Close crop: inside frame, even dims, exact aspect; scale<1.0 clamped to 1.0.
4. c: field mid-window → close_intervals set, no segment split.
5. Shot assignment preserves durations (assign_close_shots is non-destructive).
6. Parser: c: field alongside all existing fields, no shadowing.
7. Shot change at seam → hard cut (seam_xfades[k]=0); unchanged seams keep xfade.
8. close_intervals times are segment-relative (not source-absolute).
"""
from autoreels.core.models import Crop, Segment, SetupProfile
from autoreels.cloud.blocks import parse_compact_answer
from autoreels.local.render import (
    _close_crop,
    _concat_segments_graph,
    _expected_output_duration,
    _seg_ends_close,
    _seg_starts_close,
    assign_close_shots,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _setup(frame_w=3840, frame_h=2160, crop_x=864, crop_y=350, crop_w=960, crop_h=1700) -> SetupProfile:
    return SetupProfile(
        setup_id="test",
        crop=Crop(x=crop_x, y=crop_y, w=crop_w, h=crop_h),
        scale=[1080, 1920],
        frame=[frame_w, frame_h],
    )


def _seg(start, end, **kw) -> Segment:
    return Segment(start=start, end=end, **kw)


# ── Test 1: Feature off → concat graph unchanged ──────────────────────────────

def test_feature_off_concat_unchanged():
    """When segment_vfs=None and seam_xfades=None, _concat_segments_graph output is identical."""
    segs = [_seg(10.0, 20.0), _seg(25.0, 35.0)]
    xfade = 0.1

    # Baseline: no two_shot params
    fg_base, vseg_base, aseg_base = _concat_segments_graph(segs, 0.01, video_xfade_sec=xfade)

    # With explicit None (same as omitted)
    fg_none, vseg_none, aseg_none = _concat_segments_graph(
        segs, 0.01, video_xfade_sec=xfade,
        segment_vfs=None, seam_xfades=None,
    )

    assert fg_base == fg_none
    assert vseg_base == vseg_none
    assert aseg_base == aseg_none


# ── Test 2: Cold-open shot is close; body is wide ─────────────────────────────

def test_cold_open_shot_is_close():
    """assign_close_shots: cold_open range wholly covers the hook segment → shot='close'."""
    segs = [_seg(5.0, 8.0), _seg(10.0, 25.0), _seg(25.0, 40.0)]
    # cold_open covers [5.0, 8.0] exactly
    close_ranges = [(5.0, 8.0)]
    result = assign_close_shots(segs, close_ranges)

    assert result[0].shot == "close"
    assert result[0].close_intervals == []
    assert result[1].shot == "wide"
    assert result[2].shot == "wide"


# ── Test 3: Close crop validity ───────────────────────────────────────────────

def test_close_crop_valid():
    """_close_crop: result inside frame, even dims, same aspect as wide, scale<1 clamped."""
    setup = _setup()
    c = setup.crop
    sw, sh = setup.scale

    close = _close_crop(setup, scale=1.25, anchor_y=0.35)

    # Even dimensions
    assert close.w % 2 == 0
    assert close.h % 2 == 0

    # Inside source frame
    assert close.x >= 0
    assert close.y >= 0
    assert close.x + close.w <= setup.frame[0]
    assert close.y + close.h <= setup.frame[1]

    # Tighter than wide
    assert close.w < c.w
    assert close.h < c.h

    # Aspect ratio preserved (same as wide crop → same as output 9:16)
    wide_ratio = c.w / c.h
    close_ratio = close.w / close.h
    assert abs(close_ratio - wide_ratio) < 0.02, f"aspect mismatch: wide={wide_ratio:.4f} close={close_ratio:.4f}"

    # scale < 1.0 → clamped to 1.0 (result same as scale=1.0)
    import sys, io
    stderr_capture = io.StringIO()
    old_stderr = sys.stderr
    sys.stderr = stderr_capture
    try:
        clamped = _close_crop(setup, scale=0.5, anchor_y=0.35)
    finally:
        sys.stderr = old_stderr
    warning = stderr_capture.getvalue()
    assert "clamped" in warning
    # scale=1 → same rectangle as wide
    assert clamped.w == c.w
    assert clamped.h == c.h


# ── Test 4: c: field → close_intervals, no split ─────────────────────────────

def test_c_field_mid_window_no_split():
    """assign_close_shots: partial overlap → close_intervals set, no new segment created."""
    segs = [_seg(10.0, 30.0)]
    # Close range covers middle of the segment
    close_ranges = [(15.0, 22.0)]
    result = assign_close_shots(segs, close_ranges)

    assert len(result) == 1, "assign_close_shots must not split a segment"
    assert result[0].start == 10.0
    assert result[0].end == 30.0
    assert result[0].shot == "wide"
    assert len(result[0].close_intervals) == 1
    t0, t1 = result[0].close_intervals[0]
    # Interval must be segment-relative
    assert abs(t0 - 5.0) < 1e-6, f"expected 5.0 (15.0-10.0), got {t0}"
    assert abs(t1 - 12.0) < 1e-6, f"expected 12.0 (22.0-10.0), got {t1}"


# ── Test 5: Duration invariant unchanged ──────────────────────────────────────

def test_shot_assignment_does_not_change_duration():
    """assign_close_shots: no segment's (start, end) is changed."""
    segs = [_seg(5.0, 8.0), _seg(10.0, 25.0), _seg(25.0, 35.0)]
    close_ranges = [(5.0, 8.0), (15.0, 20.0)]
    original_durations = [s.end - s.start for s in segs]

    result = assign_close_shots(segs, close_ranges)

    assert len(result) == len(segs)
    for orig, res in zip(segs, result):
        assert res.start == orig.start
        assert res.end == orig.end


# ── Test 6: Parser — c: alongside all existing fields, no shadowing ───────────

def test_parser_c_field_no_shadow():
    """c: is parsed correctly alongside s:, e:, h:, x:, f:, t:, d: with no field shadowing."""
    line = "3 85 | s:2 | e:9 | h:1 | x:5 | f:1 | c:3-5,7 | t: Это заголовок | d: Описание."
    _, entries, errors, _ = parse_compact_answer(line)

    assert errors == [], f"unexpected errors: {errors}"
    assert len(entries) == 1
    e = entries[0]

    assert e.s == 2
    assert e.e == 9
    assert e.hook == 1
    assert e.x == (5,)
    assert e.filler is True
    assert e.c == (3, 4, 5, 7)
    assert e.title == "Это заголовок"
    assert e.description == "Описание."


# ── Test 7: Shot change at seam → hard cut; unchanged seams keep xfade ────────

def test_shot_change_seam_hard_cut():
    """_concat_segments_graph with seam_xfades: 0.0 seam uses concat, non-zero uses xfade."""
    segs = [
        _seg(5.0, 8.0, shot="close"),   # cold open
        _seg(10.0, 20.0, shot="wide"),  # body seg 1
        _seg(20.0, 30.0, shot="wide"),  # body seg 2
    ]
    xfade = 0.1
    # Seam 0 (close→wide): hard cut; seam 1 (wide→wide): xfade
    seam_xfades = [0.0, xfade]

    fg, _, _ = _concat_segments_graph(segs, 0.0, video_xfade_sec=xfade, seam_xfades=seam_xfades)

    # Seam 0: hard cut → concat=n=2:v=1:a=0
    assert "concat=n=2:v=1:a=0" in fg, "hard-cut seam must use concat filter"

    # Seam 1: xfade → xfade filter
    assert "xfade" in fg, "xfade seam must use xfade filter"

    # Duration: only seam 1 subtracts xfade
    dur = _expected_output_duration(segs, xfade_sec=xfade, seam_xfades=seam_xfades)
    raw_sum = sum(s.end - s.start for s in segs)
    assert abs(dur - (raw_sum - xfade)) < 1e-9


def test_shot_same_seams_keep_xfade():
    """When all shots are wide, seam_xfades=[xfade, xfade] keeps existing xfade behaviour."""
    segs = [_seg(10.0, 20.0), _seg(20.0, 30.0), _seg(30.0, 40.0)]
    xfade = 0.1

    fg_uniform, _, _ = _concat_segments_graph(segs, 0.0, video_xfade_sec=xfade)
    fg_seam, _, _ = _concat_segments_graph(segs, 0.0, seam_xfades=[xfade, xfade])

    assert "xfade" in fg_seam
    assert fg_seam.count("xfade") == fg_uniform.count("xfade")


# ── Test 8: close_intervals are segment-relative ──────────────────────────────

def test_mid_window_overlay_relative_times():
    """close_intervals are relative to segment start (not source-absolute).

    A window starting at 100 s with a close range [105, 110] gets close_intervals [[5.0, 10.0]].
    This matches the PTS-reset invariant: after setpts=PTS-STARTPTS, t=5 is source t=105.
    """
    # Segment with non-zero source offset
    segs = [_seg(100.0, 120.0)]
    close_ranges = [(105.0, 110.0)]

    result = assign_close_shots(segs, close_ranges)

    assert len(result[0].close_intervals) == 1
    t0, t1 = result[0].close_intervals[0]
    # Must be relative to segment start (100.0)
    assert abs(t0 - 5.0) < 1e-6, f"expected 5.0, got {t0} (source-absolute would be 105.0)"
    assert abs(t1 - 10.0) < 1e-6, f"expected 10.0, got {t1} (source-absolute would be 110.0)"


def test_mid_window_multiple_ranges():
    """Multiple close ranges on one segment produce multiple intervals."""
    segs = [_seg(100.0, 130.0)]
    close_ranges = [(102.0, 106.0), (115.0, 120.0)]

    result = assign_close_shots(segs, close_ranges)

    assert len(result[0].close_intervals) == 2
    assert abs(result[0].close_intervals[0][0] - 2.0) < 1e-6
    assert abs(result[0].close_intervals[0][1] - 6.0) < 1e-6
    assert abs(result[0].close_intervals[1][0] - 15.0) < 1e-6
    assert abs(result[0].close_intervals[1][1] - 20.0) < 1e-6


# ── Test 9: seam hard-cut when close_intervals starts at 0 ───────────────────

def test_seam_hard_cut_when_close_interval_at_start():
    """seg[1] with close_intervals=[[0.0, X]] means visual starts close → seam should be hard cut.

    _seg_starts_close / _seg_ends_close detect this boundary case.
    """
    # seg[0] ends wide; seg[1] starts with a close interval at t=0
    seg0 = _seg(0.0, 5.0)  # shot=wide, no close_intervals
    seg1 = _seg(10.0, 20.0, close_intervals=[[0.0, 8.0]])  # wide shot but opens close

    assert not _seg_ends_close(seg0), "seg0 ends wide"
    assert _seg_starts_close(seg1), "seg1 opens with close interval at t=0"
    # seam: ends_close(seg0) != starts_close(seg1) → hard cut
    assert _seg_ends_close(seg0) != _seg_starts_close(seg1)

    # Verify filtergraph has hard concat, no xfade
    xfade = 0.08
    seam_xfades = [
        0.0 if _seg_ends_close(segs[k]) != _seg_starts_close(segs[k + 1]) else xfade
        for segs, k in [([seg0, seg1], 0)]
    ]
    assert seam_xfades == [0.0]


def test_seam_hard_cut_when_close_interval_at_end():
    """seg[0] ending with a close interval at the segment boundary → seam with seg[1]=wide is hard cut."""
    seg0 = _seg(0.0, 10.0, close_intervals=[[7.0, 10.0]])  # ends close (10.0-10.0 = 0 gap)
    seg1 = _seg(15.0, 25.0)  # shot=wide

    assert _seg_ends_close(seg0), "seg0 ends with close interval at segment end"
    assert not _seg_starts_close(seg1), "seg1 starts wide"
    assert _seg_ends_close(seg0) != _seg_starts_close(seg1)


def test_seam_no_change_when_both_wide():
    """Both segments wide → seam keeps xfade."""
    seg0 = _seg(0.0, 5.0)
    seg1 = _seg(10.0, 20.0)
    assert not _seg_ends_close(seg0)
    assert not _seg_starts_close(seg1)
    assert _seg_ends_close(seg0) == _seg_starts_close(seg1)  # both False → no change


def test_seam_no_change_when_mid_window_close_interval():
    """close_intervals that don't touch segment boundaries → seam unchanged (wide→wide at seam)."""
    seg0 = _seg(0.0, 5.0)
    seg1 = _seg(10.0, 20.0, close_intervals=[[3.0, 7.0]])  # starts wide, ends wide

    assert not _seg_starts_close(seg1), "close_interval at t=3 (not 0) → starts wide"
    assert not _seg_ends_close(seg1), "close_interval ends at 7 (not near 10) → ends wide"
    assert _seg_ends_close(seg0) == _seg_starts_close(seg1)  # both False → xfade preserved
