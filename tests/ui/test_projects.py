"""Minimal catalog contract: distinguish actual evidence and preserve existing data."""
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from autoreels.core.models import Manifest, SetupProfile, Crop
from autoreels.orchestr import settings
from autoreels.orchestr.app import app


def _write(root, path, content=b"fake"):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


def _manifest(root, name, status="pending", sha="a" * 64):
    m = Manifest(source=name + ".mp4", source_sha256=sha, duration_preset="shorts",
                 setup=SetupProfile(setup_id="test", crop=Crop(x=0, y=0, w=960, h=1700),
                                    scale=[1080, 1920], frame=[1920, 1080]),
                 run_key="test", status=status)
    return _write(root, "manifests/" + name + ".json", m.model_dump_json().encode())


def _history(root, records):
    _write(root, "data/history.jsonl", ("\n".join(json.dumps(r) for r in records) + "\n").encode())


def _client(root, monkeypatch):
    monkeypatch.setattr(settings, "settings", settings.Settings.from_env(root_override=str(root)))
    return TestClient(app, base_url="http://127.0.0.1:8765")


def test_catalog_states_and_no_mutation(tmp_path, monkeypatch):
    root = tmp_path
    _write(root, "inputs/NEW.mp4")
    _manifest(root, "DRAFT")
    _manifest(root, "BROKEN", "failed")
    _manifest(root, "EMPTY")
    _write(root, "manifests/DRAFT.blocks.json", b"{}")
    _write(root, "reels-out/READY/r01.mp4")
    _write(root, "reels-out/UNKNOWN/r01.ERROR.mp4")
    _history(root, [
        {"source": "EMPTY.mp4", "outcome": "zero-harvest", "reel_count": 0, "sha256": "a" * 64},
        {"source": "ERROR.mp4", "outcome": "failed", "source_path": "/not/read/ERROR.mp4"},
        {"source": "SKIPPED.mp4", "outcome": "skipped"},
    ])
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    c = _client(root, monkeypatch)
    response = c.get("/api/projects")
    assert response.status_code == 200
    rows = {r["stem"]: r for r in response.json()}
    assert {k: v["status"] for k, v in rows.items()} == {
        "NEW": "unprocessed", "DRAFT": "draft", "BROKEN": "failed",
        "EMPTY": "empty", "ERROR": "failed", "READY": "ready", "UNKNOWN": "unknown",
        "SKIPPED": "unknown",
    }
    assert rows["READY"]["can_review"] and rows["READY"]["clip_count"] == 1
    assert not rows["NEW"]["can_review"] and not rows["EMPTY"]["can_review"]
    assert "/not/read" not in response.text
    assert [r["stem"] for r in c.get("/api/sources").json()] == ["READY"]
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_ambiguous_stem_not_silently_reviewed(tmp_path, monkeypatch):
    root = tmp_path
    _write(root, "inputs/SAME.mp4")
    _write(root, "inputs-archive/SAME.mp4")
    _write(root, "reels-out/SAME/r01.mp4")
    _manifest(root, "HASH")
    _history(root, [{"source": "HASH.mp4", "sha256": "b" * 64, "outcome": "ok"}])
    rows = {r["stem"]: r for r in _client(root, monkeypatch).get("/api/projects").json()}
    for key in ("SAME", "HASH"):
        assert rows[key]["status"] == "unknown"
        assert rows[key]["detail"] == "ambiguous"
        assert rows[key]["can_review"] is False
        assert rows[key]["poster_clip"] is None
