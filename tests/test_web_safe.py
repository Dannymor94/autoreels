"""Web-safe delivery check (Part 2): a correct clip passes; an edit-list / delayed-audio /
no-faststart / silent-opening clip fails.  Synthetic clips built by ffmpeg in tmp_path.
"""
import shutil
import subprocess

import pytest

from autoreels.local.render import _check_web_safe, _moov_before_mdat

FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not in PATH")


def _make(path, *, faststart=True, vcodec="libx264", silent=False,
          audio_offset=0.0, duration=4.0):
    """Mux a small clip. audio_offset>0 delays the audio stream (non-zero start_time)."""
    audio_in = (f"anullsrc=r=48000:cl=stereo" if silent
                else f"anoisesrc=r=48000:color=pink:duration={duration}:amplitude=0.3")
    cmd = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=black:size=64x112:rate=30:duration={duration}",
    ]
    if audio_offset > 0:
        cmd += ["-itsoffset", str(audio_offset)]
    cmd += ["-f", "lavfi", "-i", audio_in,
            "-c:v", vcodec, "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
            "-t", str(duration)]
    if faststart:
        cmd += ["-movflags", "+faststart"]
    cmd += [str(path)]
    subprocess.run(cmd, capture_output=True, check=True)
    return path


# ── correct clip passes ─────────────────────────────────────────────────────────

def test_correct_clip_passes(tmp_path):
    mp4 = _make(tmp_path / "ok.mp4")
    errors = _check_web_safe(mp4, FFMPEG, require_h264=True, fps=30.0)
    assert errors == [], f"a correct web-safe clip must pass: {errors}"


def test_moov_before_mdat_true_for_faststart(tmp_path):
    mp4 = _make(tmp_path / "fs.mp4", faststart=True)
    assert _moov_before_mdat(mp4) is True


# ── edit-list / delayed audio fails ──────────────────────────────────────────────

def test_delayed_audio_start_fails(tmp_path):
    """Audio stream with a non-zero start_time (delayed) — the Yandex failure shape."""
    mp4 = _make(tmp_path / "delayed.mp4", audio_offset=1.0)
    errors = _check_web_safe(mp4, FFMPEG, require_h264=True, fps=30.0)
    assert any("start_time" in e for e in errors), f"delayed audio must fail: {errors}"


def test_no_faststart_fails(tmp_path):
    """moov atom after mdat (no faststart) — streaming players stall."""
    mp4 = _make(tmp_path / "nofs.mp4", faststart=False)
    assert _moov_before_mdat(mp4) is False
    errors = _check_web_safe(mp4, FFMPEG, require_h264=True, fps=30.0)
    assert any("moov" in e for e in errors), f"no-faststart must fail: {errors}"


def test_silent_opening_fails(tmp_path):
    mp4 = _make(tmp_path / "silent.mp4", silent=True)
    errors = _check_web_safe(mp4, FFMPEG, require_h264=True, fps=30.0)
    assert any("silent" in e for e in errors), f"silent opening must fail: {errors}"


# ── codec policy: h264 required by default, hevc allowed as explicit option ───────

def test_hevc_errors_when_h264_required(tmp_path):
    mp4 = _make(tmp_path / "hevc.mp4", vcodec="libx265")
    errors = _check_web_safe(mp4, FFMPEG, require_h264=True, fps=30.0)
    assert any("not h264" in e for e in errors), f"hevc must fail when h264 required: {errors}"


def test_hevc_warning_only_when_not_required(tmp_path):
    """require_h264=False (operator chose hevc deliberately): codec is a warning, not an [ERROR]."""
    mp4 = _make(tmp_path / "hevc2.mp4", vcodec="libx265")
    errors = _check_web_safe(mp4, FFMPEG, require_h264=False, fps=30.0)
    assert not any("not h264" in e for e in errors), f"hevc must not hard-fail here: {errors}"
