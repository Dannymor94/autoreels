"""M147 (m143: one-pass loudnorm settles in the first second — the start of a clip quieter; the owner: «первая фраза
плохо слышна»): loudnorm_mode source = one gain for the whole source + a true-peak limiter."""
from __future__ import annotations

import subprocess

import pytest

from autoreels.core.config import AudioProcessing
from autoreels.local import render as R



def test_dynamic_is_the_default_and_unchanged():
    ap = AudioProcessing()
    assert ap.loudnorm_mode == "dynamic" and ap.static_gain_db is None
    assert R._loudnorm_str(ap) == "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,asetpts=N/SR/TB"
    assert R._loudnorm_str(ap.model_copy(update={"static_gain_db": 3.0})) == R._loudnorm_str(ap)   # mode decides


def test_source_mode_is_one_gain_and_a_limiter():
    ap = AudioProcessing().model_copy(update={"loudnorm_mode": "source", "static_gain_db": 4.256})
    s = R._loudnorm_str(ap)
    assert s.startswith("volume=4.26dB,alimiter=limit=0.8414:level=disabled:latency=1,")
    assert s.endswith("aresample=48000,asetpts=N/SR/TB") and "loudnorm" not in s


def test_measurement_parsed_and_never_a_silent_default(monkeypatch, tmp_path):
    out = 'noise\n[Parsed_loudnorm_0 @ 0x1]\n{\n "input_i" : "-21.30",\n "input_tp" : "-3.10"\n}\n'
    assert R._parse_loudnorm_json(out)["input_i"] == "-21.30"
    ap = AudioProcessing().model_copy(update={"loudnorm_mode": "source"})
    R._SOURCE_GAIN.clear()
    monkeypatch.setattr(R.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, "", out))
    assert abs(R._source_gain(tmp_path / "a.mp4", "ffmpeg", ap) - 7.3) < 1e-9
    R._SOURCE_GAIN.clear()
    monkeypatch.setattr(R.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "no json"))
    with pytest.raises(R.RenderError):
        R._source_gain(tmp_path / "b.mp4", "ffmpeg", ap)
    R._SOURCE_GAIN.clear()
