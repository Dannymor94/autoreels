"""M156: VAAPI encoders (gamebox RX 580): device first, GPU upload at the end of the video filter, no output pix_fmt;
any other encoder — the command untouched (invariant 8)."""
from __future__ import annotations

import pytest

from autoreels.local import render as R


def _cut(codec, **kw):
    return R.build_cut_cmd("ffmpeg", "src.mp4", 10.0, 20.0, "out.mp4", codec=codec, preset="medium",
                           video_bitrate="5M", audio_codec="aac", audio_bitrate="192k", **kw)


@pytest.mark.parametrize("codec", ["libx264", "libx265", "hevc_videotoolbox", "hevc_amf"])
def test_m156_non_vaapi_command_is_unchanged(codec):
    for cmd in (_cut(codec), _cut(codec, vf="crop=1:1:0:0")):
        assert R._hw_argv(cmd) is cmd


def test_m156_vf_gets_upload_device_and_no_pix_fmt(monkeypatch):
    monkeypatch.delenv(R._VAAPI_DEVICE_ENV, raising=False)
    cmd = _cut("hevc_vaapi", vf="crop=608:1080:656:0,scale=1080:1920")
    assert "-pix_fmt" in cmd
    out = R._hw_argv(cmd)
    assert out[:3] == ["ffmpeg", "-vaapi_device", "/dev/dri/renderD128"]
    assert out[out.index("-vf") + 1].endswith("scale=1080:1920,format=nv12,hwupload")
    assert "-pix_fmt" not in out
    assert out[out.index("-c:v") + 1] == "hevc_vaapi" and "-tag:v" in out


def test_m156_filter_complex_maps_the_uploaded_label():
    cmd = ["ffmpeg", "-y", "-i", "a.mp4", "-i", "b.mp4", "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v];[0:a]anull[a]",
           "-map", "[v]", "-map", "[a]", "-c:v", "h264_vaapi", "-b:v", "8M", "-pix_fmt", "yuv420p", "out.mp4"]
    out = R._hw_argv(cmd)
    fc = out[out.index("-filter_complex") + 1]
    assert fc.endswith(";[v]format=nv12,hwupload[vhw]")
    maps = [out[i + 1] for i, a in enumerate(out) if a == "-map"]
    assert maps == ["[vhw]", "[a]"] and "-pix_fmt" not in out


def test_m156_no_filter_adds_upload_and_keeps_input_options():
    cmd = ["ffmpeg", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.1", "-frames:v", "1",
           "-c:v", "hevc_vaapi", "-pix_fmt", "yuv420p", "-f", "null", "-"]
    out = R._hw_argv(cmd)
    assert out[out.index("-vf") + 1] == "format=nv12,hwupload" and out.index("-vf") < out.index("-c:v")
    assert "-pix_fmt" not in out and out[-3:] == ["-f", "null", "-"]


def test_m156_device_from_env(monkeypatch):
    monkeypatch.setenv(R._VAAPI_DEVICE_ENV, "/dev/dri/renderD129")
    assert R._hw_argv(_cut("hevc_vaapi", vf="null"))[2] == "/dev/dri/renderD129"


def test_m156_filter_complex_without_v_is_an_error():
    cmd = ["ffmpeg", "-i", "a.mp4", "-filter_complex", "[0:v]null[x]", "-map", "[x]", "-c:v", "hevc_vaapi", "o.mp4"]
    with pytest.raises(R.RenderError):
        R._hw_argv(cmd)


def test_m156_probe_and_progress_runner_use_the_vaapi_command(monkeypatch):
    seen = []

    class P:
        returncode = 0
    assert R.probe_encoder("hevc_vaapi", run=lambda c: seen.append(c) or P()) is True
    assert "-vaapi_device" in seen[0] and "-pix_fmt" not in seen[0]
    assert R.probe_encoder("libx264", run=lambda c: seen.append(c) or P()) is True
    assert "-vaapi_device" not in seen[1]

    class FakeProc:
        def __init__(self, argv, **k):
            seen.append(argv)
            self.stderr = iter(())
            self.returncode = 0

        def wait(self):
            return 0
    monkeypatch.setattr(R.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(R, "is_tty", lambda: False)
    R._run_ffmpeg_with_progress(_cut("h264_vaapi", vf="null"), reel_id="r01", idx=1, total=1, duration_sec=10.0)
    assert seen[-1][1:3] == ["-vaapi_device", "/dev/dri/renderD128"]
    R._run_ffmpeg_with_progress(_cut("libx264", vf="null"), reel_id="r01", idx=1, total=1, duration_sec=10.0)
    assert seen[-1] == _cut("libx264", vf="null")
