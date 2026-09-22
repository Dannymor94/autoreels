"""Part E: resolve a manifest's transcript by source_sha256 (stable) before the re-extractable audio
hash (E.2); backfill-source-sha accepts both a path and a bare name without doubling data/cache/ (E.3)."""
import json

import pytest

from autoreels import __main__ as cli
from autoreels.core import state
from autoreels.core.models import Manifest, SetupProfile, Crop, Transcript, Word


def _manifest(sha="s" * 64, pkey=""):
    return Manifest(source="v.mp4", source_sha256=sha, duration_preset="shorts",
                    setup=SetupProfile(setup_id="s", crop=Crop(x=0, y=0, w=10, h=20),
                                       scale=[1080, 1920], frame=[1920, 1080]),
                    run_key="rk", transcript_params_key=pkey)


def _write_tx(cache, name, *, sha256="", provider="groq", model="whisper", words=(("hi", 0.0, 0.5),)):
    t = Transcript(language="ru", source_sha256=sha256, provider=provider, model=model,
                   words=[Word(word=w, t0=a, t1=b) for w, a, b in words])
    (cache / name).write_text(t.model_dump_json(), encoding="utf-8")
    return t


# ---------------- E.2: transcript resolution ----------------

def test_resolves_by_source_sha256_when_audio_orphaned(tmp_path):
    # Transcript filename keyed by a stale audio hash, no mp3 in cache → the old audio-hash chain
    # would find nothing. The content stamp source_sha256 still links it to the manifest.
    cache = tmp_path / "cache"; cache.mkdir()
    _write_tx(cache, "STALEHASH.abc123.transcript.json", sha256="s" * 64)
    got = cli._resolve_cached_transcript(_manifest(sha="s" * 64), cache)
    assert got is not None and got.source_sha256 == "s" * 64


def test_prefers_matching_params_key(tmp_path):
    cache = tmp_path / "cache"; cache.mkdir()
    _write_tx(cache, "h1.transcript.json", sha256="s" * 64, provider="groq", model="whisper-a")
    _write_tx(cache, "h2.transcript.json", sha256="s" * 64, provider="groq", model="whisper-b")
    want = cli.transcript_identity(Transcript(language="ru", provider="groq", model="whisper-b"))
    got = cli._resolve_cached_transcript(_manifest(sha="s" * 64, pkey=want), cache)
    assert got is not None and got.model == "whisper-b"


def test_falls_back_to_audio_hash_for_legacy_transcript(tmp_path, monkeypatch):
    # Legacy transcript with no source_sha256 stamp, keyed by the mp3 audio hash.
    cache = tmp_path / "cache"; cache.mkdir()
    (cache / f"{'s' * 64}.mp3").write_bytes(b"audio")
    monkeypatch.setattr(state, "audio_hash", lambda p: "AH")
    _write_tx(cache, "AH.transcript.json", sha256="", words=(("legacy", 0.0, 0.4),))
    got = cli._resolve_cached_transcript(_manifest(sha="s" * 64), cache)
    assert got is not None and got.words[0].word == "legacy"


def test_returns_none_when_nothing_matches(tmp_path):
    cache = tmp_path / "cache"; cache.mkdir()
    _write_tx(cache, "other.transcript.json", sha256="d" * 64)   # different source
    assert cli._resolve_cached_transcript(_manifest(sha="s" * 64), cache) is None


# ---------------- E.3: backfill-source-sha path handling ----------------

def test_backfill_accepts_path_without_doubling(tmp_path, monkeypatch, capsys):
    cache = tmp_path / "data" / "cache"; cache.mkdir(parents=True)
    _write_tx(cache, "x.transcript.json", sha256="a" * 64)       # already stamped → skip branch
    monkeypatch.chdir(tmp_path)
    # a shell-expanded path relative to cwd must be used as-is, not prepended to cache (→ doubling)
    rc = cli.cmd_backfill_source_sha(["data/cache/x.transcript.json"], cache_dir=cache, root=tmp_path)
    out = capsys.readouterr()
    assert rc == 0
    assert "not found" not in (out.out + out.err)
    assert "skip" in out.out                                     # found, already set


def test_backfill_accepts_bare_name(tmp_path, capsys):
    cache = tmp_path / "data" / "cache"; cache.mkdir(parents=True)
    _write_tx(cache, "x.transcript.json", sha256="a" * 64)
    rc = cli.cmd_backfill_source_sha(["x.transcript.json"], cache_dir=cache, root=tmp_path)
    out = capsys.readouterr()
    assert rc == 0 and "not found" not in (out.out + out.err) and "skip" in out.out
