"""M27: the rendered audio timeline must be one packet per codec frame.

Owner: on Yandex Disk the clip had no sound for ~4 s and the picture «chewed» at the start; on the
Mac the video lagged behind the sound. Cause (measured, IMG_6848): single-pass loudnorm after the
concat of windows emitted broken timestamps — 1-sample packets at the start, then one 2.36 s
packet. Fix: rebuild the audio timestamps from the sample count right after loudnorm.
"""
import shutil
import subprocess

import pytest

from autoreels.core.config import AudioProcessing
from autoreels.local.render import _audio_packet_irregularities, _loudnorm_str

ffmpeg = shutil.which("ffmpeg")
ffprobe = shutil.which("ffprobe")


def test_loudnorm_is_followed_by_sample_count_timestamps():
    s = _loudnorm_str(AudioProcessing())
    assert s.startswith("loudnorm=I=")
    assert s.endswith(",aresample=48000,asetpts=N/SR/TB")


def _encode(tmp_path, tail: str):
    out = tmp_path / "a.m4a"
    fc = ("[0:a]atrim=start=0.0123,asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.01[a0];"
          "[1:a]atrim=start=0.517,asetpts=PTS-STARTPTS[a1];"
          f"[a0][a1]concat=n=2:v=0:a=1[s];[s]{tail}[a]")
    subprocess.run([ffmpeg, "-v", "error", "-y",
                    "-f", "lavfi", "-i", "sine=f=220:d=6:sample_rate=48000",
                    "-f", "lavfi", "-i", "sine=f=330:d=6:sample_rate=48000",
                    "-filter_complex", fc, "-map", "[a]", "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
                    str(out)], check=True)
    return out


@pytest.mark.skipif(not (ffmpeg and ffprobe), reason="ffmpeg/ffprobe not installed")
def test_concat_then_loudnorm_gives_one_packet_per_frame(tmp_path):
    fixed = _encode(tmp_path, _loudnorm_str(AudioProcessing()))
    assert _audio_packet_irregularities(fixed, ffprobe)[0] == 0


@pytest.mark.skipif(not (ffmpeg and ffprobe), reason="ffmpeg/ffprobe not installed")
def test_irregular_packets_are_detected(tmp_path):
    # a timestamp jump of 2 s after the 100th frame (what loudnorm did: one 2.36 s packet)
    broken = _encode(tmp_path, "asetpts='PTS+gte(N,100*1024)*2/TB'")
    n, longest = _audio_packet_irregularities(broken, ffprobe)
    assert n >= 1 and longest > 1.9
