"""UI-204A: existing CLI render entry point, isolated bytes + mocked encoder."""
import hashlib
import shutil
from pathlib import Path

import pytest
import yaml

from autoreels import __main__ as cli
from autoreels.core.models import Crop, Manifest, Reel, SetupProfile
from autoreels.orchestr import pipeline_gateway as gateway


def digest(data):
    return hashlib.sha256(data).hexdigest()


def stage(root):
    for folder in ("config", "inputs", "reviews"):
        (root / folder).mkdir()
    repo = Path(__file__).resolve().parents[2]
    for name in ("render.yaml", "subtitles.yaml", "r0.yaml"):
        shutil.copyfile(repo / "config" / name, root / "config" / name)
    (root / "config" / "render.local.yaml").write_text(yaml.safe_dump({
        "role": "both", "speech_map": False, "music": {"enabled": False},
    }))
    source = root / "inputs" / "DEMO.mp4"
    source.write_bytes(b"synthetic-source")
    manifest = Manifest(
        source=source.name, source_sha256=digest(source.read_bytes()),
        duration_preset="shorts", run_key="synthetic",
        setup=SetupProfile(setup_id="s", crop=Crop(x=0, y=0, w=1080, h=1920),
                           frame=[1080, 1920], scale=[1080, 1920]),
        reels=[Reel(id=id, start=0.0, end=2.0, score=80, hook="h",
                    title="t", description="d") for id in ("r01", "r02")],
    )
    path = root / "reviews" / "DEMO.review.json"
    path.write_text(manifest.model_dump_json(), encoding="utf-8")
    return source, path


def test_staged_adapter_reuses_cli_and_preserves_source(monkeypatch, tmp_path):
    source, plan = stage(tmp_path)
    before = plan.read_bytes()
    calls = []

    def fail(*args, **kwargs):
        pytest.fail("unexpected side effect or external dependency")

    monkeypatch.setattr(cli, "_git_pull", fail)
    monkeypatch.setattr(cli, "_archive_video", fail)
    monkeypatch.setattr(cli, "_manifest_calibration_desync", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_resolve_cached_transcript", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_resolve_music_track", lambda *a, **k: None)
    monkeypatch.setattr(cli, "resolve_ffmpeg", lambda *a, **k: "synthetic-ffmpeg")
    def preflight(profile, encoder, cfg, **kwargs):
        assert profile == "h264" and encoder == "libx264"
        assert kwargs["fallback"] is False
        return profile, encoder
    monkeypatch.setattr(cli, "_preflight_encoder", preflight)
    monkeypatch.setattr(cli, "_stage_two_shot_auto", lambda *a, **k: None)
    def render(manifest, **kwargs):
        assert [r.id for r in manifest.reels] == ["r02"]
        assert kwargs["profile"] == "h264" and kwargs["encoder"] == "libx264"
        out = kwargs["out_dir"] / "r02.mp4"
        out.parent.mkdir(parents=True)
        out.write_bytes(b"synthetic-output")
        calls.append(out)
        return [out]
    monkeypatch.setattr(cli, "render_crop", render)
    result, sha = gateway.render_staged_clip(
        tmp_path, stem="DEMO", clip="r02", gate="ui-test",
        plan_sha256=digest(before), run_render=cli.cmd_render,
    )
    assert result == tmp_path / "reels-out" / "DEMO" / "_gate" / "ui-test" / "r02.mp4"
    assert sha == digest(b"synthetic-output")
    assert calls == [result]
    assert source.read_bytes() == b"synthetic-source" and plan.read_bytes() == before
    assert not (tmp_path / "inputs-archive").exists()
    assert not (result.parent / "r01.mp4").exists()
    with pytest.raises(ValueError, match="gate"):
        gateway.render_staged_clip(tmp_path, stem="DEMO", clip="r02", gate="ui-test",
                                   plan_sha256=digest(before), run_render=fail)


def test_staged_adapter_rejects_stale_or_missing_inputs(tmp_path):
    source, plan = stage(tmp_path)
    before = plan.read_bytes()
    def fail(**kwargs):
        pytest.fail("render must not be called")
    args = dict(stem="DEMO", clip="r01", gate="ui-test",
                plan_sha256=digest(before), run_render=fail)
    with pytest.raises(ValueError, match="stale plan"):
        gateway.render_staged_clip(tmp_path, **{**args, "plan_sha256":"a"*64})
    with pytest.raises(ValueError, match="unsupported"):
        gateway.render_staged_clip(tmp_path, **{**args, "clip":"r99"})
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="source mismatch"):
        gateway.render_staged_clip(tmp_path, **args)
    assert not (tmp_path / "reels-out").exists()


def test_staged_adapter_does_not_accept_missing_or_wrong_result(tmp_path):
    _, plan = stage(tmp_path)
    args = dict(stem="DEMO", clip="r01", gate="ui-test",
                plan_sha256=digest(plan.read_bytes()))
    for output in ([], [tmp_path / "unrelated.mp4"]):
        with pytest.raises(RuntimeError, match="exact clip"):
            gateway.render_staged_clip(tmp_path, **args, run_render=lambda **k: output)


def test_legacy_render_archive_default_unchanged():
    import inspect
    assert inspect.signature(cli.cmd_render).parameters["archive_source"].default is True
