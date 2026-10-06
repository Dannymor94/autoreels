#!/usr/bin/env python3
"""Create a ready-to-post publish bundle for all clips under a stem.

For each clip (non-error) found in the gate folder (or top-level reel folder):
  reels-out/<stem>/_publish/<id>/
    video.mp4    → symlink to clip
    caption.txt  → line 1: title; blank line; description
    covers/      → symlinks to the three cover candidates
    info.json    → duration, first/last spoken words, source times, render fingerprint

Usage:
    python scripts/make_publish_bundle.py <stem>
    python scripts/make_publish_bundle.py <stem> --gate <gate_name>
    python scripts/make_publish_bundle.py IMG_6848 --gate g1
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


# ── project root helper ────────────────────────────────────────────────────────


def _project_root(start: Path) -> Path:
    p = start.resolve()
    for _ in range(12):
        if (p / "manifests").is_dir():
            return p
        p = p.parent
    raise FileNotFoundError(f"manifests/ not found above {start}")


# ── readers ────────────────────────────────────────────────────────────────────


def read_manifest(project_root: Path, stem: str) -> dict:
    mpath = project_root / "manifests" / f"{stem}.json"
    if mpath.exists():
        return json.loads(mpath.read_text(encoding="utf-8"))
    return {}


def _read_render_json(clip: Path) -> dict:
    p = clip.parent / f"{clip.stem}.render.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _probe_duration(clip: Path) -> float | None:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(clip)],
        capture_output=True,
        text=True,
    )
    try:
        for s in json.loads(r.stdout).get("streams", []):
            if s.get("codec_type") == "video":
                return float(s.get("duration", 0))
    except Exception:
        pass
    return None


# ── clip discovery ─────────────────────────────────────────────────────────────


def find_clips(clip_dir: Path) -> tuple[list[Path], list[str]]:
    """Return (good_clips, skipped_ids) from clip_dir.

    Skips anything with a matching <id>.ERROR.mp4 sidecar.
    """
    all_mp4 = sorted(p for p in clip_dir.glob("*.mp4") if not p.stem.endswith(".ERROR"))
    # Filter out .ERROR.mp4 files themselves (they have stem like "r01.ERROR")
    # and skip any id that has a <id>.ERROR.mp4 present
    error_ids = {p.stem.replace(".ERROR", "") for p in clip_dir.glob("*.ERROR.mp4")}
    # More precisely: "r01.ERROR.mp4" has stem "r01.ERROR"; check for files ending in .ERROR.mp4
    error_ids_v2 = set()
    for p in clip_dir.iterdir():
        if p.name.endswith(".ERROR.mp4"):
            error_ids_v2.add(p.name[: -len(".ERROR.mp4")])

    good = [p for p in all_mp4 if p.stem not in error_ids_v2]
    skipped = sorted(error_ids_v2)
    return good, skipped


# ── covers discovery ───────────────────────────────────────────────────────────


def find_covers(project_root: Path, stem: str, gate_label: str, reel_id: str) -> list[Path]:
    """Return sorted list of cover PNGs for this reel (may be empty if not yet generated)."""
    covers_dir = project_root / "reels-out" / stem / "_covers" / gate_label
    return sorted(covers_dir.glob(f"{reel_id}_cover_*.png"))


# ── bundle writer ──────────────────────────────────────────────────────────────


def build_caption(reel: dict) -> str:
    """line 1: title; blank line; description."""
    title = reel.get("title_overlay") or reel.get("title") or ""
    desc = reel.get("description") or ""
    return f"{title}\n\n{desc}\n"


def build_info(reel: dict, render_json: dict, duration: float | None) -> dict:
    words = reel.get("subtitles", [])
    first_word = words[0]["word"] if words else ""
    last_word = words[-1]["word"] if words else ""
    return {
        "reel_id": reel.get("id"),
        "duration_sec": duration,
        "first_spoken_word": first_word,
        "last_spoken_word": last_word,
        "source_start": render_json.get("source_start"),
        "source_end": render_json.get("source_end"),
        "synthetic_tail_sec": render_json.get("synthetic_tail_sec"),
        "render_fingerprint": render_json,
    }


def make_bundle(
    clip: Path,
    reel: dict,
    covers: list[Path],
    bundle_dir: Path,
) -> None:
    """Create the bundle directory for one clip."""
    bundle_dir.mkdir(parents=True, exist_ok=True)

    # video.mp4 — symlink
    video_link = bundle_dir / "video.mp4"
    if video_link.exists() or video_link.is_symlink():
        video_link.unlink()
    os.symlink(clip.resolve(), video_link)

    # caption.txt
    (bundle_dir / "caption.txt").write_text(build_caption(reel), encoding="utf-8")

    # covers/ — symlinks
    covers_dir = bundle_dir / "covers"
    covers_dir.mkdir(exist_ok=True)
    for cover in covers:
        link = covers_dir / cover.name
        if link.exists() or link.is_symlink():
            link.unlink()
        os.symlink(cover.resolve(), link)

    # info.json
    render_json = _read_render_json(clip)
    duration = _probe_duration(clip)
    info = build_info(reel, render_json, duration)
    (bundle_dir / "info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── main ───────────────────────────────────────────────────────────────────────


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Create publish bundle for reel clips.")
    ap.add_argument("stem", help="Video stem, e.g. IMG_6848")
    ap.add_argument("--gate", default=None, help="Gate name (use clips from _gate/<name>/); omit for final clips")
    args = ap.parse_args(argv)

    stem: str = args.stem
    gate: str | None = args.gate

    try:
        root = _project_root(Path("."))
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    reels_out = root / "reels-out"
    if gate:
        clip_dir = reels_out / stem / "_gate" / gate
        gate_label = gate
    else:
        clip_dir = reels_out / stem
        gate_label = "final"

    if not clip_dir.exists():
        print(f"ERROR: clip directory not found: {clip_dir}", file=sys.stderr)
        return 1

    manifest = read_manifest(root, stem)
    reels_by_id = {r["id"]: r for r in manifest.get("reels", [])}

    clips, skipped = find_clips(clip_dir)

    if skipped:
        print(f"Skipped (ERROR clips): {', '.join(skipped)}")

    if not clips:
        print("No clips to bundle.", file=sys.stderr)
        return 0

    publish_root = reels_out / stem / "_publish"
    ok = 0
    for clip in clips:
        reel_id = clip.stem
        reel = reels_by_id.get(reel_id)
        if reel is None:
            print(f"  WARNING: {reel_id} not in manifest — skipping")
            continue
        covers = find_covers(root, stem, gate_label, reel_id)
        bundle_dir = publish_root / reel_id
        make_bundle(clip, reel, covers, bundle_dir)
        print(f"  bundled: {bundle_dir.relative_to(root)}"
              f"  ({len(covers)} cover(s))")
        ok += 1

    print(f"Done: {ok}/{len(clips)} clips bundled → {publish_root.relative_to(root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
