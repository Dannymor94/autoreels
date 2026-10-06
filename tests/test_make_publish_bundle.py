"""Tests for scripts/make_publish_bundle.py — fixture-based, no ffmpeg."""

import json
import os
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import make_publish_bundle


# ── fixtures ───────────────────────────────────────────────────────────────────


def _make_tree(root: Path, stem: str = "VID_01", gate: str = "g1") -> dict:
    """Create a minimal project tree in root and return paths."""
    manifests = root / "manifests"
    manifests.mkdir()
    clip_dir = root / "reels-out" / stem / "_gate" / gate
    clip_dir.mkdir(parents=True)

    reel = {
        "id": "r01",
        "start": 10.0,
        "end": 30.0,
        "segments": [],
        "speed": 1.0,
        "title": "Тест заголовок",
        "title_overlay": "Тест заголовок",
        "description": "Описание клипа #тест #рилс",
        "hook": "",
        "score": 80,
        "subtitles": [
            {"word": "Привет", "t0": 10.1, "t1": 10.5, "emph": False},
            {"word": "мир", "t0": 10.6, "t1": 11.0, "emph": False},
        ],
    }
    manifest = {"reels": [reel]}
    (manifests / f"{stem}.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Create fake clip file
    clip = clip_dir / "r01.mp4"
    clip.write_bytes(b"FAKE")

    # Render sidecar
    (clip_dir / "r01.render.json").write_text(
        json.dumps({"source_start": 10.0, "source_end": 30.0, "synthetic_tail_sec": 1.0}),
        encoding="utf-8",
    )

    return {"root": root, "stem": stem, "gate": gate, "clip": clip, "reel": reel}


# ── find_clips ─────────────────────────────────────────────────────────────────


def test_find_clips_excludes_error(tmp_path):
    d = tmp_path
    (d / "r01.mp4").write_bytes(b"ok")
    (d / "r02.mp4").write_bytes(b"ok")
    (d / "r02.ERROR.mp4").write_bytes(b"err")

    good, skipped = make_publish_bundle.find_clips(d)
    good_names = [p.name for p in good]
    assert "r01.mp4" in good_names
    assert "r02.mp4" not in good_names
    assert "r02" in skipped


def test_find_clips_empty_dir(tmp_path):
    good, skipped = make_publish_bundle.find_clips(tmp_path)
    assert good == []
    assert skipped == []


# ── build_caption ──────────────────────────────────────────────────────────────


def test_caption_format():
    reel = {
        "title_overlay": "Мой заголовок",
        "description": "Описание #хэштег",
    }
    caption = make_publish_bundle.build_caption(reel)
    lines = caption.splitlines()
    assert lines[0] == "Мой заголовок"
    assert lines[1] == ""
    assert "Описание" in caption
    assert "#хэштег" in caption


def test_caption_falls_back_to_title():
    reel = {"title": "Заголовок из поля title", "title_overlay": "", "description": ""}
    caption = make_publish_bundle.build_caption(reel)
    assert caption.startswith("Заголовок из поля title")


def test_caption_empty_reel():
    caption = make_publish_bundle.build_caption({})
    # Should not raise; first line may be blank
    assert isinstance(caption, str)


# ── build_info ─────────────────────────────────────────────────────────────────


def test_build_info_fields():
    reel = {
        "id": "r01",
        "subtitles": [
            {"word": "Первое", "t0": 1.0, "t1": 1.5},
            {"word": "последнее", "t0": 5.0, "t1": 5.5},
        ],
    }
    render_json = {"source_start": 10.0, "source_end": 30.0, "synthetic_tail_sec": 1.0}
    info = make_publish_bundle.build_info(reel, render_json, duration=20.5)
    assert info["reel_id"] == "r01"
    assert info["duration_sec"] == 20.5
    assert info["first_spoken_word"] == "Первое"
    assert info["last_spoken_word"] == "последнее"
    assert info["source_start"] == 10.0
    assert info["source_end"] == 30.0


# ── make_bundle integration ────────────────────────────────────────────────────


def test_make_bundle_creates_expected_files(tmp_path):
    ctx = _make_tree(tmp_path)
    covers_dir = tmp_path / "reels-out" / ctx["stem"] / "_covers" / ctx["gate"]
    covers_dir.mkdir(parents=True)
    cover = covers_dir / "r01_cover_1.png"
    cover.write_bytes(b"PNG")

    bundle_dir = tmp_path / "bundle" / "r01"
    make_publish_bundle.make_bundle(ctx["clip"], ctx["reel"], [cover], bundle_dir)

    assert (bundle_dir / "video.mp4").is_symlink()
    assert (bundle_dir / "caption.txt").exists()
    assert (bundle_dir / "info.json").exists()
    assert (bundle_dir / "covers" / "r01_cover_1.png").is_symlink()


def test_make_bundle_caption_content(tmp_path):
    ctx = _make_tree(tmp_path)
    bundle_dir = tmp_path / "bundle" / "r01"
    make_publish_bundle.make_bundle(ctx["clip"], ctx["reel"], [], bundle_dir)

    caption = (bundle_dir / "caption.txt").read_text(encoding="utf-8")
    assert caption.startswith("Тест заголовок")
    assert "Описание клипа" in caption


def test_make_bundle_video_symlink_target(tmp_path):
    ctx = _make_tree(tmp_path)
    bundle_dir = tmp_path / "bundle" / "r01"
    make_publish_bundle.make_bundle(ctx["clip"], ctx["reel"], [], bundle_dir)

    link = bundle_dir / "video.mp4"
    assert link.is_symlink()
    assert os.readlink(link) == str(ctx["clip"].resolve())


def test_make_bundle_idempotent(tmp_path):
    ctx = _make_tree(tmp_path)
    bundle_dir = tmp_path / "bundle" / "r01"
    # Run twice; second run should not raise on existing symlinks
    make_publish_bundle.make_bundle(ctx["clip"], ctx["reel"], [], bundle_dir)
    make_publish_bundle.make_bundle(ctx["clip"], ctx["reel"], [], bundle_dir)
    assert (bundle_dir / "video.mp4").is_symlink()


# ── find_covers ────────────────────────────────────────────────────────────────


def test_find_covers_returns_sorted(tmp_path):
    ctx = _make_tree(tmp_path)
    covers_dir = tmp_path / "reels-out" / ctx["stem"] / "_covers" / ctx["gate"]
    covers_dir.mkdir(parents=True)
    for n in [3, 1, 2]:
        (covers_dir / f"r01_cover_{n}.png").write_bytes(b"PNG")

    covers = make_publish_bundle.find_covers(tmp_path, ctx["stem"], ctx["gate"], "r01")
    names = [p.name for p in covers]
    assert names == sorted(names)
    assert len(names) == 3


def test_find_covers_missing_dir(tmp_path):
    (tmp_path / "manifests").mkdir()
    covers = make_publish_bundle.find_covers(tmp_path, "VID_01", "g1", "r01")
    assert covers == []
