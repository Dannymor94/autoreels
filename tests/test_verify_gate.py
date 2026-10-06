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
    """3s video + pink noise audio — volumedetect will see activity."""
    subprocess.run([
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"color=black:size=64x112:rate=30:duration={duration}",
        "-f", "lavfi", "-i", f"anoisesrc=r=44100:color=pink:duration={duration}:amplitude=0.3",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-b:a", "64k",
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


def test_main_fail_returns_1(tmp_path):
    """Missing clip → exit 1."""
    data = {"clips": [_yaml_entry(
        "r01", "nonexistent/r01.mp4", "s", 3.0, "a b c d", "e f g h"
    )]}
    yaml_path = tmp_path / "test.yaml"
    yaml_path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    rc = vg.main(str(yaml_path))
    assert rc == 1
