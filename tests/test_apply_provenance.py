"""Tests for --apply provenance fix and backfill-params-key command.

1. --apply stamps transcript_params_key from the actual transcript used (not from
   the source manifest, which may be empty for legacy manifests).
2. After backfill, arl blocks and resnap can resolve the transcript.
3. backfill refuses a transcript whose identity does not match.
"""
import json
from pathlib import Path

import pytest

from autoreels import __main__ as cli
from autoreels.cloud.transcribe import params_key, transcript_identity
from autoreels.core import state
from autoreels.core.models import Crop, Manifest, Reel, SetupProfile, Transcript, Word

REPO_ROOT = Path(__file__).resolve().parents[1]

_META = {"provider": "groq", "model": "whisper-large-v3", "prompt_hash": "ph1"}
KEY = params_key(_META)

# Words that span ~70s in three pause-separated groups so candidate_blocks produces blocks >= 18s
_WORDS = []
for group_offset in (0.0, 25.0, 50.0):
    for i in range(18):
        _WORDS.append({
            "word": f"слово{i}.",
            "t0": group_offset + i * 1.0,
            "t1": group_offset + i * 1.0 + 0.5,
        })


def _setup(tmp_path, *, manifest_key: str = ""):
    """Lay out cache + manifest. Returns (root, manifests_dir, cache_dir, manifest_path)."""
    (tmp_path / "manifests").mkdir()
    (tmp_path / "reviews").mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    sha = "a" * 64
    audio = cache / f"{sha}.mp3"
    audio.write_bytes(b"MP3")
    ah = state.audio_hash(audio)
    # Write a stamped transcript keyed by KEY
    transcript_file = cache / f"{ah}.{KEY}.transcript.json"
    transcript_file.write_text(
        json.dumps({"language": "ru", "words": _WORDS, **_META}), encoding="utf-8"
    )
    m = Manifest(
        source="v.mp4", source_sha256=sha, source_hash_scheme="partial-p1",
        source_path="/originals/v.mp4",
        duration_preset="shorts",
        setup=SetupProfile(setup_id="t", crop=Crop(x=0, y=0, w=960, h=1700),
                           scale=[1080, 1920], frame=[1920, 1080]),
        run_key="rk", transcript_params_key=manifest_key,
        source_kind="lecture", reels=[],
    )
    mpath = tmp_path / "manifests" / "v.json"
    mpath.write_text(m.model_dump_json(), encoding="utf-8")
    return tmp_path, tmp_path / "manifests", cache, mpath, transcript_file


# ---------------------------------------------------------------------------
# Test 1: --apply stamps transcript_params_key from transcript (not source manifest)
# ---------------------------------------------------------------------------

def test_apply_stamps_transcript_params_key(tmp_path):
    """--apply output manifest carries transcript_params_key from the transcript it used.

    The source manifest has transcript_params_key="" (legacy). The fix is that the output
    must stamp the actual transcript identity, not blindly copy the empty key.
    """
    root, manifests, cache, mpath, _ = _setup(tmp_path, manifest_key="")
    out_path = REPO_ROOT / "reviews" / "v__test_apply__.review.json"
    out_path.unlink(missing_ok=True)
    try:
        # Rename the manifest stem so output goes to a test-specific file
        test_mpath = tmp_path / "manifests" / "v__test_apply__.json"
        test_mpath.write_text(mpath.read_text(), encoding="utf-8")
        review_content = (
            "# AutoReels block review\n"
            f"# source: {test_mpath}\n"
            "# blocks: 3  |  filter_removed: 0\n"
            "# format: compact\n"
            "#\n"
            "1: 80\n"
        )
        review_path = root / "reviews" / "v__test_apply__.review.md"
        review_path.write_text(review_content, encoding="utf-8")

        rc = cli._blocks_do_apply(str(review_path), root=REPO_ROOT, cache_dir=str(cache))
        assert rc == 0

        assert out_path.exists(), "apply must write a review manifest"
        result = Manifest.model_validate_json(out_path.read_text(encoding="utf-8"))

        assert result.transcript_params_key == KEY, (
            f"--apply must stamp transcript identity ({KEY!r}), got {result.transcript_params_key!r}"
        )
        assert result.selection_source == "human"
        assert result.source_path == "/originals/v.mp4"
    finally:
        out_path.unlink(missing_ok=True)
        (REPO_ROOT / "reviews" / "v__test_apply__._low_speech_density.json").unlink(missing_ok=True)


def test_apply_preserves_key_when_source_has_one(tmp_path):
    """When source manifest already has the right key, --apply keeps it (same transcript used)."""
    root, manifests, cache, mpath, _ = _setup(tmp_path, manifest_key=KEY)
    out_path = REPO_ROOT / "reviews" / "v__test_apply2__.review.json"
    out_path.unlink(missing_ok=True)
    try:
        test_mpath = tmp_path / "manifests" / "v__test_apply2__.json"
        test_mpath.write_text(mpath.read_text(), encoding="utf-8")
        review_content = (
            "# AutoReels block review\n"
            f"# source: {test_mpath}\n"
            "# blocks: 3  |  filter_removed: 0\n"
            "# format: compact\n"
            "#\n"
            "1: 80\n"
        )
        review_path = root / "reviews" / "v__test_apply2__.review.md"
        review_path.write_text(review_content, encoding="utf-8")

        rc = cli._blocks_do_apply(str(review_path), root=REPO_ROOT, cache_dir=str(cache))
        assert rc == 0

        result = Manifest.model_validate_json(out_path.read_text(encoding="utf-8"))
        assert result.transcript_params_key == KEY
    finally:
        out_path.unlink(missing_ok=True)
        (REPO_ROOT / "reviews" / "v__test_apply2__._low_speech_density.json").unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Test 2: after backfill, arl blocks resolves the transcript correctly
# ---------------------------------------------------------------------------

def test_backfill_enables_blocks(tmp_path):
    """After backfill-params-key, cmd_blocks no longer falls back with a warning."""
    root, manifests, cache, mpath, transcript_file = _setup(tmp_path, manifest_key="")
    assert Manifest.model_validate_json(mpath.read_text()).transcript_params_key == ""

    rc = cli.cmd_backfill_pkey(str(mpath), str(transcript_file), root=root, cache_dir=str(cache))
    assert rc == 0

    updated = Manifest.model_validate_json(mpath.read_text())
    assert updated.transcript_params_key == KEY

    # Now cmd_blocks should resolve the transcript without fallback warning
    import io, sys
    captured = io.StringIO()
    old_stderr = sys.stderr
    sys.stderr = captured
    try:
        rc2 = cli.cmd_blocks(str(mpath), root=REPO_ROOT, cache_dir=str(cache))
    finally:
        sys.stderr = old_stderr
    assert rc2 == 0
    err = captured.getvalue()
    assert "backfill-params-key" not in err, (
        f"should not suggest backfill after it was already done; stderr={err!r}"
    )


# ---------------------------------------------------------------------------
# Test 3: backfill refuses a transcript whose identity does not match
# ---------------------------------------------------------------------------

def test_backfill_refuses_mismatched_transcript(tmp_path, capsys):
    """backfill-params-key refuses a transcript file whose audio_hash doesn't match."""
    root, manifests, cache, mpath, _ = _setup(tmp_path, manifest_key="")

    # Create a transcript for a DIFFERENT audio (different sha → different audio hash prefix)
    wrong_sha = "b" * 64
    wrong_audio = cache / f"{wrong_sha}.mp3"
    wrong_audio.write_bytes(b"DIFFERENTMP3")
    wrong_ah = state.audio_hash(wrong_audio)
    wrong_pkey = KEY  # same params_key doesn't help if audio hash is wrong
    wrong_transcript = cache / f"{wrong_ah}.{wrong_pkey}.transcript.json"
    wrong_transcript.write_text(
        json.dumps({"language": "ru", "words": _WORDS, **_META}), encoding="utf-8"
    )

    rc = cli.cmd_backfill_pkey(str(mpath), str(wrong_transcript), root=root, cache_dir=str(cache))
    assert rc != 0, "must refuse a transcript from a different audio"

    err = capsys.readouterr().err
    assert "ОТКАЗАН" in err or "не совпадает" in err

    # Manifest must NOT have been modified
    unchanged = Manifest.model_validate_json(mpath.read_text())
    assert unchanged.transcript_params_key == ""


def test_backfill_refuses_orphan_transcript(tmp_path, capsys):
    """backfill-params-key refuses an orphan transcript (no stamped model metadata)."""
    root, manifests, cache, mpath, _ = _setup(tmp_path, manifest_key="")

    # Write an orphan transcript (no model/provider/prompt_hash)
    sha = "a" * 64
    audio = cache / f"{sha}.mp3"
    ah = state.audio_hash(audio)
    orphan = cache / f"{ah}.transcript.json"  # no pkey in name
    orphan.write_text(json.dumps({"language": "ru", "words": _WORDS}), encoding="utf-8")

    rc = cli.cmd_backfill_pkey(str(mpath), str(orphan), root=root, cache_dir=str(cache))
    assert rc != 0

    err = capsys.readouterr().err
    assert "orphan" in err.lower() or "stamped" in err.lower() or "штамп" in err.lower()


def test_backfill_refuses_already_set_without_force(tmp_path, capsys):
    """backfill-params-key refuses overwrite without --force."""
    root, manifests, cache, mpath, transcript_file = _setup(tmp_path, manifest_key=KEY)

    rc = cli.cmd_backfill_pkey(str(mpath), str(transcript_file), root=root, cache_dir=str(cache))
    assert rc != 0

    err = capsys.readouterr().err
    assert "force" in err.lower() or "--force" in err


# ---------------------------------------------------------------------------
# backfill-source-sha: stamps source_sha256 on legacy transcripts
# ---------------------------------------------------------------------------

def test_backfill_source_sha_stamps_existing_transcript(tmp_path, capsys):
    """backfill-source-sha scans mp3 content hash and stamps source_sha256."""
    root, manifests, cache, mpath, transcript_file = _setup(tmp_path, manifest_key=KEY)

    # Simulate a legacy transcript by writing one without source_sha256
    sha = "a" * 64
    mp3 = cache / f"{sha}.mp3"
    ah = state.audio_hash(mp3)
    legacy = cache / f"{ah}.{KEY}.legacy.transcript.json"
    legacy.write_text(
        json.dumps({"language": "ru", "words": _WORDS, **_META}), encoding="utf-8"
    )
    from autoreels.core.models import Transcript as _Tx
    assert _Tx.model_validate_json(legacy.read_text()).source_sha256 == ""

    from autoreels.__main__ import cmd_backfill_source_sha
    rc = cmd_backfill_source_sha([str(legacy)], cache_dir=str(cache))
    assert rc == 0

    updated = _Tx.model_validate_json(legacy.read_text())
    assert updated.source_sha256 == sha


def test_backfill_source_sha_refuses_reextracted_mp3(tmp_path, capsys):
    """backfill-source-sha refuses when mp3 was re-extracted (content hash mismatch)."""
    root, manifests, cache, mpath, transcript_file = _setup(tmp_path, manifest_key=KEY)

    sha = "a" * 64
    mp3 = cache / f"{sha}.mp3"
    ah = state.audio_hash(mp3)
    legacy = cache / f"{ah}.{KEY}.legacy2.transcript.json"
    legacy.write_text(
        json.dumps({"language": "ru", "words": _WORDS, **_META}), encoding="utf-8"
    )
    # Re-extract: overwrite mp3 with different content (content hash changes)
    mp3.write_bytes(b"REEXTRACTED_AUDIO")

    from autoreels.__main__ import cmd_backfill_source_sha
    rc = cmd_backfill_source_sha([str(legacy)], cache_dir=str(cache))
    assert rc != 0
    err = capsys.readouterr().err
    assert "re-extracted" in err.lower() or "re-run" in err.lower() or "не совпадает" in err.lower() or "mismatch" in err.lower() or "content hash" in err.lower()
