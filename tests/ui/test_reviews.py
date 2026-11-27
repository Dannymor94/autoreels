"""UI-103: exact bytes, durable local review, idempotency and export isolation."""
import hashlib
import json
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from autoreels.orchestr import settings
from autoreels.orchestr.app import app


@pytest.fixture()
def review_fixture(tmp_path, monkeypatch):
    root = tmp_path
    video = root / "reels-out" / "DEMO" / "r01.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"synthetic-video-v1")
    legacy = root / "reviews" / "verdicts.jsonl"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"stem":"DEMO","rid":"r01","gate":"auto","verdict":"ok","note":"old"})+"\n")
    draft = root / "reviews" / "DEMO_auto.txt"
    draft.write_text("unchanged")
    monkeypatch.setattr(settings, "settings", settings.Settings.from_env(root_override=str(root)))
    return root, video, legacy, draft, TestClient(app, base_url="http://127.0.0.1:8765")


URL = "/api/reviews/DEMO/r01"
MEDIA = "/api/media/DEMO/r01"


def _body(sha, **kw):
    return {"request_id":str(uuid4()), "artifact_sha256":sha, "base_revision":None,
            "verdict":"keep", "comment":"good", "position_s":0.25, **kw}


def test_save_reload_retry_and_legacy_isolation(review_fixture):
    root, video, legacy, draft, client = review_fixture
    before_legacy, before_draft = legacy.read_bytes(), draft.read_bytes()
    state = client.get(URL).json()
    sha = hashlib.sha256(video.read_bytes()).hexdigest()
    assert state["artifact_sha256"] == sha and state["current"] is None
    assert state["legacy"][0]["verdict"] == "ok"
    assert not (root/"reviews/ui").exists()  # GET never creates a store
    body = _body(sha)
    saved = client.put(URL, json=body)
    assert saved.status_code == 200
    assert saved.json()["current"]["verdict"] == "keep"
    assert client.get(URL).json() == saved.json()
    assert client.put(URL, json=body).json() == saved.json()
    assert client.put(URL, json={**body, "comment":"different"}).status_code == 409
    assert client.put(URL, json=_body(sha, verdict="fix")).status_code == 409
    changed = client.put(URL, json=_body(sha, base_revision=body["request_id"], verdict="fix"))
    assert changed.status_code == 200
    assert changed.json()["current"]["verdict"] == "fix"
    assert len(changed.json()["history"]) == 2
    assert legacy.read_bytes() == before_legacy and draft.read_bytes() == before_draft
    assert video.read_bytes() == b"synthetic-video-v1"


def test_replacement_does_not_inherit_review_and_versioned_playback(review_fixture):
    root, video, _, _, client = review_fixture
    sha = client.get(URL).json()["artifact_sha256"]
    body = _body(sha)
    assert client.put(URL, json=body).status_code == 200
    response = client.get(MEDIA, params={"artifact":sha}, headers={"Range":"bytes=2-5"})
    assert response.status_code == 206 and response.content == video.read_bytes()[2:6]
    assert response.headers["content-range"] == f"bytes 2-5/{video.stat().st_size}"
    variant = video.parent / "_gate" / "b" / video.name
    variant.parent.mkdir(parents=True)
    variant.write_bytes(video.read_bytes())
    assert client.get(URL, params={"variant":"_gate/b"}).json()["current"] is None
    video.write_bytes(b"synthetic-video-v2")
    state = client.get(URL).json()
    assert state["artifact_sha256"] != sha and state["current"] is None
    assert state["history"][0]["artifact_sha256"] == sha
    assert client.put(URL, json=body).status_code == 409
    assert client.get(MEDIA, params={"artifact":sha}).status_code == 409
    assert client.get(MEDIA, params={"artifact":state["artifact_sha256"]}).content == video.read_bytes()
    assert client.get(MEDIA, params={"artifact":state["artifact_sha256"]}, headers={"Range":"bytes=999-"}).status_code == 416
    assert client.put(URL, json=_body(state["artifact_sha256"], position_s=-1)).status_code == 422
    assert client.put(URL, json=_body(state["artifact_sha256"], verdict="ok")).status_code == 422
    assert len(client.get(URL).json()["history"]) == 1


def test_pair_preference_is_bound_to_both_artifacts(review_fixture):
    root, video, legacy, draft, client = review_fixture
    variant = video.parent / "_gate" / "b" / video.name
    variant.parent.mkdir(parents=True)
    variant.write_bytes(b"synthetic-other")
    url = "/api/comparisons/DEMO/r01"
    params = {"left":"", "right":"_gate/b"}
    before = legacy.read_bytes(), draft.read_bytes()
    state = client.get(url, params=params).json()
    assert state["current"] is None
    assert not (root/"reviews/ui").exists()
    body = {"request_id":str(uuid4()), "left_sha256":state["left_sha256"],
            "right_sha256":state["right_sha256"], "base_revision":None,
            "winner":"_gate/b", "comment":"better"}
    saved = client.put(url, params=params, json=body)
    assert saved.status_code == 200
    assert saved.json()["current"]["winner"] == "_gate/b"
    assert client.put(url, params=params, json=body).json() == saved.json()
    assert client.get(url, params={"left":"_gate/b","right":""}).json() == saved.json()
    assert client.put(url, params=params, json={**body, "winner":"other"}).status_code == 422
    assert client.put(url, params=params, json={**body, "request_id":str(uuid4())}).status_code == 409
    assert client.get(URL).json()["current"] is None
    variant.write_bytes(b"replacement")
    stale = client.get(url, params=params).json()
    assert stale["current"] is None and len(stale["history"]) == 1
    assert client.put(url, params=params, json=body).status_code == 409
    assert (legacy.read_bytes(), draft.read_bytes()) == before
    assert client.get(url, params={"left":"","right":""}).status_code == 422
