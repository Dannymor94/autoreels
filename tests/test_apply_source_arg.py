"""Tests for --apply source-argument handling and transcript-as-source.

1. Bare score lines (no # source: header) apply when source is given as argument.
2. A header disagreeing with the argument is refused, naming both.
3. --apply from a transcript finds a manifest and produces output, or refuses
   with missing fields named when no manifest exists.
"""
import json
from pathlib import Path

import pytest

from autoreels import __main__ as cli
from autoreels.cloud.transcribe import params_key, transcript_identity
from autoreels.core import state
from autoreels.core.models import Crop, Manifest, SetupProfile

REPO_ROOT = Path(__file__).resolve().parents[1]

_META = {"provider": "groq", "model": "whisper-large-v3", "prompt_hash": "ph2"}
KEY = params_key(_META)

_WORDS = []
for group_offset in (0.0, 25.0, 50.0):
    for i in range(18):
        _WORDS.append({"word": f"word{i}.", "t0": group_offset + i * 1.0, "t1": group_offset + i * 1.0 + 0.5})


def _setup(tmp_path, *, manifest_key: str = KEY):
    """Create cache (mp3 + transcript) + manifest. Returns (root, cache, mpath, tpath)."""
    (tmp_path / "manifests").mkdir()
    (tmp_path / "reviews").mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    sha = "c" * 64
    mp3 = cache / f"{sha}.mp3"
    mp3.write_bytes(b"AUDIO")
    ah = state.audio_hash(mp3)
    tpath = cache / f"{ah}.{KEY}.transcript.json"
    # source_sha256 = mp3.stem (stamped at transcription time since the fix)
    tpath.write_text(
        json.dumps({"language": "ru", "words": _WORDS, "source_sha256": sha, **_META}),
        encoding="utf-8",
    )
    m = Manifest(
        source="v.mp4", source_sha256=sha, source_hash_scheme="partial-p1",
        source_path="/originals/v.mp4",
        duration_preset="shorts",
        setup=SetupProfile(setup_id="t", crop=Crop(x=0, y=0, w=960, h=1700),
                           scale=[1080, 1920], frame=[1920, 1080]),
        run_key="rk2", transcript_params_key=manifest_key,
        source_kind="lecture", reels=[],
    )
    mpath = tmp_path / "manifests" / "v.json"
    mpath.write_text(m.model_dump_json(), encoding="utf-8")
    return tmp_path, cache, mpath, tpath


# ---------------------------------------------------------------------------
# Test 1: no # source: header — source from CLI argument
# ---------------------------------------------------------------------------

def test_apply_no_header_uses_source_argument(tmp_path):
    """Bare score lines with no # source: header apply when source is given as argument."""
    root, cache, mpath, _ = _setup(tmp_path)
    out_path = REPO_ROOT / "reviews" / "v__test_noheader__.review.json"
    out_path.unlink(missing_ok=True)
    try:
        test_mpath = tmp_path / "manifests" / "v__test_noheader__.json"
        test_mpath.write_text(mpath.read_text(), encoding="utf-8")

        # Review file has NO # source: line — only score lines
        review = "1: 80\n2: 75\n"
        rpath = tmp_path / "reviews" / "bare.review.md"
        rpath.write_text(review, encoding="utf-8")

        rc = cli._blocks_do_apply(
            str(rpath), root=REPO_ROOT, cache_dir=str(cache),
            source=str(test_mpath),
        )
        assert rc == 0, "should succeed when source is given as argument"
        assert out_path.exists(), "output manifest must be written"
    finally:
        out_path.unlink(missing_ok=True)
        (REPO_ROOT / "reviews" / "v__test_noheader__._low_speech_density.json").unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Test 2: header disagrees with argument → refused, both named
# ---------------------------------------------------------------------------

def test_apply_source_conflict_refused(tmp_path, capsys):
    """When # source: header and CLI argument point to different files, refuse naming both."""
    root, cache, mpath, _ = _setup(tmp_path)
    other = tmp_path / "manifests" / "other.json"
    other.write_text(mpath.read_text(), encoding="utf-8")

    review = f"# source: {mpath}\n1: 80\n"
    rpath = tmp_path / "reviews" / "conflict.review.md"
    rpath.write_text(review, encoding="utf-8")

    rc = cli._blocks_do_apply(
        str(rpath), root=REPO_ROOT, cache_dir=str(cache),
        source=str(other),
    )
    assert rc != 0

    err = capsys.readouterr().err
    assert "conflict" in err.lower() or "≠" in err
    # Both paths must be named in the error message
    assert str(mpath) in err or mpath.name in err
    assert str(other) in err or other.name in err


# ---------------------------------------------------------------------------
# Test 3a: --apply from transcript, matching manifest exists → produces output
# ---------------------------------------------------------------------------

def test_apply_from_transcript_with_manifest(tmp_path):
    """--apply with a transcript as source finds the matching manifest and produces output."""
    root, cache, mpath, tpath = _setup(tmp_path)
    out_path = REPO_ROOT / "reviews" / "v__test_tx_src__.review.json"
    out_path.unlink(missing_ok=True)
    try:
        # Rename manifest so stem is unique for output
        test_mpath = tmp_path / "manifests" / "v__test_tx_src__.json"
        test_mpath.write_text(mpath.read_text(), encoding="utf-8")
        mpath.unlink()  # remove original so only test_mpath matches

        review = "1: 80\n"
        rpath = tmp_path / "reviews" / "tx.review.md"
        rpath.write_text(review, encoding="utf-8")

        rc = cli._blocks_do_apply(
            str(rpath), root=REPO_ROOT, cache_dir=str(cache),
            manifests_dir=str(tmp_path / "manifests"),
            source=str(tpath),   # ← transcript as source
        )
        assert rc == 0, "should succeed: transcript + matching manifest in manifests/"
        assert out_path.exists()
        result = Manifest.model_validate_json(out_path.read_text(encoding="utf-8"))
        assert result.transcript_params_key == KEY
        assert result.selection_source == "human"
    finally:
        out_path.unlink(missing_ok=True)
        (REPO_ROOT / "reviews" / "v__test_tx_src__._low_speech_density.json").unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Test 3b: --apply from transcript, no manifest exists → refuses with missing fields named
# ---------------------------------------------------------------------------

def test_apply_from_transcript_no_manifest_refuses(tmp_path, capsys):
    """--apply with transcript as source refuses when no manifest matches, naming missing fields."""
    root, cache, mpath, tpath = _setup(tmp_path)
    # Remove the manifest so there is nothing to match
    mpath.unlink()

    review = "1: 80\n"
    rpath = tmp_path / "reviews" / "nobase.review.md"
    rpath.write_text(review, encoding="utf-8")

    rc = cli._blocks_do_apply(
        str(rpath), root=REPO_ROOT, cache_dir=str(cache),
        source=str(tpath),
    )
    assert rc != 0

    err = capsys.readouterr().err
    # Error message must mention the missing fields
    for field in ("source", "setup", "run_key", "duration_preset"):
        assert field in err, f"missing field {field!r} not mentioned in error: {err!r}"


# ---------------------------------------------------------------------------
# Test 3c: --apply from legacy transcript (no source_sha256) → clear error
# ---------------------------------------------------------------------------

def test_apply_from_legacy_transcript_refuses(tmp_path, capsys):
    """--apply with a legacy transcript (source_sha256='') refuses with a clear error."""
    root, cache, mpath, _ = _setup(tmp_path)
    sha = "c" * 64
    mp3 = cache / f"{sha}.mp3"
    ah = state.audio_hash(mp3)
    # Legacy transcript: no source_sha256 field
    legacy_tpath = cache / f"{ah}.{KEY}.legacy.transcript.json"
    legacy_tpath.write_text(
        json.dumps({"language": "ru", "words": _WORDS, **_META}),  # no source_sha256
        encoding="utf-8",
    )

    review = "1: 80\n"
    rpath = tmp_path / "reviews" / "legacy.review.md"
    rpath.write_text(review, encoding="utf-8")

    rc = cli._blocks_do_apply(
        str(rpath), root=REPO_ROOT, cache_dir=str(cache),
        source=str(legacy_tpath),
    )
    assert rc != 0
    err = capsys.readouterr().err
    # Must name the fix and the missing link
    assert "source_sha256" in err or "backfill" in err.lower()
    assert "missing" in err.lower() or "no source_sha256" in err.lower() or "stamp" in err.lower()


# ---------------------------------------------------------------------------
# Test: chained splice warning
# ---------------------------------------------------------------------------

def _setup_chained(tmp_path):
    """Like _setup but with 4 groups at t=40,80,120,160 (25 words each).
    Groups 1-3 survive; group 4 (midpoint 172s > tail_boundary 154s) is dropped → 3 kept blocks.
    density=0.51 > 0.4 threshold."""
    from autoreels.core import state
    (tmp_path / "manifests").mkdir()
    (tmp_path / "reviews").mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    sha = "d" * 64
    mp3 = cache / f"{sha}.mp3"
    mp3.write_bytes(b"AUDIO")
    ah = state.audio_hash(mp3)
    words = []
    for group_offset in (40.0, 80.0, 120.0, 160.0):
        for i in range(25):
            words.append({"word": f"слово{i}.", "t0": group_offset + i * 1.0,
                          "t1": group_offset + i * 1.0 + 0.5})
    tpath = cache / f"{ah}.{KEY}.transcript.json"
    tpath.write_text(
        json.dumps({"language": "ru", "words": words, "source_sha256": sha, **_META}),
        encoding="utf-8",
    )
    m = Manifest(
        source="vc.mp4", source_sha256=sha, source_hash_scheme="partial-p1",
        source_path="/originals/vc.mp4",
        duration_preset="shorts",
        setup=SetupProfile(setup_id="t", crop=Crop(x=0, y=0, w=960, h=1700),
                           scale=[1080, 1920], frame=[1920, 1080]),
        run_key="rk3", transcript_params_key=KEY,
        source_kind="lecture", reels=[],
    )
    mpath = tmp_path / "manifests" / "vc.json"
    mpath.write_text(m.model_dump_json(), encoding="utf-8")
    return tmp_path, cache, mpath, tpath


def test_chained_splice_warning(tmp_path, capsys):
    """Two scored lines both with '+' chain into one group; warn about ignored fields."""
    root, cache, mpath, _ = _setup_chained(tmp_path)
    # Rename manifest to a unique stem so output files get a known unique name
    unique_mpath = tmp_path / "manifests" / "vc__chained__.json"
    unique_mpath.write_text(mpath.read_text(encoding="utf-8"), encoding="utf-8")
    out_review = REPO_ROOT / "reviews" / "vc__chained__.review.json"
    out_dataset = REPO_ROOT / "data" / "blocks_dataset" / "vc__chained__.jsonl"
    out_review.unlink(missing_ok=True)
    out_dataset.unlink(missing_ok=True)
    try:
        # Score blocks 1 and 2 both with '+': 1+2+3 form one group; line 2's fields ignored
        review = "1 85+\n2 80+\n"
        rpath = tmp_path / "reviews" / "chained.review.md"
        rpath.write_text(review, encoding="utf-8")

        rc = cli._blocks_do_apply(
            str(rpath), root=REPO_ROOT, cache_dir=str(cache),
            source=str(unique_mpath),
        )
        err = capsys.readouterr().err
        assert "lines 1 and 2 merged into one clip 1+2+3" in err, (
            f"chained splice warning not emitted; stderr={err!r}"
        )
        assert "fields of line 2 ignored" in err
    finally:
        out_review.unlink(missing_ok=True)
        out_dataset.unlink(missing_ok=True)
