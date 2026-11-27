"""UI-105 security boundary; all fixtures and credentials are synthetic."""
import hashlib
import json
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from autoreels.orchestr import settings
from autoreels.orchestr.app import app

ORIGIN = "https://gamebox.example.test"
PASSWORD = "synthetic-only-not-a-real-password"
AUTH = ("owner", PASSWORD)


def _peer(host):
    async def proxy(scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope, client=(host, 12345))
        await app(scope, receive, send)
    return proxy


@pytest.fixture()
def private(tmp_path, monkeypatch):
    root = tmp_path / "root"
    source = root / "reels-out" / "DEMO"
    (source / "_gate" / "b").mkdir(parents=True)
    (source / "r01.mp4").write_bytes(b"0123456789")
    (source / "_gate" / "b" / "r01.mp4").write_bytes(b"variant")
    monkeypatch.setattr(settings, "settings", settings.Settings(
        root=root, private_origin=ORIGIN,
        owner_digest=SecretStr(hashlib.sha256(PASSWORD.encode()).hexdigest()),
    ))
    with TestClient(_peer("127.0.0.1"), base_url=ORIGIN) as client:
        yield root, source, client


def test_private_auth_applies_to_all_reads_and_writes(private):
    root, _, c = private
    paths = ["/", "/docs", "/openapi.json", "/api/health", "/api/projects",
             "/api/sources", "/api/sources/DEMO/clips", "/api/render-targets", "/api/pipeline-settings", "/api/jobs", "/api/preset-preview",
             "/api/reviews/DEMO/r01", "/api/comparisons/DEMO/r01?left=&right=_gate/b",
             "/api/thumb/DEMO/r01", "/api/media/DEMO/r01",
             "/api/media/DEMO/r01?artifact="+"a"*64]
    for path in paths:
        r = c.get(path, headers={"Range":"bytes=0-1","Tailscale-User-Login":"owner@example.test"})
        assert r.status_code == 401, path
        assert r.headers["cache-control"] == "no-store, private"
    assert c.get("/api/health", auth=("not-owner", PASSWORD)).status_code == 401
    assert c.get("/api/health", auth=("owner", "wrong")).status_code == 401
    assert c.put("/api/sources/DEMO/meta", json={"display_name":"bad"}).status_code == 401
    assert c.put("/api/preset-preview", json={}).status_code == 401
    assert c.put("/api/preset-preview", auth=AUTH, json={}).status_code == 403
    assert c.put("/api/jobs/" + str(uuid4()), json={"action":"create","target_kind":"mobile","outcome":"success"}).status_code == 401
    assert c.put("/api/jobs/" + str(uuid4()), auth=AUTH, json={"action":"create","target_kind":"mobile","outcome":"success"}).status_code == 403
    assert not (root/"reviews").exists()
    assert c.get("/api/health", auth=AUTH, headers={"Host":"attacker.example"}).status_code == 403
    assert c.get("/api/health", auth=AUTH, headers={"Origin":"https://attacker.example"}).status_code == 403
    assert c.get("/api/media/DEMO/r01", auth=AUTH, headers={"Sec-Fetch-Site":"cross-site"}).status_code == 403
    with TestClient(_peer("192.0.2.1"), base_url=ORIGIN) as outside:
        assert outside.get("/api/health", auth=AUTH, headers={"X-Forwarded-For":"127.0.0.1"}).status_code == 403
    health = c.get("/api/health", auth=AUTH)
    assert health.status_code == 200 and health.json()["root"] == "private"
    assert str(root) not in health.text
    assert health.headers["x-frame-options"] == "DENY"
    assert health.headers["referrer-policy"] == "no-referrer"


def test_private_owner_can_review_compare_and_seek(private):
    root, _, c = private
    headers = {"Origin":ORIGIN}
    assert c.get("/api/projects", auth=AUTH).json()[0]["stem"] == "DEMO"
    review = "/api/reviews/DEMO/r01"
    sha = c.get(review, auth=AUTH).json()["artifact_sha256"]
    body = {"request_id":str(uuid4()), "artifact_sha256":sha, "base_revision":None,
            "verdict":"keep", "comment":"synthetic", "position_s":0.0}
    assert c.put(review, auth=AUTH, json=body).status_code == 403
    assert c.put(review, auth=AUTH, headers={"Origin":"https://attacker.example"}, json=body).status_code == 403
    assert not (root/"reviews").exists()
    assert c.put(review, auth=AUTH, headers=headers, json=body).status_code == 200
    assert c.get(review, auth=AUTH).json()["current"]["verdict"] == "keep"
    pair = "/api/comparisons/DEMO/r01?left=&right=_gate/b"
    state = c.get(pair, auth=AUTH).json()
    choice = {"request_id":str(uuid4()), "left_sha256":state["left_sha256"],
              "right_sha256":state["right_sha256"], "base_revision":None,
              "winner":"_gate/b", "comment":"synthetic"}
    assert c.put(pair, auth=AUTH, headers=headers, json=choice).status_code == 200
    assert c.get(pair, auth=AUTH).json()["current"]["winner"] == "_gate/b"
    media = "/api/media/DEMO/r01?artifact=" + sha
    r = c.get(media, auth=AUTH, headers={"Range":"bytes=2-5"})
    assert r.status_code == 206 and r.content == b"2345"
    assert r.headers["cache-control"] == "no-store, private"
    for bad in ("bytes=0-1,3-4","garbage","bytes=999-","bytes=0-999999999999999999999"):
        assert c.get(media, auth=AUTH, headers={"Range":bad}).status_code == 416
    assert c.put("/api/sources/DEMO/meta", auth=AUTH, headers=headers,
                 json={"display_name":"x"*20000}).status_code == 413
    assert c.put("/api/sources/DEMO/meta", auth=AUTH, headers=headers,
                 content=b"not json").status_code == 415
    assert not (root/"reviews/verdicts.jsonl").exists()


def test_symlinks_and_sidecars_fail_closed(private, tmp_path):
    root, source, c = private
    secret = tmp_path / "secret.mp4"
    secret.write_bytes(b"never disclose")
    (source/"r99.mp4").symlink_to(secret)
    (source/"r01.txt").symlink_to(secret)
    (source/"r01.render.json").symlink_to(secret)
    other = root/"reels-out"/"OTHER"
    other.mkdir()
    (other/"r01.mp4").write_bytes(b"other source")
    (source/"r98.mp4").symlink_to(other/"r01.mp4")
    for clip in ("r99","r98"):
        assert c.get(f"/api/media/DEMO/{clip}", auth=AUTH).status_code == 404
        assert c.get(f"/api/reviews/DEMO/{clip}", auth=AUTH).status_code == 404
    assert c.get("/api/media/DEMO/r01?variant=_gate/..", auth=AUTH).status_code == 404
    rows = c.get("/api/sources/DEMO/clips", auth=AUTH).json()
    assert all(r["clip"]=="r01" and r["caption"] is None and r["fingerprint"] is None for r in rows)
    # A symlinked metadata destination must not be read or overwritten.
    outside = tmp_path/"external"
    outside.mkdir()
    (root/"reviews").symlink_to(outside, target_is_directory=True)
    assert c.put("/api/sources/DEMO/meta", auth=AUTH, headers={"Origin":ORIGIN},
                 json={"display_name":"bad"}).status_code == 409
    assert not list(outside.iterdir())
    # A whole reels-out symlink is also denied, not just child paths.
    (root/"reels-out").rename(root/"renamed")
    (root/"reels-out").symlink_to(root/"renamed", target_is_directory=True)
    assert c.get("/api/media/DEMO/r01", auth=AUTH).status_code == 404
    assert c.get("/api/sources", auth=AUTH).json() == []


def test_local_defaults_and_private_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "settings", settings.Settings(root=tmp_path))
    c = TestClient(app, base_url="http://127.0.0.1:8765")
    assert c.get("/api/health").json()["root"] == str(tmp_path)
    assert c.get("/api/health", headers={"Host":"attacker.example"}).status_code == 403
    assert c.get("/api/health", headers={"Origin":"https://attacker.example"}).status_code == 403
    digest = SecretStr("a"*64)
    for origin in ("http://example.test","https://example.test/path","https://user@example.test",
                   "https://example.test?x=1"):
        with pytest.raises(ValidationError):
            settings.Settings(root=tmp_path, private_origin=origin, owner_digest=digest)
    with pytest.raises(ValidationError):
        settings.Settings(root=tmp_path, private_origin=ORIGIN)
    assert PASSWORD not in repr(settings.Settings(root=tmp_path, private_origin=ORIGIN, owner_digest=digest))
