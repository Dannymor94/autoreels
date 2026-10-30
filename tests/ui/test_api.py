import json
import os
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


@pytest.fixture()
def tmp_root(tmp_path):
    reels = tmp_path / "reels-out" / "DEMO"
    reels.mkdir(parents=True)
    gate = reels / "_gate" / "variant_b"
    gate.mkdir(parents=True)

    fake_mp4 = b"\x00" * 200

    for name in ("r01", "r02"):
        (reels / f"{name}.mp4").write_bytes(fake_mp4)
        (reels / f"{name}.render.json").write_text(json.dumps({"fingerprint": f"fp_{name}"}))
    (gate / "r01.mp4").write_bytes(fake_mp4)

    return tmp_path


@pytest.fixture()
def client(tmp_root):
    import autoreels.orchestr.settings as _s
    from autoreels.orchestr.settings import Settings
    _s.settings = Settings.from_env(root_override=str(tmp_root))

    from autoreels.orchestr.app import app
    return TestClient(app, raise_server_exceptions=True)


def test_health(client, tmp_root):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["schema_version"] == 1
    assert data["root"] == str(tmp_root.resolve())


def test_sources(client):
    r = client.get("/api/sources")
    assert r.status_code == 200
    stems = [s["stem"] for s in r.json()]
    assert "DEMO" in stems
    demo = next(s for s in r.json() if s["stem"] == "DEMO")
    assert demo["clip_count"] > 0


def test_clips(client):
    r = client.get("/api/sources/DEMO/clips")
    assert r.status_code == 200
    clips = [c["clip"] for c in r.json() if c["variant"] == ""]
    assert "r01" in clips


def test_clips_gate_variant(client):
    r = client.get("/api/sources/DEMO/clips")
    assert r.status_code == 200
    variants = [c["variant"] for c in r.json()]
    assert "_gate/variant_b" in variants


def test_clips_fingerprint(client):
    r = client.get("/api/sources/DEMO/clips")
    clips = {(c["clip"], c["variant"]): c for c in r.json()}
    assert clips[("r01", "")]["fingerprint"] == "fp_r01"


def test_range_206(client):
    r = client.get("/api/media/DEMO/r01", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206
    assert len(r.content) == 100


def test_traversal_stem(client):
    r = client.get("/api/media/../x/r01")
    assert r.status_code == 404


def test_traversal_clip(client):
    r = client.get("/api/media/DEMO/../../etc/passwd")
    assert r.status_code == 404


def test_traversal_variant(client):
    r = client.get("/api/media/DEMO/r01?variant=_gate/../../x")
    assert r.status_code == 404


def test_symlink_outside(client, tmp_root):
    evil = tmp_path_factory = tmp_root.parent / "evil.mp4"
    evil.write_bytes(b"\x00" * 50)
    link = tmp_root / "reels-out" / "DEMO" / "r99.mp4"
    link.symlink_to(evil)
    r = client.get("/api/media/DEMO/r99")
    assert r.status_code == 404


def test_default_bind():
    from autoreels.orchestr.settings import Settings
    s = Settings.from_env()
    assert s.root.is_absolute()
    assert s.port == 8765


# --- added in U1-fix ---------------------------------------------------------

def test_each_test_gets_its_own_root(tmp_path):
    """Guard: the app must read settings at call time, not at import time."""
    import autoreels.orchestr.settings as _s
    from autoreels.orchestr.settings import Settings
    from autoreels.orchestr.app import app

    roots = [tmp_path / "a", tmp_path / "b"]
    for r in roots:
        (r / "reels-out").mkdir(parents=True)
        _s.settings = Settings.from_env(root_override=str(r))
        assert TestClient(app).get("/api/health").json()["root"] == str(r.resolve())


def test_clips_listing_traversal_rejected(client, tmp_root):
    (tmp_root / "r09.mp4").write_bytes(b"secret")   # one level above reels-out
    for stem in ("%2E%2E", "..", "%2E%2E%2F%2E%2E"):
        assert client.get(f"/api/sources/{stem}/clips").status_code == 404


def test_error_files_not_listed(client, tmp_root):
    (tmp_root / "reels-out" / "DEMO" / "r01.ERROR.mp4").write_bytes(b"x")
    clips = [c["clip"] for c in client.get("/api/sources/DEMO/clips").json()]
    assert "r01.ERROR" not in clips
    src = client.get("/api/sources").json()[0]
    assert src["clip_count"] == 2


def test_symlink_outside_not_listed(client, tmp_root):
    evil = tmp_root.parent / "evil2.mp4"
    evil.write_bytes(b"\x00" * 50)
    (tmp_root / "reels-out" / "DEMO" / "r98.mp4").symlink_to(evil)
    clips = [c["clip"] for c in client.get("/api/sources/DEMO/clips").json()]
    assert "r98" not in clips
