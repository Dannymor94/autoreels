"""REEL_SPEC §1.4 filler cut: fillers («э», «ммм» = untranscribed speech) and over-long pauses are
cut out of a planned window, a short pause is kept, cut edges never touch a word; the render
decodes the pieces of one window once (one input per run, not per piece)."""
import shutil
import subprocess

import pytest

from autoreels.cloud.plan import ManualPlanParams, PlannedWindow, build_manual_plan
from autoreels.core.models import Word, make_segment
from autoreels.local.render import _concat_segments_graph, _input_groups, build_concat_cmd

P = ManualPlanParams(filler_cut=True)


def _setup(words_spec, untranscribed):
    """words_spec: sentences of (word, start, end) with exact aligned times."""
    sents, words, al = [], [], []
    for sent in words_spec:
        cur = []
        for text, a, b in sent:
            w = Word(word=text, t0=a, t1=b)
            cur.append(w)
            words.append(w)
            al.append({"t0": a, "start": a, "end": b, "score": 0.9})
        sents.append(cur)
    smap = {"words": [{"t0": w.t0, "t1": w.t1, "audible_start": w.t0, "audible_end": w.t1} for w in words],
            "intervals": []}
    align = {"version": 1, "words": al, "untranscribed": untranscribed}
    return sents, words, smap, align


# one sentence: «раз» … filler 1.0–1.6 … «два» ; «три» after a 0.2 s gap (kept)
SPEC = [[("Раз", 0.0, 0.8), ("два", 1.8, 2.4), ("три.", 2.6, 3.2)],
        [("Четыре", 4.4, 5.0), ("пять.", 5.1, 5.8)]]


def test_filler_is_cut_with_short_pause_kept():
    sents, words, smap, align = _setup(SPEC, [[1.0, 1.6]])
    plan = build_manual_plan(sents, [1, 2], words=words, smap=smap, params=P, align=align)
    w = plan.body[0]
    # gap 0.8–1.8 holds the filler: keep min(0.05, silence) around each word → cut 0.85…1.75
    assert w.cuts[0] == [pytest.approx(0.85), pytest.approx(1.75)]
    # 2.4–2.6 gap (0.2 s, no filler) stays; 3.2–4.4 sentence pause (1.2 s) shortened to 0.25 s
    assert [pytest.approx(3.325), pytest.approx(4.275)] == w.cuts[1]
    assert len(w.cuts) == 2
    assert w.played == pytest.approx((w.end - w.start) - 0.9 - 0.95)


def test_cut_edges_stay_off_words_and_subtitles_in_played_pieces():
    sents, words, smap, align = _setup(SPEC, [[0.8, 1.8]])     # filler glued to both words
    plan = build_manual_plan(sents, [1, 2], words=words, smap=smap, params=P, align=align)
    c0, c1 = plan.body[0].cuts[0]
    assert c0 == pytest.approx(0.8 + P.edge_min_sec) and c1 == pytest.approx(1.8 - P.edge_min_sec)
    pieces = plan.body[0].pieces()
    for s in plan.subtitles:
        assert any(a <= s.t0 < b for a, b in pieces)


def test_off_by_default_and_short_or_capped():
    sents, words, smap, align = _setup(SPEC, [[1.0, 1.6]])
    assert build_manual_plan(sents, [1, 2], words=words, smap=smap, align=align).body[0].cuts == []
    tiny = ManualPlanParams(filler_cut=True, min_cut_sec=5.0)
    assert build_manual_plan(sents, [1, 2], words=words, smap=smap, params=tiny, align=align).body[0].cuts == []
    capped = ManualPlanParams(filler_cut=True, max_removed_share=0.17)
    cuts = build_manual_plan(sents, [1, 2], words=words, smap=smap, params=capped, align=align).body[0].cuts
    assert len(cuts) == 1 and cuts[0][0] > 3.0          # the larger removal wins the budget


def test_segments_split_and_close_spans_rebased():
    w = PlannedWindow(sentences=[1], start=10.0, end=20.0, shot="wide",
                      close_intervals=[[0.0, 4.0]], cuts=[[12.0, 13.0], [16.0, 17.0]])
    segs = w.segments()
    assert [(s.start, s.end) for s in segs] == [(10.0, 12.0), (13.0, 16.0), (17.0, 20.0)]
    assert [s.window_cut for s in segs] == [False, True, True]
    assert segs[0].shot == "close" and segs[0].close_intervals == []       # fully inside 0–4
    assert segs[1].shot == "wide" and segs[1].close_intervals == [[0.0, 1.0]]
    assert segs[2].shot == "wide" and segs[2].close_intervals == []
    assert PlannedWindow(sentences=[1], start=0.0, end=1.0, shot="wide").segments()[0].window_cut is False


def _seg(a, b, cut=False, shot="wide"):
    return make_segment(a, b).model_copy(update={"window_cut": cut, "shot": shot})


def test_input_groups_only_for_hard_cut_runs():
    segs = [_seg(0, 1), _seg(2, 3, True), _seg(4, 5, True), _seg(9, 10)]
    assert _input_groups(segs) == [[0, 1, 2], [3]]
    assert _input_groups(segs, seam_xfades=[0.0, 0.13, 0.0]) == [[0, 1], [2], [3]]
    plain = [_seg(0, 1), _seg(2, 3)]
    assert _input_groups(plain) == [[0], [1]]


def test_grouped_graph_selects_pieces_and_trims_audio_per_piece():
    segs = [_seg(10.0, 12.0), _seg(13.0, 16.0, True), _seg(30.0, 31.0)]
    fc, v, a = _concat_segments_graph(segs, 0.01, pre_roll=0.0, segment_vfs=["VF", "VF", "VF"],
                                      seam_xfades=[0.0, 0.0])
    assert "select='between(t,-0.001,1.998)+between(t,2.999,5.998)',setpts='PTS-(gte(T,2.999)*1)/TB'" in fc
    assert "asplit=2[s0_0][s0_1]" in fc and "atrim=start=3:end=6" in fc
    assert "[a0][a1][a2]concat=n=3:v=0:a=1[aseg]" in fc
    assert "[v0][v1]concat=n=2:v=1:a=0" in fc


ffmpeg = shutil.which("ffmpeg")
ffprobe = shutil.which("ffprobe")


@pytest.mark.skipif(not (ffmpeg and ffprobe), reason="ffmpeg/ffprobe not installed")
def test_grouped_render_has_exact_piece_durations(tmp_path):
    src = tmp_path / "src.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=12",
                    "-f", "lavfi", "-i", "sine=f=440:d=12:sample_rate=48000", "-shortest",
                    "-c:v", "libx264", "-g", "30", "-c:a", "aac", str(src)], check=True)
    segs = [_seg(1.0, 3.0), _seg(4.0, 6.0, True), _seg(7.0, 8.0, True)]
    fc, v, a = _concat_segments_graph(segs, 0.01, pre_roll=0.0, segment_vfs=[None] * 3, seam_xfades=[0.0, 0.0])
    groups = _input_groups(segs, [0.0, 0.0])
    windows = [(segs[g[0]].start, segs[g[-1]].end - segs[g[0]].start) for g in groups]
    out = tmp_path / "o.mp4"
    cmd = build_concat_cmd(ffmpeg, src, out, windows=windows, filter_complex=f"{fc};{v}null[v];{a}anull[a]",
                           codec="libx264", preset="ultrafast", audio_codec="aac", audio_bitrate="128k")
    subprocess.run(cmd, check=True)
    r = subprocess.run([ffprobe, "-v", "error", "-show_entries", "stream=codec_type,nb_frames,duration",
                        "-of", "csv=p=0", str(out)], capture_output=True, text=True, check=True).stdout.split()
    vrow = next(x for x in r if x.startswith("video"))
    arow = next(x for x in r if x.startswith("audio"))
    assert int(vrow.split(",")[2]) == 150                    # 5 s × 30 fps: 60 + 60 + 30 frames
    assert abs(float(arow.split(",")[1]) - 5.0) < 0.03


@pytest.mark.skipif(not (ffmpeg and ffprobe), reason="ffmpeg/ffprobe not installed")
def test_grouped_render_keeps_source_timing_on_variable_frame_rate(tmp_path):
    # iPhone footage: nominal 59.94, real frame times jitter / frames drop. The cut pieces must keep
    # their SOURCE durations (as the plan, subtitles and the duration invariant assume), not
    # "frames kept × nominal frame time" (IMG_6848 r07: −50 ms → render invariant [ERROR]).
    src = tmp_path / "vfr.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=60:duration=12",
                    "-f", "lavfi", "-i", "sine=f=440:d=12:sample_rate=48000", "-shortest",
                    "-vf", "select='not(eq(mod(n\\,7)\\,3))'", "-fps_mode", "passthrough",
                    "-c:v", "libx264", "-g", "60", "-c:a", "aac", str(src)], check=True)
    segs = [_seg(1.0, 3.0), _seg(4.0, 6.0, True), _seg(7.0, 8.0, True)]
    fc, v, a = _concat_segments_graph(segs, 0.01, pre_roll=0.0, segment_vfs=[None] * 3, seam_xfades=[0.0, 0.0])
    groups = _input_groups(segs, [0.0, 0.0])
    windows = [(segs[g[0]].start, segs[g[-1]].end - segs[g[0]].start) for g in groups]
    out = tmp_path / "o.mp4"
    cmd = build_concat_cmd(ffmpeg, src, out, windows=windows, filter_complex=f"{fc};{v}null[v];{a}anull[a]",
                           codec="libx264", preset="ultrafast", audio_codec="aac", audio_bitrate="128k")
    subprocess.run(cmd, check=True)
    r = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,duration",
                        "-of", "csv=p=0", str(out)], capture_output=True, text=True, check=True).stdout.split()
    vdur = float(next(x for x in r if x.startswith("video")).split(",")[1])
    assert abs(vdur - 5.0) < 2.5 / 60


# ── M30b: a cut whose picture would jump is left in ─────────────────────────────────────────

def test_jump_lookup_measures_cut_against_typical_motion(tmp_path):
    import numpy as np
    from autoreels.local.motion import FPS, jump_lookup, load, save
    frames = np.full((100, 48, 27), 100, dtype=np.uint8)
    frames[::2] += 2                                 # ordinary flicker between frames: 2 grey levels
    frames[50:] += 40                                # the head moves at t = 5.0 s
    jump = jump_lookup(frames)
    assert jump(2.0, 3.0) < 1.5                      # both sides still: invisible
    assert jump(4.5, 5.5) > 10                       # across the move: visible
    p = tmp_path / "m.npz"
    save(p, frames, "sha", [608, 1080, 656, 0])
    assert load(p, "sha", [608, 1080, 656, 0]) is not None
    assert load(p, "other", [608, 1080, 656, 0]) is None
    assert load(p, "sha", [100, 100, 0, 0]) is None
    assert FPS == 10 and jump_lookup(None) is None


def test_plan_leaves_in_cuts_with_a_visible_jump():
    sents, words, smap, align = _setup(SPEC, [[1.0, 1.6]])
    big = lambda a, b: 5.0 if a < 2.0 else 0.5       # the first cut would jump, the second not
    plan = build_manual_plan(sents, [1, 2], words=words, smap=smap, params=P, align=align, jump=big)
    w = plan.body[0]
    assert len(w.cuts) == 1 and w.cuts[0][0] > 3.0 and w.cuts_skipped == 1
    assert any("1 left in (visible jump)" in ln for ln in plan.describe(sents))
