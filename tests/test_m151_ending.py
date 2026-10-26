"""M151 (ending package, PLAN M1.7 B; owner: «просто чтобы была такая опция»): loop / held last frame / sting."""
from __future__ import annotations

import shutil
import subprocess
from types import SimpleNamespace

import pytest

from autoreels.core.config import RenderConfig
from autoreels.local.render import RenderError, _ending_flags, _extend_ending, _probe_duration_sec, _sibling_ffprobe

FF = shutil.which("ffmpeg")


def test_off_by_default():
    f = RenderConfig.model_fields
    assert f["ending_loop"].default is False and f["end_freeze_sec"].default == 0.0 and f["end_sting_path"].default == ""


def test_flags():
    cfg = SimpleNamespace(ending_loop=True, end_freeze_sec=1.0, end_sting_path="")
    hooked, plain = SimpleNamespace(cold_open=object()), SimpleNamespace(cold_open=None)
    assert _ending_flags(cfg, hooked, True) == (False, True)       # the loop wins: no freeze on a looping clip
    assert _ending_flags(cfg, plain, True) == (True, False)
    assert _ending_flags(cfg, plain, False) == (False, False)      # unplanned clips: as before
    off = SimpleNamespace(ending_loop=False, end_freeze_sec=0.0, end_sting_path="")
    assert _ending_flags(off, hooked, True) == (False, False)


def _clip(path, sec=2.0):
    subprocess.run([FF, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=d={sec}:s=320x240:r=30",
                    "-f", "lavfi", "-i", f"sine=f=440:d={sec}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(path)], check=True)


@pytest.mark.skipif(FF is None, reason="ffmpeg not installed")
def test_held_frame_and_sting_extend_the_clip(tmp_path):
    kw = dict(fade_sec=0.25, codec="libx264", quality_args=["-pix_fmt", "yuv420p"], audio_codec="aac",
              audio_bitrate="128k", faststart=True)
    a = tmp_path / "a.mp4"
    _clip(a)
    assert abs(_extend_ending(FF, a, freeze_sec=1.0, sting_path="", sting_volume=0.8, **kw) - 1.0) < 1e-9
    assert abs(_probe_duration_sec(a, _sibling_ffprobe(FF)) - 3.0) < 0.1
    b, s = tmp_path / "b.mp4", tmp_path / "s.wav"
    _clip(b)
    subprocess.run([FF, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=880:d=0.6", str(s)], check=True)
    added = _extend_ending(FF, b, freeze_sec=0.0, sting_path=str(s), sting_volume=0.8, **kw)
    assert abs(added - 0.6) < 0.05 and abs(_probe_duration_sec(b, _sibling_ffprobe(FF)) - 2.6) < 0.1
    with pytest.raises(RenderError):
        _extend_ending(FF, b, freeze_sec=0.0, sting_path=str(tmp_path / "none.wav"), sting_volume=0.8, **kw)
