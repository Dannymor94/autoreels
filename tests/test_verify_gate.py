"""Verify gate script — unit tests with small synthetic fixtures.

No real video or audio in git. ffmpeg creates everything in tmp_path.
"""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# ── load verify_gate without making it a package ──────────────────────────────
_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "tools"))  # flash_check

_spec = importlib.util.spec_from_file_location(
    "verify_gate", _REPO / "scripts" / "verify_gate.py"
)
vg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vg)

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


# ── synthetic video helpers ────────────────────────────────────────────────────

def _make_mp4_with_audio(path: Path, duration: float = 3.0) -> Path:
    """3s video + pink noise audio — volumedetect will see activity.

    Muxed web-safe (h264/aac/+faststart) so the web-safe check in check_clip passes."""
    subprocess.run([
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"color=black:size=64x112:rate=30:duration={duration}",
        "-f", "lavfi", "-i", f"anoisesrc=r=44100:color=pink:duration={duration}:amplitude=0.3",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-b:a", "64k",
        "-movflags", "+faststart",
        str(path),
    ], capture_output=True, check=True)
    return path


def _make_mp4_silent(path: Path, duration: float = 3.0) -> Path:
    """3s video + silence — volumedetect sees very low dB."""
    subprocess.run([
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"color=black:size=64x112:rate=30:duration={duration}",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-b:a", "64k",
        "-t", str(duration),
        str(path),
    ], capture_output=True, check=True)
    return path


def _make_frozen_mp4(path: Path, duration: float = 3.0) -> Path:
    """3s video of a still black frame — all frame md5s identical."""
    subprocess.run([
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"color=black:size=64x112:rate=30:duration={duration}",
        "-f", "lavfi", "-i", f"anoisesrc=r=44100:color=pink:duration={duration}:amplitude=0.3",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-b:a", "64k",
        str(path),
    ], capture_output=True, check=True)
    return path


def _speechmap(path: Path, intervals: list) -> Path:
    """Write minimal speechmap.json with given intervals."""
    data = {"version": 6, "intervals": intervals, "words": [], "boundaries": []}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _yaml_entry(clip_id: str, path: str, stem: str, reel_end: float,
                first_words: str, last_words: str) -> dict:
    return {
        "clip_id": clip_id,
        "stem": stem,
        "path": path,
        "reel_start": 0.0,
        "reel_end": reel_end,
        "first_words": first_words,
        "last_words": last_words,
        "cold_open": None,
    }


# ── clip_missing ──────────────────────────────────────────────────────────────

def test_clip_missing(tmp_path):
    entry = _yaml_entry("r01", "nonexistent/r01.mp4", "stem", 10.0, "a b c d", "e f g h")
    fails = vg.check_clip(entry, tmp_path)
    assert fails == ["clip_missing"]


# ── error_mp4_present ─────────────────────────────────────────────────────────

def test_error_mp4_detected(tmp_path):
    clip_dir = tmp_path / "gate"
    clip_dir.mkdir()
    mp4 = clip_dir / "r01.mp4"
    _make_mp4_with_audio(mp4)
    (clip_dir / "r01.ERROR.mp4").write_bytes(b"")
    # transcript.txt + speechmap needed to avoid those failures
    (clip_dir / "r01.transcript.txt").write_text("a b c d e f g h\n", encoding="utf-8")
    _speechmap(tmp_path / "s.speechmap.json", [])

    entry = _yaml_entry("r01", str(mp4.relative_to(tmp_path)), "s", 3.0, "a b c d", "e f g h")
    fails = vg.check_clip(entry, tmp_path)
    assert "error_mp4_present" in fails


# ── first / last words ────────────────────────────────────────────────────────

def test_words_pass(tmp_path):
    clip_dir = tmp_path / "gate"
    clip_dir.mkdir()
    mp4 = clip_dir / "r01.mp4"
    _make_mp4_with_audio(mp4)
    (clip_dir / "r01.transcript.txt").write_text(
        "первое второе третье четвёртое пятое шестое седьмое восьмое\n",
        encoding="utf-8"
    )
    _speechmap(tmp_path / "s.speechmap.json", [])

    entry = _yaml_entry("r01", str(mp4.relative_to(tmp_path)), "s", 3.0,
                        "первое второе третье четвёртое", "пятое шестое седьмое восьмое")
    fails = vg.check_clip(entry, tmp_path)
    word_fails = [f for f in fails if "words" in f]
    assert not word_fails, f"unexpected word failures: {word_fails}"


def test_words_fail_first(tmp_path):
    clip_dir = tmp_path / "gate"
    clip_dir.mkdir()
    mp4 = clip_dir / "r01.mp4"
    _make_mp4_with_audio(mp4)
    (clip_dir / "r01.transcript.txt").write_text(
        "WRONG два три четыре пять шесть семь восемь\n", encoding="utf-8"
    )
    _speechmap(tmp_path / "s.speechmap.json", [])

    entry = _yaml_entry("r01", str(mp4.relative_to(tmp_path)), "s", 3.0,
                        "один два три четыре", "пять шесть семь восемь")
    fails = vg.check_clip(entry, tmp_path)
    assert any("first_words" in f for f in fails)


def test_words_fail_last(tmp_path):
    clip_dir = tmp_path / "gate"
    clip_dir.mkdir()
    mp4 = clip_dir / "r01.mp4"
    _make_mp4_with_audio(mp4)
    (clip_dir / "r01.transcript.txt").write_text(
        "один два три четыре пять шесть WRONG\n", encoding="utf-8"
    )
    _speechmap(tmp_path / "s.speechmap.json", [])

    entry = _yaml_entry("r01", str(mp4.relative_to(tmp_path)), "s", 3.0,
                        "один два три четыре", "четыре пять шесть семь")
    fails = vg.check_clip(entry, tmp_path)
    assert any("last_words" in f for f in fails)


def test_transcript_missing(tmp_path):
    clip_dir = tmp_path / "gate"
    clip_dir.mkdir()
    mp4 = clip_dir / "r01.mp4"
    _make_mp4_with_audio(mp4)
    _speechmap(tmp_path / "s.speechmap.json", [])

    entry = _yaml_entry("r01", str(mp4.relative_to(tmp_path)), "s", 3.0, "a b c d", "e f g h")
    fails = vg.check_clip(entry, tmp_path)
    assert "transcript_txt_missing" in fails


# ── audio start ──────────────────────────────────────────────────────────────

def test_audio_start_pass(tmp_path):
    mp4 = tmp_path / "r01.mp4"
    _make_mp4_with_audio(mp4)
    fails = vg._check_audio_start(mp4)
    assert not fails, f"unexpected: {fails}"


def test_audio_start_fail(tmp_path):
    mp4 = tmp_path / "r01.mp4"
    _make_mp4_silent(mp4)
    fails = vg._check_audio_start(mp4)
    assert fails, "silent clip should fail audio_start check"
    assert any("no_audio_start" in f for f in fails)


# ── tail silence (speechmap) ──────────────────────────────────────────────────

def test_tail_silence_pass(tmp_path):
    sm = _speechmap(tmp_path / "s.speechmap.json", [[0.0, 9.0]])
    # reel_end=10.0; last 0.5s = [9.5, 10.0]; speech ends at 9.0 → no overlap
    fails = vg._check_tail_silence(sm, reel_end=10.0)
    assert not fails


def test_tail_silence_fail(tmp_path):
    sm = _speechmap(tmp_path / "s.speechmap.json", [[9.6, 10.2]])
    # reel_end=10.0; last 0.5s = [9.5, 10.0]; interval [9.6, 10.2] overlaps
    fails = vg._check_tail_silence(sm, reel_end=10.0)
    assert fails
    assert any("speech_in_tail" in f for f in fails)


def test_tail_silence_speechmap_missing(tmp_path):
    fails = vg._check_tail_silence(tmp_path / "nosuchfile.speechmap.json", reel_end=10.0)
    assert any("speechmap_missing" in f for f in fails)


def test_tail_silence_short_interval_ignored(tmp_path):
    """Intervals shorter than SPEECH_MIN_INTERVAL_SEC (0.1s) are noise — must not fire.

    Reproduces lec0933 r05 [825.78,825.85] (0.07s) and r10 [1518.94,1518.97] (0.03s)."""
    sm_path = tmp_path / "s.speechmap.json"
    sm_path.write_text(json.dumps({
        "version": 6,
        "intervals": [[9.6, 9.67]],   # 0.07s — below SPEECH_MIN_INTERVAL_SEC=0.1s
        "words": [{"idx": 0, "t0": 8.0, "t1": 9.0, "audible_end": 9.0}],
        "boundaries": [],
    }), encoding="utf-8")
    fails = vg._check_tail_silence(sm_path, reel_end=10.0)
    assert not fails, f"short interval (<0.1s) must not trigger speech_in_tail: {fails}"

    # Interval clearly above threshold (0.15s) must fire
    sm_path.write_text(json.dumps({
        "version": 6,
        "intervals": [[9.55, 9.7]],   # 0.15s — well above SPEECH_MIN_INTERVAL_SEC
        "words": [{"idx": 0, "t0": 8.0, "t1": 9.0, "audible_end": 9.0}],
        "boundaries": [],
    }), encoding="utf-8")
    fails = vg._check_tail_silence(sm_path, reel_end=10.0)
    assert any("speech_in_tail" in f for f in fails), \
        f"interval of 0.15s must trigger speech_in_tail: {fails}"


# ── tail frames (framemd5) ────────────────────────────────────────────────────

def test_tail_frames_natural_motion_passes(tmp_path):
    # video with changing content (noise) → frames not identical → pass
    mp4 = tmp_path / "r01.mp4"
    subprocess.run([
        FFMPEG, "-y",
        "-f", "lavfi", "-i", "mandelbrot=size=64x112:rate=30:end_pts=3",
        "-f", "lavfi", "-i", "anoisesrc=r=44100:color=pink:duration=3:amplitude=0.3",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-b:a", "64k", "-t", "3", str(mp4),
    ], capture_output=True, check=True)
    fails = vg._check_tail_frames(mp4, clip_duration=3.0)
    assert not fails


def test_tail_frames_frozen_synthetic_tail_passes(tmp_path):
    # all-black still → all frames identical → synthetic tail → pass
    mp4 = tmp_path / "r01.mp4"
    _make_frozen_mp4(mp4, duration=3.0)
    fails = vg._check_tail_frames(mp4, clip_duration=3.0)
    assert not fails, f"frozen tail should pass: {fails}"


# ── full yaml round-trip ──────────────────────────────────────────────────────

def test_main_all_pass(tmp_path):
    """End-to-end: one clip yaml + real file → PASS with exit 0."""
    clip_dir = tmp_path / "gate"
    clip_dir.mkdir()
    tx_dir = tmp_path / "transcripts"
    tx_dir.mkdir()

    mp4 = clip_dir / "r01.mp4"
    _make_mp4_with_audio(mp4)
    (clip_dir / "r01.transcript.txt").write_text(
        "один два три четыре пять шесть семь восемь\n", encoding="utf-8"
    )
    _speechmap(tx_dir / "s.speechmap.json", [[0.0, 2.0]])
    (clip_dir / "r01.render.json").write_text(
        json.dumps({"source_start": 0.0, "source_end": 3.0, "synthetic_tail_sec": 0.0}),
        encoding="utf-8",
    )

    data = {"clips": [_yaml_entry(
        "r01",
        str(mp4.relative_to(tmp_path)),
        "s",
        reel_end=3.0,
        first_words="один два три четыре",
        last_words="пять шесть семь восемь",
    )]}
    yaml_path = tmp_path / "test.yaml"
    yaml_path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")

    rc = vg.main(str(yaml_path), project=tmp_path)
    assert rc == 0


# ── Bug 1: speech_in_tail — own last words must not fire ─────────────────────

def test_tail_silence_lecture_r01_own_last_words(tmp_path):
    """lecture r01: speech [79.05,81.24], reel_end=81.54 — own last word, must PASS."""
    sm_path = tmp_path / "s.speechmap.json"
    sm_path.write_text(json.dumps({
        "version": 6,
        "intervals": [[79.05, 81.24]],
        "words": [{"idx": 10, "t0": 81.0, "t1": 81.24, "audible_end": 81.24}],
        "boundaries": [],
    }), encoding="utf-8")
    fails = vg._check_tail_silence(sm_path, reel_end=81.54)
    assert not fails, f"own last words must not trigger speech_in_tail: {fails}"


# ── Bug 2: tail fade frames — last run exempt ──────────────────────────────────

def test_span_violations_tail_fade_exempt():
    """PXL r01: 1-frame wide tail (fr 1169-1169) must not trigger short_span."""
    runs = [
        ("close", 1, 119), ("wide", 120, 427), ("close", 428, 696),
        ("wide", 697, 925), ("close", 926, 1168), ("wide", 1169, 1169),
    ]
    fails = vg._check_span_violations(
        runs, jump_seam_frames=set(), fps=30.0,
        min_shot=2.5, min_middle=4.0, shot_tolerance_frames=2,
    )
    assert not any("short_span" in f for f in fails), \
        f"1-frame tail must be exempt: {fails}"


# ── Bug 3: jump-seam span — exempt when >= JUMP_SEAM_MIN_SEC ──────────────────

def test_span_violations_jump_seam_lec_r06():
    """lecture r06: close 2.07s (62fr) at jump seam (16.5s backward gap) → PASS."""
    reel = {
        "segments": [
            {"start": 467.52635, "end": 469.27634, "close_intervals": []},
            {"start": 452.78635, "end": 461.04635, "close_intervals": []},
            {"start": 469.68634, "end": 473.22635, "close_intervals": []},
        ],
        "cold_open": None,
    }
    js_frames = vg._jump_seam_frames(reel)
    assert js_frames, "r06 must have jump seams"
    # actual shot sequence from flash_check: close(62fr) → wide(252fr) → close(91fr)
    runs = [("close", 1, 62), ("wide", 63, 314), ("close", 315, 405)]
    fails = vg._check_span_violations(
        runs, jump_seam_frames=js_frames, fps=30.0,
        min_shot=2.5, min_middle=4.0, shot_tolerance_frames=2,
    )
    assert not any("short_span" in f for f in fails), \
        f"2.07s close at jump seam must be exempt: {fails}"


# ── Bug 4: word normalization — punctuation must not cause mismatch ───────────

def test_words_normalization_punct_match(tmp_path):
    """Transcript has trailing period; golden does not — must match after normalization."""
    clip_dir = tmp_path / "gate"
    clip_dir.mkdir()
    mp4 = clip_dir / "r01.mp4"
    _make_mp4_with_audio(mp4)
    (clip_dir / "r01.transcript.txt").write_text(
        "Здесь мы стараемся войти.\n", encoding="utf-8"
    )
    _speechmap(tmp_path / "s.speechmap.json", [])
    entry = _yaml_entry("r01", str(mp4.relative_to(tmp_path)), "s", 3.0,
                        "Здесь мы стараемся войти",
                        "Здесь мы стараемся войти")
    fails = vg.check_clip(entry, tmp_path)
    assert not any("words" in f for f in fails), \
        f"punct-normalized words should match: {fails}"


def test_words_normalization_dash_token_stripped(tmp_path):
    """PXL r04: golden '— А с какими' has dash stripped → N=3, not 4 — must match."""
    clip_dir = tmp_path / "gate"
    clip_dir.mkdir()
    mp4 = clip_dir / "r01.mp4"
    _make_mp4_with_audio(mp4)
    (clip_dir / "r01.transcript.txt").write_text(
        "а с какими самыми разными клиентами работаешь.\n", encoding="utf-8"
    )
    _speechmap(tmp_path / "s.speechmap.json", [])
    entry = _yaml_entry("r01", str(mp4.relative_to(tmp_path)), "s", 3.0,
                        "— А с какими",  # dash strips → N=3
                        "а с какими самыми")
    fails = vg.check_clip(entry, tmp_path)
    assert not any("first_words" in f for f in fails), \
        f"dash-prefixed golden first_words should match after strip: {fails}"


# ── Bug 5: frame tolerance — 118fr A-B-A middle passes with 2-frame tolerance ─

def test_span_violations_aba_118fr_tolerance():
    """PXL r05 pattern: A-B-A middle 118fr=3.933s, 2-frame tol → 3.933+0.067=4.0 → PASS."""
    # No tail artifact — genuine 3-run pattern
    runs = [("wide", 1, 300), ("close", 301, 418), ("wide", 419, 720)]
    fails = vg._check_span_violations(
        runs, jump_seam_frames=set(), fps=30.0,
        min_shot=2.5, min_middle=4.0, shot_tolerance_frames=2,
    )
    assert not any("aba_middle_short" in f for f in fails), \
        f"118fr close A-B-A middle must pass with 2-frame tolerance: {fails}"


# ── Bug 6: own-word via t1 extension — blip within Whisper t1 span must not fire ─

def test_tail_silence_own_word_t1_extension(tmp_path):
    """lec r02: last word t1=186.38 extends past ae=184.61; 0.02s blip at 186.09 is own-word."""
    sm_path = tmp_path / "s.speechmap.json"
    sm_path.write_text(json.dumps({
        "version": 6,
        "intervals": [[186.09, 186.11]],
        "words": [{"idx": 5, "t0": 184.06, "t1": 186.38, "audible_end": 184.61}],
        "boundaries": [],
    }), encoding="utf-8")
    fails = vg._check_tail_silence(sm_path, reel_end=186.24)
    assert not fails, f"blip within last word t1 must not trigger speech_in_tail: {fails}"


# ── Bug 7: render_end cutoff — interval after audio cut point is outside the clip ─

def test_tail_silence_render_end_cutoff(tmp_path):
    """PXL r10: render_end=2748.33; own-word [2747.40] exempt; [2748.40] > render_end → PASS."""
    sm_path = tmp_path / "s.speechmap.json"
    sm_path.write_text(json.dumps({
        "version": 6,
        "intervals": [[2747.40, 2747.68], [2748.40, 2748.66]],
        "words": [{"idx": 99, "t0": 2747.081, "t1": 2747.621, "audible_end": 2747.21}],
        "boundaries": [],
    }), encoding="utf-8")
    fails = vg._check_tail_silence(sm_path, reel_end=2748.33)
    assert not fails, f"interval after render_end must not trigger speech_in_tail: {fails}"


# ── render_end_missing — source_end required from render.json ─────────────────

def test_render_end_missing_no_json(tmp_path):
    """check_clip fails with render_end_missing when no render.json exists."""
    clip_dir = tmp_path / "gate"
    clip_dir.mkdir()
    mp4 = clip_dir / "r01.mp4"
    _make_mp4_with_audio(mp4)
    _speechmap(tmp_path / "s.speechmap.json", [])
    entry = _yaml_entry("r01", str(mp4.relative_to(tmp_path)), "s", 3.0, "a b", "a b")
    fails = vg.check_clip(entry, tmp_path)
    assert "render_end_missing" in fails, f"expected render_end_missing: {fails}"


def test_render_end_missing_no_source_end_field(tmp_path):
    """check_clip fails with render_end_missing when render.json lacks source_end."""
    clip_dir = tmp_path / "gate"
    clip_dir.mkdir()
    mp4 = clip_dir / "r01.mp4"
    _make_mp4_with_audio(mp4)
    _speechmap(tmp_path / "s.speechmap.json", [])
    (clip_dir / "r01.render.json").write_text(
        json.dumps({"fingerprint": "abc"}), encoding="utf-8"
    )
    entry = _yaml_entry("r01", str(mp4.relative_to(tmp_path)), "s", 3.0, "a b", "a b")
    fails = vg.check_clip(entry, tmp_path)
    assert "render_end_missing" in fails, f"expected render_end_missing: {fails}"


def test_render_end_source_end_gates_tail_check(tmp_path):
    """source_end from render.json gates tail check; interval after source_end=3.0 → PASS."""
    clip_dir = tmp_path / "gate"
    clip_dir.mkdir()
    mp4 = clip_dir / "r01.mp4"
    _make_mp4_with_audio(mp4)
    sm = tmp_path / "s.speechmap.json"
    sm.write_text(json.dumps({
        "version": 6,
        "intervals": [[3.5, 3.7]],
        "words": [{"idx": 0, "t0": 2.0, "t1": 2.8, "audible_end": 2.5}],
        "boundaries": [],
    }), encoding="utf-8")
    (clip_dir / "r01.render.json").write_text(
        json.dumps({"source_start": 0.0, "source_end": 3.0, "synthetic_tail_sec": 0.0}),
        encoding="utf-8",
    )
    entry = _yaml_entry("r01", str(mp4.relative_to(tmp_path)), "s", 5.0, "a b", "a b")
    fails = vg.check_clip(entry, tmp_path)
    assert "render_end_missing" not in fails, f"source_end present, must not fire: {fails}"
    assert not any("speech_in_tail" in f for f in fails), \
        f"interval [3.5,3.7] after source_end=3.0 must not trigger speech_in_tail: {fails}"


def test_main_fail_returns_1(tmp_path):
    """Missing clip → exit 1."""
    data = {"clips": [_yaml_entry(
        "r01", "nonexistent/r01.mp4", "s", 3.0, "a b c d", "e f g h"
    )]}
    yaml_path = tmp_path / "test.yaml"
    yaml_path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    rc = vg.main(str(yaml_path))
    assert rc == 1


# ── planned reels (REEL_SPEC §7.2): frame-by-frame shot check against the plan ─────────────

def test_planned_expected_follows_shot_and_close_intervals():
    labels = vg._planned_expected({"shot": "wide", "close_intervals": [[1.0, 2.0]]}, 90, 30.0)
    assert labels[:30] == ["wide"] * 30
    assert labels[30:60] == ["close"] * 30
    assert labels[60:] == ["wide"] * 30
    assert vg._planned_expected({"shot": "close", "close_intervals": []}, 5, 30.0) == ["close"] * 5


def test_planned_reel_without_source_is_a_failure_not_a_skip(tmp_path):
    reel = {"id": "r01", "planned": True, "segments": [{"start": 1.0, "end": 3.0, "shot": "wide"}]}
    mf = tmp_path / "m.json"
    mf.write_text(json.dumps({"source": "nowhere.mov", "setup": {}, "reels": [reel]}))
    fails = vg._check_shots(tmp_path / "r01.mp4", mf, "r01", tmp_path / "inputs-archive")
    assert fails == ["plan_shots_unchecked:source_not_found"]


def test_end_aligned_catches_hesitation_and_next_word(tmp_path):
    al = {"version": 1, "words": [{"t0": 1.0, "start": 1.05, "end": 1.6}, {"t0": 3.6, "start": 3.7, "end": 3.9}],
          "untranscribed": [[1.8, 2.4], [2.5, 3.6]]}
    p = tmp_path / "x.align.json"
    p.write_text(json.dumps(al))
    reel = {"planned": True, "subtitles": [{"word": "жизнь.", "t0": 1.0, "t1": 3.6}]}
    assert vg._check_end_aligned(p, reel, 1.75) == []                     # ends before «ммм»
    bad = vg._check_end_aligned(p, reel, 3.8)                             # Whisper-time end
    assert any(f.startswith("next_word_in_clip") for f in bad)
    assert any(f.startswith("untranscribed_speech_in_tail") for f in bad)
    assert vg._check_end_aligned(p, reel, 1.5)[0].startswith("last_word_cut_aligned")
    assert vg._check_end_aligned(p, {"planned": True, "subtitles": [{"word": "x", "t0": 9.0}]}, 9.5) == \
        ["alignment_mismatch:0/1"]


def test_end_air_planned_measured_from_plan_word_end(tmp_path, monkeypatch):
    """IMG_6848 r04: «человеком.» map ae 1097.260, plan (aligned) 1097.310, clip end 1097.600 —
    0.29 s of air by the plan; from the map it read 0.34 > 0.333 (false FAIL)."""
    monkeypatch.setattr(vg, "_DYNAMIC_ENDING", True)
    monkeypatch.setattr(vg, "_END_AIR_SEC", 0.30)
    sm = tmp_path / "x.speechmap.json"
    sm.write_text(json.dumps({"words": [{"t0": 1096.7, "t1": 1097.3, "audible_end": 1097.26}]}))
    sub = [{"word": "человеком.", "t0": 1096.7, "t1": 1097.3}]
    assert vg._check_end_air_vg(sm, {"subtitles": sub}, 1097.6)          # not planned: map end
    planned = {"planned": True, "tail_last_word_end": 1097.31, "subtitles": sub}
    assert vg._check_end_air_vg(sm, planned, 1097.6) == []
    assert vg._check_end_air_vg(sm, planned, 1097.7)[0].startswith("end_air:")


def test_end_aligned_finds_words_moved_out_of_a_filler_cut(tmp_path):
    # REEL_SPEC §1.4: a subtitle start inside a cut stretch is moved to the next played piece
    al = {"version": 1, "words": [{"t0": 1.0, "start": 1.05, "end": 1.6}, {"t0": 2.0, "start": 2.9, "end": 3.4}],
          "untranscribed": [[1.7, 2.8]]}
    p = tmp_path / "x.align.json"
    p.write_text(json.dumps(al))
    subs = [{"word": "раз", "t0": 1.0, "t1": 1.6}, {"word": "два.", "t0": 2.88, "t1": 3.4}]   # t0 moved 2.0 → 2.88
    cut = {"planned": True, "subtitles": subs,
           "segments": [{"start": 0.9, "end": 1.7}, {"start": 2.83, "end": 3.7, "window_cut": True}]}
    assert vg._check_end_aligned(p, cut, 3.7) == []
    plain = {"planned": True, "subtitles": subs, "segments": [{"start": 0.9, "end": 3.7}]}
    assert vg._check_end_aligned(p, plain, 3.7) == ["alignment_mismatch:1/2"]
