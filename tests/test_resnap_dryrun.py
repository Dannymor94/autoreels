"""Tests for resnap --dry-run and block-set sidecar (iteration-loop speed improvements).

Tests 1-2: resnap --dry-run writes nothing / preview with fallback transcript.
Test 5: block sidecar round-trips (see test_blocks_sidecar.py for full coverage).
"""
import json
from pathlib import Path

import pytest

from autoreels import __main__ as cli
from autoreels.cloud.transcribe import params_key
from autoreels.core import state
from autoreels.core.models import Crop, Manifest, Reel, SetupProfile, Word

REPO_ROOT = Path(__file__).resolve().parents[1]

_META = {"provider": "groq", "model": "whisper-large-v3", "prompt_hash": "ph1"}
KEY = params_key(_META)

_WORDS = [
    {"word": "Первое", "t0": 0.0, "t1": 0.5},
    {"word": "слово.", "t0": 0.6, "t1": 1.0},
    {"word": "Второе", "t0": 2.0, "t1": 2.5},
    {"word": "слово.", "t0": 2.6, "t1": 3.0},
]


def _setup(tmp_path, *, manifest_key: str, reels=None):
    """Lay out a manifest + cached transcript. Returns (manifests_dir, cache_dir, manifest_path)."""
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    sha = "a" * 64
    audio = cache / f"{sha}.mp3"
    audio.write_bytes(b"MP3")
    ah = state.audio_hash(audio)
    if manifest_key:
        (cache / f"{ah}.{manifest_key}.transcript.json").write_text(
            json.dumps({"language": "ru", "words": _WORDS, **_META}), encoding="utf-8"
        )
    if reels is None:
        reels = [
            Reel(id="r01", start=0.5, end=2.9, r0_start=0.0, r0_end=3.0,
                 score=80, hook="h", title="T", description="d", reason="r", topic="x"),
        ]
    m = Manifest(
        source="v.mp4", source_sha256=sha, source_hash_scheme="partial-p1",
        duration_preset="shorts",
        setup=SetupProfile(setup_id="t", crop=Crop(x=0, y=0, w=960, h=1700),
                           scale=[1080, 1920], frame=[1920, 1080]),
        run_key="rk", transcript_params_key=manifest_key, reels=reels,
    )
    mpath = manifests / "v.json"
    mpath.write_text(m.model_dump_json(), encoding="utf-8")
    return manifests, cache, mpath


# ---------------------------------------------------------------------------
# Test 1: dry-run writes nothing, manifest byte-identical afterwards
# ---------------------------------------------------------------------------

def test_dryrun_writes_nothing(tmp_path, monkeypatch):
    """--dry-run: manifest is byte-identical after the call; no git push."""
    manifests, cache, mpath = _setup(tmp_path, manifest_key=KEY)
    original_bytes = mpath.read_bytes()

    # Stub out git pull/push so the test works without a real repo
    monkeypatch.setattr(cli, "_git_pull", lambda *a, **k: None)
    push_calls = []
    monkeypatch.setattr(cli, "_commit_push_manifest", lambda *a, **k: push_calls.append(1))

    rc = cli.cmd_resnap(
        video="v.mp4",
        root=REPO_ROOT,
        manifests_dir=str(manifests),
        cache_dir=str(cache),
        push=True,       # push=True, but dry_run must override it
        pull_first=False,
        dry_run=True,
    )

    assert rc == 0
    assert mpath.read_bytes() == original_bytes, "manifest was modified in dry-run mode"
    assert not push_calls, "git push was called in dry-run mode"


# ---------------------------------------------------------------------------
# Test 2a: dry-run with missing params_key shows warning; real resnap still refuses
# ---------------------------------------------------------------------------

def test_dryrun_missing_pkey_previews_with_warning(tmp_path, monkeypatch, capsys):
    """dry-run + empty transcript_params_key: preview printed, warning emitted (no refusal)."""
    # manifest_key="" means no params_key; no keyed transcript in cache
    # But we need SOME transcript — write one keyed by current config's pkey
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    sha = "b" * 64
    audio = cache / f"{sha}.mp3"
    audio.write_bytes(b"MP3")
    ah = state.audio_hash(audio)
    # Write transcript keyed to "current config" pkey (any key — monkeypatched below)
    fallback_key = KEY
    (cache / f"{ah}.{fallback_key}.transcript.json").write_text(
        json.dumps({"language": "ru", "words": _WORDS, **_META}), encoding="utf-8"
    )
    reels = [
        Reel(id="r01", start=0.5, end=2.9, r0_start=0.0, r0_end=3.0,
             score=80, hook="h", title="T", description="d", reason="r", topic="x"),
    ]
    m = Manifest(
        source="v.mp4", source_sha256=sha, source_hash_scheme="partial-p1",
        duration_preset="shorts",
        setup=SetupProfile(setup_id="t", crop=Crop(x=0, y=0, w=960, h=1700),
                           scale=[1080, 1920], frame=[1920, 1080]),
        run_key="rk", transcript_params_key="",  # ← empty, triggers dry-run best-effort path
        reels=reels,
    )
    mpath = manifests / "v.json"
    mpath.write_text(m.model_dump_json(), encoding="utf-8")
    original_bytes = mpath.read_bytes()

    monkeypatch.setattr(cli, "_git_pull", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_config_params_key", lambda root: fallback_key)

    rc = cli.cmd_resnap(
        video="v.mp4",
        root=REPO_ROOT,
        manifests_dir=str(manifests),
        cache_dir=str(cache),
        push=False,
        pull_first=False,
        dry_run=True,
    )

    assert rc == 0
    assert mpath.read_bytes() == original_bytes, "dry-run with fallback transcript must not write"
    stderr = capsys.readouterr().err
    assert "dry-run" in stderr.lower() or "dry_run" in stderr.lower() or "dry" in stderr.lower()
    assert "transcript_params_key" in stderr or "params_key" in stderr


def test_real_resnap_refuses_missing_pkey(tmp_path, monkeypatch, capsys):
    """Real resnap (not dry-run) still refuses a manifest with empty transcript_params_key."""
    manifests, cache, mpath = _setup(tmp_path, manifest_key="")
    original_bytes = mpath.read_bytes()

    monkeypatch.setattr(cli, "_git_pull", lambda *a, **k: None)

    rc = cli.cmd_resnap(
        video="v.mp4",
        root=REPO_ROOT,
        manifests_dir=str(manifests),
        cache_dir=str(cache),
        push=False,
        pull_first=False,
        dry_run=False,
    )

    assert rc == 0   # batch mode: refusal is not a fatal error (just skipped)
    assert mpath.read_bytes() == original_bytes, "resnap must refuse to write without params_key"
    stderr = capsys.readouterr().err
    assert "ОТКАЗАН" in stderr or "refuse" in stderr.lower() or "transcript_params_key" in stderr
