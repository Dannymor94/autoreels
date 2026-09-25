"""video_xfade_sec: short dissolve at internal segment seams.

1. Two-segment reel with xfade has duration = sum − 1 × xfade; subtitles land correctly.
2. video_xfade_sec=0 → hard concat (byte-identical filtergraph to pre-xfade path).
3. Frame-alignment invariant: xfade snapped to frame grid → output duration is frame-aligned.
4. build_concat_cmd with 4 windows (3 seams) includes -t matching expected duration.
5. build_concat_cmd without duration_sec does not add -t (no-seams path unchanged).
6. pre_roll: build_cut_cmd with pre_roll seeks earlier and adds trim=start={pr} in vf/af.
7. pre_roll: build_concat_cmd with pre_roll seeks each window earlier; filtergraph adds trim.
"""
from autoreels.core.models import Segment
from autoreels.local.render import (
    _concat_segments_graph, _snap_windows_to_frames, _expected_output_duration,
    build_concat_cmd, build_cut_cmd, _ts_dur, _ts, _num,
)
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


# ── Test 4: 3-seam clip command includes -t capping at expected duration ──────
def test_three_seam_cmd_includes_t_duration():
    """build_concat_cmd with 4 windows passes -t equal to _ts_dur(expected_duration),
    so hevc_videotoolbox/amf encoder artifacts (1 frame per seam) are trimmed off."""
    fps = 29.97
    # r02 segment values from the manifest (post-snap approximation)
    segs = [
        _seg(131.231, 151.517),
        _seg(154.354, 158.758),
        _seg(159.393, 169.503),
        _seg(170.103, 195.728),
    ]
    xfade = round(0.0667 * fps) / fps  # 2 frames at 29.97

    expected = _expected_output_duration(segs, xfade_sec=xfade)
    windows = [(s.start, s.end - s.start) for s in segs]

    cmd = build_concat_cmd(
        "ffmpeg", "source.mp4", "out.mp4",
        windows=windows, filter_complex="[0:v]null[v];[0:a]anull[a]",
        codec="hevc_videotoolbox", preset="medium",
        audio_codec="aac", audio_bitrate="128k",
        xfade_fps=fps, duration_sec=expected,
    )
    shortest_idx = cmd.index("-shortest")
    tail = cmd[shortest_idx:]
    assert "-t" in tail, "output -t not found after -shortest"
    t_val = tail[tail.index("-t") + 1]
    assert t_val == _ts_dur(expected), f"-t {t_val!r} != {_ts_dur(expected)!r}"


# ── Test 5: no-seams path — duration_sec=None does not inject -t ──────────────
def test_no_seams_cmd_no_t_duration():
    """build_concat_cmd without duration_sec (or duration_sec=None) must NOT add -t;
    callers that don't pass it are unaffected."""
    windows = [(0.0, 30.0)]
    cmd = build_concat_cmd(
        "ffmpeg", "source.mp4", "out.mp4",
        windows=windows, filter_complex="[0:v]null[v];[0:a]anull[a]",
        codec="libx264", preset="fast",
        audio_codec="aac", audio_bitrate="128k",
    )
    # -t for OUTPUT must not appear (INPUT -t args come in pairs with -ss/-i)
    # All -t values are input-side; if no duration_sec, there is no output -t.
    # The output is the last non-flag argument; check no -t appears after -shortest.
    shortest_idx = cmd.index("-shortest")
    assert "-t" not in cmd[shortest_idx:], "unexpected -t after -shortest"


# ── Test 6: build_cut_cmd pre_roll seeks earlier + adds trim filter ───────────
def test_cut_cmd_pre_roll_seek_and_trim():
    """build_cut_cmd(pre_roll=2.0) must seek 2 s before start and prepend
    trim=start={pre_roll},setpts=PTS-STARTPTS to vf/af (relative, because
    input-side seek resets frame PTS to 0)."""
    start = 66.1
    pre_roll = 2.0
    vf = "crop=960:1700:864:350,scale=1080:1920"
    af = "loudnorm=I=-14:TP=-1.5:LRA=11"
    cmd = build_cut_cmd(
        "ffmpeg", "source.mp4", start, start + 17.0, "out.mp4",
        codec="hevc_videotoolbox", preset="medium",
        audio_codec="aac", audio_bitrate="128k",
        vf=vf, af=af, pre_roll=pre_roll,
    )
    # Input seek must be pre_roll seconds before start
    ss_idx = cmd.index("-ss")
    assert cmd[ss_idx + 1] == _ts(start - pre_roll), \
        f"-ss should be {_ts(start - pre_roll)}, got {cmd[ss_idx + 1]}"
    # vf must start with trim=start={_num(pre_roll)},setpts=PTS-STARTPTS (relative PTS after seek)
    vf_idx = cmd.index("-vf")
    vf_val = cmd[vf_idx + 1]
    assert vf_val.startswith(f"trim=start={_num(pre_roll)},setpts=PTS-STARTPTS,"), \
        f"-vf doesn't start with trim prefix: {vf_val!r}"
    assert vf in vf_val, f"original vf missing from -vf: {vf_val!r}"
    # af must start with atrim=start={_num(pre_roll)},asetpts=PTS-STARTPTS
    af_idx = cmd.index("-af")
    af_val = cmd[af_idx + 1]
    assert af_val.startswith(f"atrim=start={_num(pre_roll)},asetpts=PTS-STARTPTS,"), \
        f"-af doesn't start with atrim prefix: {af_val!r}"


# ── Test 7: build_concat_cmd pre_roll seeks each window earlier ───────────────
def test_concat_cmd_pre_roll_seek():
    """build_concat_cmd(pre_roll=2.0) seeks each window 2 s before its start;
    _concat_segments_graph(pre_roll=2.0) adds trim=start={pr} (relative) in the graph."""
    segs = [_seg(131.231, 151.517), _seg(159.393, 169.503)]
    windows = [(s.start, s.end - s.start) for s in segs]
    pre_roll = 2.0
    prefix, _, _ = _concat_segments_graph(segs, 0.01, pre_roll=pre_roll)

    # Graph must contain trim=start={_num(pr)} (relative) for each segment; both segs start > 2.0
    for s in segs:
        pr = min(pre_roll, s.start)
        assert f"trim=start={_num(pr)}" in prefix, \
            f"trim=start={_num(pr)} not found in filtergraph prefix"

    cmd = build_concat_cmd(
        "ffmpeg", "source.mp4", "out.mp4",
        windows=windows, filter_complex=f"{prefix};[vseg]null[v];[aseg]anull[a]",
        codec="hevc_videotoolbox", preset="medium",
        audio_codec="aac", audio_bitrate="128k",
        pre_roll=pre_roll,
    )
    # Each -ss must be (start - min(pre_roll, start)) seconds before window start
    ss_positions = [i for i, tok in enumerate(cmd) if tok == "-ss"]
    for idx, (st, _dur) in zip(ss_positions, windows):
        pr = min(pre_roll, st)
        expected_ss = _ts(st - pr)
        assert cmd[idx + 1] == expected_ss, \
            f"window start={st}: expected -ss {expected_ss}, got {cmd[idx + 1]}"
