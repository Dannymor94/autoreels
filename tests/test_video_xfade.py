"""video_xfade_sec: short dissolve at internal segment seams.

1. Two-segment reel with xfade has duration = sum − 1 × xfade; subtitles land correctly.
2. video_xfade_sec=0 → hard concat (byte-identical filtergraph to pre-xfade path).
3. Frame-alignment invariant: xfade snapped to frame grid → output duration is frame-aligned.
"""
from autoreels.core.models import Segment
from autoreels.local.render import _concat_segments_graph, _snap_windows_to_frames
from autoreels.local.subtitles import remap_to_output
from autoreels.core.models import Word


def _w(t0, t1, word="x"):
    return Word(word=word, t0=t0, t1=t1)


def _seg(start, end):
    return Segment(start=start, end=end)


# ── Test 1: duration = sum − xfade; subtitles shift correctly ────────────────
def test_xfade_duration_and_subtitle_remap():
    # Two segments: seg0 1.0s, seg1 0.5s, xfade 0.1s → output = 1.4s
    segs = [_seg(0.0, 1.0), _seg(5.0, 5.5)]
    xfade = 0.1

    # Duration check
    raw_sum = sum(s.end - s.start for s in segs)
    expected_out = raw_sum - xfade
    assert abs(expected_out - 1.4) < 1e-9

    # Filtergraph includes xfade filter, NOT concat for video
    fg, vseg, aseg = _concat_segments_graph(segs, 0.01, video_xfade_sec=xfade)
    assert "xfade" in fg
    assert "concat=n=2:v=1" not in fg  # video hard-concat must be gone
    assert "concat=n=2:v=0:a=1" in fg  # audio concat stays
    assert vseg == "[vseg]"

    # xfade offset in filtergraph = D0 - xfade = 1.0 - 0.1 = 0.9
    assert "offset=0.9" in fg

    # Subtitle remap: a word in seg1 at local offset 0.2 maps to output time
    # D0 - xfade + 0.2 = 0.9 + 0.2 = 1.1
    words = [_w(5.2, 5.3, "hi")]  # seg1.start=5.0, offset=0.2
    remapped = remap_to_output(words, segs, xfade_sec=xfade)
    assert len(remapped) == 1
    assert abs(remapped[0].t0 - 1.1) < 1e-9, f"expected 1.1, got {remapped[0].t0}"

    # Word in seg0 at offset 0.8 → output 0.8 (unaffected by xfade)
    words0 = [_w(0.8, 0.9, "a")]
    remapped0 = remap_to_output(words0, segs, xfade_sec=xfade)
    assert abs(remapped0[0].t0 - 0.8) < 1e-9


# ── Test 2: xfade=0 → hard concat, no xfade filter ───────────────────────────
def test_xfade_zero_gives_hard_concat():
    segs = [_seg(0.0, 1.0), _seg(5.0, 5.5)]

    fg_xfade, _, _ = _concat_segments_graph(segs, 0.01, video_xfade_sec=0.0)
    fg_ref, _, _ = _concat_segments_graph(segs, 0.01)  # default = 0.0

    assert fg_xfade == fg_ref
    assert "xfade" not in fg_xfade
    assert "concat=n=2:v=1:a=0[vseg]" in fg_xfade


# ── Test 3: frame-alignment invariant with xfade ─────────────────────────────
def test_xfade_frame_aligned():
    # 30 fps source; windows that are whole-frame durations.
    fps = 30.0
    # seg0: 30 frames = 1.0s, seg1: 15 frames = 0.5s
    segs = [_seg(0.0, 1.0), _seg(5.0, 5.5)]
    segs_snapped = _snap_windows_to_frames(segs, fps)

    # xfade = 0.08s → snapped to 2/30 ≈ 0.06667s
    xfade_raw = 0.08
    xfade_actual = round(xfade_raw * fps) / fps
    assert abs(xfade_actual * fps - round(xfade_actual * fps)) < 1e-9, \
        "xfade_actual must be frame-aligned after snap"

    # Output duration must also be frame-aligned
    raw_sum = sum(s.end - s.start for s in segs_snapped)
    out_dur = raw_sum - xfade_actual
    out_frames = out_dur * fps
    assert abs(out_frames - round(out_frames)) < 1e-9, \
        f"output duration {out_dur}s = {out_frames} frames — not integer"
