"""Part 1: a reel is an ordered list of source segments concatenated at render.

Covers the structural foundation only (the render stop-check — single-segment output identical to
the current renderer — is verified by an actual render, not here):

1. A legacy single-span reel reads as one segment; playback duration == span.
2. remap_to_output puts each word at (offset-in-segment + accumulated prior durations) and drops a
   word that falls in a removed gap (three-segment case).
3. _concat_segments_graph trims each segment relative to the seek base and joins video hard /
   audio with acrossfade; build_concat_cmd fast-seeks the input to the first segment.
4. A single-segment reel still routes through the fast -ss/-t build_cut_cmd (no concat graph).
"""
import pytest

from autoreels.core.models import Reel, Segment, Word
from autoreels.local.render import _concat_segments_graph, build_concat_cmd
from autoreels.local.subtitles import remap_to_output


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
def test_concat_graph_trims_relative_and_edge_fades():
    segs = [Segment(start=100.0, end=118.0), Segment(start=123.0, end=140.0)]
    graph, vseg, aseg = _concat_segments_graph(segs, 0.01, base=100.0)
    assert (vseg, aseg) == ("[vseg]", "[aseg]")
    # trims are relative to base=100 → first segment starts at 0, not 100
    assert "trim=start=0.000:end=18.000" in graph
    assert "trim=start=23.000:end=40.000" in graph
    assert "concat=n=2:v=1:a=0[vseg]" in graph      # video hard concat
    assert "concat=n=2:v=0:a=1[aseg]" in graph      # audio also plain concat (no overlap → no drift)
    assert "acrossfade" not in graph                 # NOT a crossfade
    # non-overlapping edge fades: fade-in at 0, fade-out near each segment's own end (18s, 17s)
    assert "afade=t=in:st=0:d=0.01" in graph
    assert "afade=t=out:st=17.99:d=0.01" in graph    # 18.0 - 0.01
    assert "afade=t=out:st=16.99:d=0.01" in graph    # 17.0 - 0.01


def test_concat_graph_zero_fade_hard_joins_audio():
    segs = [Segment(start=0.0, end=5.0), Segment(start=10.0, end=15.0)]
    graph, _, _ = _concat_segments_graph(segs, 0.0)
    assert "afade" not in graph
    assert "concat=n=2:v=0:a=1[aseg]" in graph


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


def test_build_concat_cmd_fast_seeks_first_segment():
    cmd = build_concat_cmd("ffmpeg", "src.mp4", "out.mp4", filter_complex="[0:v]null[v];[0:a]anull[a]",
                           codec="libx264", preset="fast", seek=100.0,
                           audio_codec="aac", audio_bitrate="128k")
    assert cmd[:1] == ["ffmpeg"]
    assert "-ss" in cmd and cmd[cmd.index("-ss") + 1] == "100.000"
    # seek precedes the input so it fast-seeks the decoder
    assert cmd.index("-ss") < cmd.index("-i")
    assert "-filter_complex" in cmd and cmd[-1] == "out.mp4"
    assert cmd[cmd.index("-map") + 1] == "[v]"
    assert "-shortest" in cmd    # clamp audio to the (authoritative) video length → equal durations
