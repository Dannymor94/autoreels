"""Test 5: block-set sidecar written by cmd_blocks and round-trips correctly.

The sidecar (<manifest>.blocks.json) is written whenever cmd_blocks is called with a manifest,
regardless of --scored or --review flags.
"""
import json
from pathlib import Path

import pytest

from autoreels import __main__ as cli
from autoreels.cloud.transcribe import params_key
from autoreels.core import state
from autoreels.core.models import Crop, Manifest, Reel, SetupProfile

REPO_ROOT = Path(__file__).resolve().parents[1]

_META = {"provider": "groq", "model": "whisper-large-v3", "prompt_hash": "ph1"}
KEY = params_key(_META)

# Minimal transcript: two blocks separated by a >1.5s pause
_WORDS = [
    {"word": "Первое", "t0": 0.0, "t1": 0.5},
    {"word": "предложение.", "t0": 0.6, "t1": 1.0},
    # pause ~2.5s → new block
    {"word": "Второе", "t0": 3.5, "t1": 4.0},
    {"word": "предложение.", "t0": 4.1, "t1": 4.5},
    # another pause
    {"word": "Третье", "t0": 6.5, "t1": 7.0},
    {"word": "предложение.", "t0": 7.1, "t1": 7.5},
    # ... continuing to build up duration to pass min_sec (18s), so add more words
]

# Expand each "block" to ~20s so they pass the 18s min_meaningful filter
_LONG_WORDS: list[dict] = []
for block_offset in (0.0, 25.0, 50.0):
    for i in range(20):
        _LONG_WORDS.append({
            "word": f"слово{i}.",
            "t0": block_offset + i * 0.9,
            "t1": block_offset + i * 0.9 + 0.5,
        })
    # pause to next block (>1.5s gap is guaranteed by block_offset jump of 25s)


def _setup(tmp_path):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    sha = "c" * 64
    audio = cache / f"{sha}.mp3"
    audio.write_bytes(b"MP3")
    ah = state.audio_hash(audio)
    (cache / f"{ah}.{KEY}.transcript.json").write_text(
        json.dumps({"language": "ru", "words": _LONG_WORDS, **_META}), encoding="utf-8"
    )
    m = Manifest(
        source="v.mp4", source_sha256=sha, source_hash_scheme="partial-p1",
        duration_preset="shorts",
        setup=SetupProfile(setup_id="t", crop=Crop(x=0, y=0, w=960, h=1700),
                           scale=[1080, 1920], frame=[1920, 1080]),
        run_key="rk", transcript_params_key=KEY, reels=[],
    )
    mpath = manifests / "v.json"
    mpath.write_text(m.model_dump_json(), encoding="utf-8")
    return manifests, cache, mpath


def test_blocks_sidecar_written_and_roundtrips(tmp_path):
    """cmd_blocks writes .blocks.json sidecar; fields id/start/end/boundary_reason/verdict/score."""
    manifests, cache, mpath = _setup(tmp_path)

    rc = cli.cmd_blocks(str(mpath), root=REPO_ROOT, cache_dir=str(cache))
    assert rc == 0

    sidecar = mpath.with_suffix(".blocks.json")
    assert sidecar.exists(), ".blocks.json sidecar must be created by cmd_blocks"

    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) > 0

    for entry in data:
        assert "id" in entry
        assert "start" in entry and "end" in entry
        assert "boundary_reason" in entry
        assert "verdict" in entry          # "KEPT" or a drop-reason string
        assert "heuristic_score" in entry  # float, pre-computed

    # All verdicts are either "KEPT" or a non-empty reason string
    verdicts = {e["verdict"] for e in data}
    assert all(isinstance(v, str) and v for v in verdicts)

    # Sidecar does NOT contain block text (kept small; recoverable from transcript by timecode)
    for entry in data:
        assert "text" not in entry


def test_blocks_sidecar_excluded_from_manifest_glob(tmp_path):
    """The .blocks.json sidecar is excluded from _glob_manifests so resnap/batch don't pick it up."""
    d = tmp_path / "manifests"
    d.mkdir()
    real = d / "video.json"
    real.write_text("{}", encoding="utf-8")
    sidecar = d / "video.blocks.json"
    sidecar.write_text("[]", encoding="utf-8")

    found = cli._glob_manifests(d)
    names = [p.name for p in found]
    assert "video.json" in names
    assert "video.blocks.json" not in names
