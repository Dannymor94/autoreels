"""Display names, distinct clip counts, poster fields, manifest titles."""

import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from autoreels.orchestr import manifests  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
REAL_MANIFEST = REPO / "manifests" / "2026-08-08 09h 33m 14s.json"


@pytest.fixture()
def root(tmp_path):
    src = tmp_path / "reels-out" / "SRC"
    (src / "_gate" / "m").mkdir(parents=True)
    (src / "r01.mp4").write_bytes(b"x")
    (src / "_gate" / "m" / "r01.mp4").write_bytes(b"x")
    (src / "_gate" / "m" / "r02.mp4").write_bytes(b"x")  # r02 exists ONLY as a variant
    return tmp_path


@pytest.fixture()
def client(root):
    import autoreels.orchestr.settings as _s
    from autoreels.orchestr.settings import Settings
    _s.settings = Settings.from_env(root_override=str(root))
    from autoreels.orchestr.app import app
    return TestClient(app)


def test_clip_count_is_distinct_across_variants(client):
    src = client.get("/api/sources").json()[0]
    assert src["clip_count"] == 2  # r01 + r02, not "main only" (was 1)
    assert src["poster_clip"] == "r01" and src["poster_variant"] == ""
    assert src["display_name"] is None


def test_rename_roundtrip_and_reset(client, root):
    r = client.put("/api/sources/SRC/meta", json={"display_name": "  Лекция о дыхании  "})
    assert r.status_code == 200 and r.json() == {"stem": "SRC", "display_name": "Лекция о дыхании"}
    assert client.get("/api/sources").json()[0]["display_name"] == "Лекция о дыхании"
    stored = json.loads((root / "reviews" / "ui" / "sources.json").read_text(encoding="utf-8"))
    assert stored["schema_version"] == 1
    assert (root / "reels-out" / "SRC").is_dir()  # folder name untouched
    r = client.put("/api/sources/SRC/meta", json={"display_name": "   "})
    assert r.json()["display_name"] is None
    assert client.get("/api/sources").json()[0]["display_name"] is None


def test_rename_unknown_or_traversal_is_404(client, root):
    for stem in ("NOPE", "%2E%2E"):
        assert client.put(f"/api/sources/{stem}/meta", json={"display_name": "x"}).status_code == 404
    assert not (root / "reviews").exists()


def test_rename_is_length_limited(client):
    r = client.put("/api/sources/SRC/meta", json={"display_name": "я" * 500})
    assert len(r.json()["display_name"]) == 120


@pytest.mark.skipif(not REAL_MANIFEST.is_file(), reason="sample manifest not in repo")
def test_titles_from_real_manifest(client, root):
    (root / "manifests").mkdir()
    shutil.copy(REAL_MANIFEST, root / "manifests" / "SRC.json")
    titles = manifests.reel_titles(root, "SRC")
    assert titles.get("r01")
    clip = next(c for c in client.get("/api/sources/SRC/clips").json() if c["clip"] == "r01")
    assert clip["title"] == titles["r01"]


def test_broken_manifest_gives_no_titles(client, root):
    (root / "manifests").mkdir()
    (root / "manifests" / "SRC.json").write_text("{not json", encoding="utf-8")
    assert manifests.reel_titles(root, "SRC") == {}
    assert all(c["title"] is None for c in client.get("/api/sources/SRC/clips").json())
