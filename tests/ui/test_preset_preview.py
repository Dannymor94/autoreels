"""UI-203A: actual CLI defaults, isolated preview and scope priority."""
from pathlib import Path
import shutil

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from pydantic import ValidationError
from autoreels.orchestr import preset_preview as p, settings
from autoreels.orchestr.app import app


def test_precedence_off_parity_and_dependency():
    base = p.PresetValues(duration_preset="shorts", hook_rescue=False, filler_word_cut=True,
                          zoom=False, loudnorm=True, denoise=False,
                          two_shot=False, two_shot_auto=True)
    choices = [p.DurationChoice(name="shorts", min_sec=15, max_sec=90),
               p.DurationChoice(name="tiktok", min_sec=15, max_sec=180)]
    original = base.model_dump()
    default = p.preview(base, choices)
    blank = p.PresetLayer()
    request = p.PresetRequest(base_revision=default.base_revision, global_layer=blank,
                              project_layer=blank, clip_layer=blank)
    assert p.preview(base, choices, request) == default
    assert not default.changed_fields and not default.invalidates
    assert default.effective.two_shot_auto and not default.two_shot_auto_active
    request = p.PresetRequest(
        base_revision=default.base_revision,
        global_layer=p.PresetLayer(zoom=True, filler_word_cut=False, two_shot=True),
        project_layer=p.PresetLayer(zoom=False, duration_preset="tiktok"),
        clip_layer=p.PresetLayer(filler_word_cut=True, two_shot=False, denoise=True),
    )
    result = p.preview(base, list(reversed(choices)), request)
    assert result.effective.duration_preset == "tiktok"
    assert result.effective.filler_word_cut and not result.effective.zoom
    assert result.effective.denoise and not result.two_shot_auto_active
    assert result.changed_fields == ["denoise", "duration_preset"]
    assert result.invalidates == ["selection", "plan", "render"]
    assert base.model_dump() == original
    assert not result.execution_enabled
    with pytest.raises(ValidationError):
        p.PresetLayer(zoom="false")
    with pytest.raises(ValidationError):
        p.PresetLayer(command="ffmpeg")
    with pytest.raises(p.StalePreview):
        p.preview(p.PresetValues.model_validate({**original, "zoom":True}), choices, request)
    with pytest.raises(ValueError):
        p.preview(base, choices, p.PresetRequest(base_revision=default.base_revision,
                  global_layer=p.PresetLayer(duration_preset="reels"), project_layer=blank, clip_layer=blank))


def test_api_uses_config_overlay_and_never_touches_manual_edits(tmp_path, monkeypatch):
    folder = tmp_path / "config"
    folder.mkdir()
    repo = Path(__file__).resolve().parents[2] / "config"
    for name in ("r0.yaml", "render.yaml"):
        shutil.copyfile(repo / name, folder / name)
    local = folder / "render.local.yaml"
    local.write_text("zoom:\n  enabled: true\nffmpeg: /secret/sentinel\n")
    manual = tmp_path / "reviews" / "verdicts.jsonl"
    manual.parent.mkdir()
    manual.write_bytes(b"accepted manual decisions\n")
    before = {str(f.relative_to(tmp_path)): f.read_bytes() for f in tmp_path.rglob("*") if f.is_file()}
    monkeypatch.setattr(settings, "settings", settings.Settings(root=tmp_path))
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.get("/api/preset-preview")
        assert response.status_code == 200, response.text
        assert "secret" not in response.text
        data = response.json()
        assert data["base"]["zoom"] is True
        assert data["effective"] == data["base"]
        body = {"base_revision":data["base_revision"],"global_layer":{"zoom":True},
                "project_layer":{"zoom":False},"clip_layer":{}}
        result = client.put("/api/preset-preview", json=body)
        assert result.status_code == 200
        assert result.json()["effective"]["zoom"] is False
        assert result.json()["invalidates"] == ["render"]
        assert {str(f.relative_to(tmp_path)):f.read_bytes() for f in tmp_path.rglob("*") if f.is_file()} == before
        body["clip_layer"] = {"zoom":"false"}
        assert client.put("/api/preset-preview", json=body).status_code == 422
        body["clip_layer"] = {}
        local.write_text("zoom:\n  enabled: false\n")
        assert client.put("/api/preset-preview", json=body).status_code == 409
        local.unlink()
        local.symlink_to(tmp_path / "missing-secret")
        assert client.get("/api/preset-preview").status_code == 409
    assert manual.read_bytes() == before["reviews/verdicts.jsonl"]
