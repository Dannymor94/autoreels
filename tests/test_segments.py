"""Part 1: a reel is an ordered list of source segments concatenated at render.

Covers the structural foundation only (the render stop-check — single-segment output identical to
the current renderer — is verified by an actual render, not here):

1. A legacy single-span reel reads as one segment; playback duration == span.
2. remap_to_output puts each word at (offset-in-segment + accumulated prior durations) and drops a
   word that falls in a removed gap (three-segment case).
3. _concat_segments_graph joins one pre-seeked input per window (video hard, audio edge-faded);
   build_concat_cmd opens each window as its own input with input-side seek.
4. A single-segment reel still routes through the fast -ss/-t build_cut_cmd (no concat graph).
"""
from pathlib import Path

import pytest

from autoreels.core.config import load_subtitles_config
from autoreels.core.models import Reel, Segment, Word
from autoreels.local.render import (
    RenderError,
    _assert_windows_frame_aligned,
    _concat_segments_graph,
    _snap_windows_to_frames,
    build_concat_cmd,
)
from autoreels.local.subtitles import build_ass, remap_to_output

_SUB_CFG = load_subtitles_config(Path(__file__).resolve().parents[1] / "config" / "subtitles.yaml")


def _reel(**kw):
    base = dict(id="r", start=10.0, end=50.0, score=80, hook="h", title="", description="")
    base.update(kw)
    return Reel(**base)


# --- 1: legacy single-span reads as one segment --------------------------------------------
def test_legacy_reel_is_one_segment():
    r = _reel(start=10.0, end=50.0)
    segs = r.effective_segments()
    assert len(segs) == 1 and (segs[0].start, segs[0].end) == (10.0, 50.0)
    assert r.playback_duration() == 40.0


def test_segments_playback_drops_gaps():
    r = _reel(start=0.0, end=100.0,
              segments=[Segment(start=0.0, end=20.0), Segment(start=60.0, end=90.0)])
    # span is 100 but only 20 + 30 = 50s actually play
    assert r.playback_duration() == 50.0
    assert (r.start, r.end) == (0.0, 100.0)  # span preserved for range-only tools


# --- 2: subtitle remap onto the output timeline --------------------------------------------
def test_remap_three_segments_drops_gap_word():
    words = [
        Word(word="a", t0=0.0, t1=1.0),     # seg0
        Word(word="b", t0=1.0, t1=2.0),     # seg0
        Word(word="gap", t0=5.0, t1=6.0),   # in removed gap → dropped
        Word(word="c", t0=10.0, t1=11.0),   # seg1
        Word(word="d", t0=20.0, t1=21.0),   # seg2
    ]
    segs = [Segment(start=0.0, end=2.0), Segment(start=10.0, end=12.0),
            Segment(start=20.0, end=22.0)]
    out = remap_to_output(words, segs)
    assert [w.word for w in out] == ["a", "b", "c", "d"]        # gap word dropped
    # a,b keep their times (seg0 starts at 0, offset 0)
    assert (out[0].t0, out[1].t0) == (0.0, 1.0)
    # c: offset-in-seg1 (10-10=0) + prior durations (2.0) = 2.0
    assert out[2].t0 == 2.0
    # d: offset-in-seg2 (20-20=0) + prior durations (2.0 + 2.0) = 4.0
    assert out[3].t0 == 4.0


def test_remap_single_segment_equals_shift():
    words = [Word(word="x", t0=12.0, t1=13.0), Word(word="y", t0=14.0, t1=15.0)]
    out = remap_to_output(words, [Segment(start=10.0, end=50.0)])
    # single segment == shift by start; identical to build_ass(clip_start=start)
    assert [(w.t0, w.t1) for w in out] == [(2.0, 3.0), (4.0, 5.0)]


# --- 3: concat filtergraph + command --------------------------------------------------------
def test_concat_graph_joins_per_input_windows_with_edge_fades():
    segs = [Segment(start=100.0, end=118.0), Segment(start=123.0, end=140.0)]
    graph, vseg, aseg = _concat_segments_graph(segs, 0.01)
    assert (vseg, aseg) == ("[vseg]", "[aseg]")
    # Each window is its own input [i:v]/[i:a] (pre-seeked); we only reset PTS — no shared-decode trim
    assert "[0:v]setpts=PTS-STARTPTS,settb=expr=1/90000[v0]" in graph
    assert "[1:v]setpts=PTS-STARTPTS,settb=expr=1/90000[v1]" in graph
    assert "trim=" not in graph                       # no trimming of a single shared decode
    assert "concat=n=2:v=1:a=0[vseg]" in graph        # video hard concat
    assert "concat=n=2:v=0:a=1[aseg]" in graph        # audio also plain concat (no overlap → no drift)
    assert "acrossfade" not in graph                   # NOT a crossfade
    # non-overlapping edge fades: fade-in at 0, fade-out near each segment's own end (18s, 17s)
    assert "afade=t=in:st=0:d=0.01" in graph
    assert "afade=t=out:st=17.99:d=0.01" in graph      # 18.0 - 0.01
    assert "afade=t=out:st=16.99:d=0.01" in graph      # 17.0 - 0.01


def test_concat_graph_zero_fade_hard_joins_audio():
    segs = [Segment(start=0.0, end=5.0), Segment(start=10.0, end=15.0)]
    graph, _, _ = _concat_segments_graph(segs, 0.0)
    assert "afade" not in graph
    assert "concat=n=2:v=0:a=1[aseg]" in graph


def test_concat_graph_overlay_path_has_settb():
    """Overlay path must emit settb=expr=1/90000 so xfade seams don't get a 1/600 timebase."""
    segs = [Segment(start=0.0, end=5.0), Segment(start=10.0, end=15.0)]
    ovl = [("crop=1080:1920:0:0,scale=1080:1920", "crop=540:960:270:480,scale=1080:1920",
            "between(t,0,5)"), None]
    graph, _, _ = _concat_segments_graph(segs, 0.01, segment_overlays=ovl)
    assert "settb=expr=1/90000[v0]" in graph
    assert "settb=expr=1/90000[v1]" in graph


def test_concat_graph_mixed_seam_hard_cut_has_settb():
    """Mixed seam_xfades: hard-cut seam uses concat+settb so a following xfade sees 1/90000."""
    segs = [Segment(start=0.0, end=5.0), Segment(start=10.0, end=15.0),
            Segment(start=20.0, end=25.0)]
    graph, _, _ = _concat_segments_graph(segs, 0.01, seam_xfades=[0.0, 0.1])
    assert "concat=n=2:v=1:a=0,settb=expr=1/90000" in graph


# --- Part 4: title plate renders only for its duration and does not overlap subtitles -------
def test_title_plate_only_when_given_and_bounded():
    words = [Word(word="привет", t0=0.0, t1=0.5), Word(word="мир", t0=0.5, t1=1.0)]
    # No title → no plate.
    assert "Style: Title" not in build_ass(words, cfg=_SUB_CFG, clip_start=0.0)
    # With title → a Title style + one Dialogue spanning exactly [0, title_lead_sec].
    ass = build_ass(words, cfg=_SUB_CFG, clip_start=0.0, title="Сожми книгу до одной сутры")
    assert "Style: Title" in ass
    title_lines = [l for l in ass.splitlines() if l.startswith("Dialogue:") and ",Title,," in l]
    assert len(title_lines) == 1, title_lines
    end = title_lines[0].split(",")[2]
    assert end == "0:00:03.50", end                     # cfg.title_lead_sec = 3.5
    assert "\\N" in title_lines[0]                        # long title wrapped, not clipped


def test_title_plate_does_not_overlap_subtitles():
    # Title style is top-aligned (8); subtitle Default is bottom (2). Their vertical zones are
    # disjoint: title MarginV is measured from the top, subtitle position_v from the bottom.
    ass = build_ass([Word(word="w", t0=0.0, t1=0.5)], cfg=_SUB_CFG, clip_start=0.0, title="T")
    title_style = next(l for l in ass.splitlines() if l.startswith("Style: Title"))
    default_style = next(l for l in ass.splitlines() if l.startswith("Style: Default"))
    # field order: …, Alignment(19th), MarginL, MarginR, MarginV, Encoding
    assert title_style.split(",")[18] == "8"             # top-centre
    assert default_style.split(",")[18] == str({"center": 2, "left": 1, "right": 3}[_SUB_CFG.alignment])


# --- invariant: segments must stay consistent with the reel's final bounds -----------------
def test_check_segments_rejects_first_segment_before_start():
    # A reel whose start was moved forward (e.g. dangling repair) AFTER segments were built:
    # the first segment still begins at the old position → must be rejected, not rendered.
    r = _reel(start=10.0, end=50.0,
              segments=[Segment(start=8.0, end=20.0), Segment(start=30.0, end=50.0)])
    with pytest.raises(ValueError, match="segments\\[0\\].start"):
        r.check_segments()


def test_check_segments_accepts_consistent_and_single_span():
    _reel(start=10.0, end=50.0).check_segments()   # single span: always valid
    _reel(start=10.0, end=50.0,
          segments=[Segment(start=10.0, end=20.0), Segment(start=30.0, end=50.0)]).check_segments()


def test_check_segments_rejects_overlap_and_end_mismatch():
    with pytest.raises(ValueError, match="unordered or overlapping"):
        _reel(start=0.0, end=50.0,
              segments=[Segment(start=0.0, end=25.0), Segment(start=20.0, end=50.0)]).check_segments()
    with pytest.raises(ValueError, match="segments\\[-1\\].end"):
        _reel(start=0.0, end=50.0,
              segments=[Segment(start=0.0, end=20.0), Segment(start=30.0, end=60.0)]).check_segments()


def test_build_concat_cmd_opens_each_window_as_its_own_input():
    # A hook window (later in the source) BEFORE the body window in playback order — each opens as
    # its own input with input-side -ss/-t, so decodes are independent (no buffering → no OOM).
    cmd = build_concat_cmd("ffmpeg", "src.mp4", "out.mp4",
                           windows=[(200.0, 5.0), (100.0, 18.0)],
                           filter_complex="[0:v]null[v];[0:a]anull[a]",
                           codec="libx264", preset="fast",
                           audio_codec="aac", audio_bitrate="128k")
    assert cmd[:1] == ["ffmpeg"]
    # two inputs, each with its own input-side seek + duration, -ss/-t before that -i
    i0 = cmd.index("-i")
    assert cmd[:i0].count("-ss") == 1 and cmd[:i0].count("-t") == 1
    assert cmd[cmd.index("-ss") + 1] == "200.000" and cmd[cmd.index("-t") + 1] == "5.000"
    i1 = cmd.index("-i", i0 + 1)
    assert cmd[i0 + 1:i1 + 1].count("-ss") == 1     # second window's seek precedes its input
    assert cmd.count("-i") == 2
    assert "-filter_complex" in cmd and cmd[-1] == "out.mp4"
    assert cmd[cmd.index("-map") + 1] == "[v]"
    assert "-shortest" in cmd    # clamp audio to the (authoritative) video length → equal durations


# --- frame-grid snap: multi-window windows must be whole frames (no lip-sync drift) -----------
def test_snap_windows_makes_every_window_whole_frames():
    # Arbitrary (non-frame-aligned) boundaries taken from the r11 regression.
    segs = [Segment(start=2414.798719, end=2421.468719),
            Segment(start=2422.578719, end=2444.108719),
            Segment(start=2444.738719, end=2467.478719)]
    fps = 30.0
    snapped = _snap_windows_to_frames(segs, fps)
    for s in snapped:
        frames = (s.end - s.start) * fps
        assert abs(frames - round(frames)) < 1e-6, f"{s} is not a whole number of frames"
    # boundaries move by at most half a frame
    for orig, snap in zip(segs, snapped):
        assert abs(snap.start - orig.start) <= 0.5 / fps + 1e-9
        assert abs(snap.end - orig.end) <= 0.5 / fps + 1e-9


def test_frame_aligned_invariant_passes_on_whole_frames_and_fails_on_drift():
    fps = 30.0
    # snapped windows → whole frames → invariant holds
    segs = _snap_windows_to_frames(
        [Segment(start=100.017, end=106.673), Segment(start=200.331, end=222.118)], fps)
    windows = [(s.start, s.end - s.start) for s in segs]
    _assert_windows_frame_aligned(windows, fps)     # no raise
    # a window off by ~half a frame → invariant catches it (this is exactly the drift source)
    with pytest.raises(RenderError, match="not frame-aligned"):
        _assert_windows_frame_aligned([(0.0, 5.0), (0.0, 6.6667 + 0.5 / fps)], fps)


# --- tail air: exactly tail_pad_sec after the last heard word, on every path ------------------
from autoreels.__main__ import _apply_tail_air, _check_tail_air
from autoreels.cloud.edit import remove_fillers

_FR = dict(filler_words=["ну", "вот"], pause_shorten_sec=0.8, pause_residual_sec=0.25,
           max_removed_share=0.25)


def _tail_reel(**kw):
    base = dict(id="r", start=0.0, end=0.0, score=80, hook="h", title="", description="")
    base.update(kw)
    return Reel(**base)


def test_explicit_e_ends_tail_pad_after_last_word():
    # An explicit e: lands the end exactly on the last word (no air); the tail step adds it back.
    words = [Word(word="Раз.", t0=0.0, t1=0.5), Word(word="Два.", t0=1.0, t1=1.5),
             Word(word="конец.", t0=2.0, t1=2.5), Word(word="Дальше", t0=3.4, t1=3.9)]
    r = _tail_reel(start=0.0, end=2.5)               # e: put the end on «конец.» — zero air
    _apply_tail_air([r], words, tail_pad_sec=0.7, video_duration=10.0)
    assert abs(r.end - (2.5 + 0.7)) < 1e-6           # exactly tail_pad after the last word
    assert _check_tail_air([r], tail_pad_sec=0.7, video_duration=10.0) is None


def test_filler_removal_leaves_trailing_air_intact():
    # Padding put 0.7s of air after the last word; a mid-clip filler is cut, the tail is untouched.
    words = [Word(word="Смысл", t0=0.0, t1=0.4), Word(word="такой.", t0=0.5, t1=1.0),
             Word(word="ну,", t0=1.2, t1=1.6), Word(word="дальше.", t0=2.0, t1=2.5)]
    end = 2.5 + 0.7                                   # last word + tail_pad (post-padding end)
    segs, removed, cuts = remove_fillers(words, 0.0, end, **_FR)
    assert cuts == 1 and removed > 0                  # the standalone «ну,» was cut
    assert abs(segs[-1].end - end) < 1e-6             # trailing air preserved (not shortened)


def test_multisegment_reel_keeps_tail_air():
    # Two body segments; the tail step extends the LAST segment to last_word + tail_pad.
    words = [Word(word="a", t0=0.0, t1=0.5), Word(word="b.", t0=1.0, t1=1.9),
             Word(word="c", t0=3.0, t1=3.5), Word(word="итог.", t0=4.0, t1=4.8),
             Word(word="Следующее", t0=6.0, t1=6.5)]
    r = _tail_reel(start=0.0, end=4.8,
                   segments=[Segment(start=0.0, end=1.9), Segment(start=3.0, end=4.8)])
    _apply_tail_air([r], words, tail_pad_sec=0.7, video_duration=20.0)
    assert abs(r.segments[-1].end - (4.8 + 0.7)) < 1e-6
    assert abs(r.end - (4.8 + 0.7)) < 1e-6
    # played length = seg0 (1.9) + seg1 (extended to 5.5-3.0=2.5) = 4.4
    assert abs(r.playback_duration() - (1.9 + 2.5)) < 1e-6
    r.check_segments()                                # invariant still holds


def test_apply_tail_air_records_intruder_pulled_into_tail():
    # The next phrase «Следующее» starts 40 ms after the last intended word, inside the 0.7s air.
    # It is trimmed out of subtitles, so the intruder start must be recorded from the full words.
    words = [Word(word="итог.", t0=1.5, t1=2.0), Word(word="Следующее", t0=2.04, t1=2.6)]
    r = _tail_reel(start=0.0, end=2.0)                 # end on the last intended word
    _apply_tail_air([r], words, tail_pad_sec=0.7, video_duration=20.0)
    assert abs(r.tail_last_word_end - 2.0) < 1e-6
    assert abs(r.tail_next_word_start - 2.04) < 1e-6   # intruder recorded from the transcript
    assert abs(r.end - 2.7) < 1e-6                      # tail_pad still added


def test_apply_tail_air_records_intruder_that_butts_against_last_word():
    # The worst case (r01/r05/r10 in the PXL export): the next phrase starts the instant the last
    # word ends (0 ms gap). It must still be recorded, not mistaken for the last intended word.
    words = [Word(word="любили.", t0=1.4, t1=2.0), Word(word="Наверное,", t0=2.0, t1=2.5)]
    r = _tail_reel(start=0.0, end=2.0)
    _apply_tail_air([r], words, tail_pad_sec=0.7, video_duration=20.0)
    assert abs(r.tail_last_word_end - 2.0) < 1e-6
    assert abs(r.tail_next_word_start - 2.0) < 1e-6    # intruder at exactly lw_end still caught


def test_apply_tail_air_clean_tail_records_no_intruder():
    words = [Word(word="итог.", t0=1.5, t1=2.0), Word(word="Далеко", t0=5.0, t1=5.5)]  # next word past tail
    r = _tail_reel(start=0.0, end=2.0)
    _apply_tail_air([r], words, tail_pad_sec=0.7, video_duration=20.0)
    assert r.tail_next_word_start is None              # nothing inside the 0.7s air → clean




# --- M1.7 step 1c: beat reels (non-monotonic segments) ---------------------------------

def test_check_segments_beat_reel_allows_nonmonotonic():
    # beat_gap_sec set → check_segments must NOT raise for non-monotonic source order.
    # Sentence 3 (t=100-110) played first, then sentence 1 (t=10-20) — classic reorder.
    r = _reel(start=100.0, end=20.25,
              segments=[Segment(start=100.0, end=110.25), Segment(start=10.0, end=20.25)],
              beat_gap_sec=0.25)
    r.check_segments()   # must not raise


def test_check_segments_beat_reel_still_rejects_empty_segment():
    # Even beat reels must not contain zero-length segments.
    r = _reel(start=100.0, end=20.0,
              segments=[Segment(start=100.0, end=100.0), Segment(start=10.0, end=20.0)],
              beat_gap_sec=0.25)
    with pytest.raises(ValueError, match="empty/reversed"):
        r.check_segments()


def test_beat_reel_playback_duration_is_sum_of_segments():
    # playback_duration sums all beat segments regardless of source order.
    segs = [Segment(start=100.0, end=110.25), Segment(start=10.0, end=20.25)]
    r = _reel(start=100.0, end=20.25, segments=segs, beat_gap_sec=0.25)
    assert abs(r.playback_duration() - (10.25 + 10.25)) < 1e-6


def test_beat_reel_concat_uses_hard_cuts():
    # _concat_segments_graph with beat segments and seam_xfades=[0.0] must produce
    # hard-cut concat (concat=n=2:v=1:a=0) rather than xfade.
    segs = [Segment(start=100.0, end=110.0), Segment(start=10.0, end=20.0)]
    prefix, vseg, aseg = _concat_segments_graph(
        segs, edge_fade_sec=0.01, seam_xfades=[0.0],
    )
    assert "concat=n=2:v=1:a=0" in prefix
    assert "xfade" not in prefix
