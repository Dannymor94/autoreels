#!/usr/bin/env python3
"""Verify rendered gate clips against golden expectations.

Usage:
    python scripts/verify_gate.py benchmarks/golden/montage.yaml

Exit code: 1 if any clip FAILs, 0 if all PASS.
"""
import json
import subprocess
import sys
from pathlib import Path

import yaml

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "tools"))
import flash_check  # noqa: E402

TWO_SHOT_MIN_SEC = 2.5
TWO_SHOT_MIN_MIDDLE_SEC = 4.0


# ── ffmpeg helpers ─────────────────────────────────────────────────────────────

def _run(cmd: list) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _probe_duration(path: Path) -> float | None:
    r = _run(["ffprobe", "-v", "quiet", "-print_format", "json",
               "-show_streams", str(path)])
    try:
        for s in json.loads(r.stdout).get("streams", []):
            if s.get("codec_type") == "video":
                return float(s["duration"])
    except (json.JSONDecodeError, KeyError, ValueError):
        pass
    return None


def _volumedetect_mean(path: Path, duration: float = 1.0) -> float | None:
    """Return mean_volume dB for first `duration` seconds. None on failure."""
    r = _run(["ffmpeg", "-i", str(path), "-t", str(duration),
              "-af", "volumedetect", "-f", "null", "-"])
    for line in r.stderr.splitlines():
        if "mean_volume" in line:
            try:
                return float(line.split(":")[1].strip().replace(" dB", ""))
            except ValueError:
                pass
    return None


def _framemd5s(path: Path, ss: float, duration: float) -> list[str]:
    """Return per-frame md5 strings for [ss, ss+duration]."""
    r = _run(["ffmpeg", "-ss", f"{ss:.3f}", "-i", str(path),
              "-t", f"{duration:.3f}", "-f", "framemd5", "-an", "-"])
    out = []
    for line in r.stdout.splitlines():
        if line.startswith("#") or "," not in line:
            continue
        out.append(line.split(",")[-1].strip())
    return out


# ── per-clip checks ────────────────────────────────────────────────────────────

def _check_words(clip_dir: Path, clip_id: str, expected: dict) -> list[str]:
    txt = clip_dir / f"{clip_id}.transcript.txt"
    if not txt.exists():
        return ["transcript_txt_missing"]
    words = txt.read_text(encoding="utf-8").split()
    first4 = " ".join(words[:4])
    last4 = " ".join(words[-4:])
    fails = []
    if first4 != expected["first_words"]:
        fails.append(f"first_words:got='{first4}'")
    if last4 != expected["last_words"]:
        fails.append(f"last_words:got='{last4}'")
    return fails


def _check_audio_start(mp4: Path) -> list[str]:
    mean = _volumedetect_mean(mp4, 1.0)
    if mean is None:
        return ["volumedetect_failed"]
    if mean <= -45.0:
        return [f"no_audio_start:{mean:.1f}dB"]
    return []


def _check_tail_silence(speechmap_path: Path, reel_end: float) -> list[str]:
    if not speechmap_path.exists():
        return [f"speechmap_missing:{speechmap_path.name}"]
    with open(speechmap_path) as f:
        sm = json.load(f)
    t_start = reel_end - 0.5
    for ivl in sm.get("intervals", []):
        s, e = ivl[0], ivl[1]
        if s < reel_end and e > t_start:
            return [f"speech_in_tail:[{s:.2f},{e:.2f}]"]
    return []


def _check_tail_frames(mp4: Path, clip_duration: float) -> list[str]:
    """Verify tail integrity via framemd5.

    Identical frames → synthetic tail (expected, pass).
    Mixed frames → natural motion (expected, pass).
    Single hash repeated >80% but not 100% → suspect freeze artifact → fail.
    """
    window = 0.5
    hashes = _framemd5s(mp4, max(0.0, clip_duration - window), window)
    if len(hashes) < 3:
        return []  # too short to judge
    unique = set(hashes)
    if len(unique) <= 1:
        return []  # fully frozen synthetic tail — ok
    if len(unique) == 2:
        dominant = max(hashes.count(h) for h in unique)
        if dominant / len(hashes) > 0.80:
            return ["tail_frames_suspect_freeze"]
    return []


def _check_shots(mp4: Path, manifest_path: Path, reel_id: str,
                 src_dir: Path) -> list[str]:
    """Check two-shot spans via flash_check.check_reel. Skips if source not found."""
    if not manifest_path.exists():
        return []  # no manifest in this environment — skip
    try:
        manifest = json.load(open(manifest_path))
    except json.JSONDecodeError as exc:
        return [f"manifest_corrupt:{exc}"]

    setup = manifest.get("setup", {})
    stem = setup.get("setup_id", "")
    src = next(
        (src_dir / f"{stem}{ext}"
         for ext in (".mp4", ".MP4", ".mov")
         if (src_dir / f"{stem}{ext}").exists()),
        None,
    )
    if src is None:
        return []  # no source video in this environment — skip

    reel = next((r for r in manifest.get("reels", []) if r["id"] == reel_id), None)
    if reel is None:
        return [f"reel_{reel_id}_not_in_manifest"]

    wide_vf = flash_check._wide_vf(setup)
    close_vf = flash_check._close_vf(setup)
    labels, flashes = flash_check.check_reel(reel, mp4, src, wide_vf, close_vf)

    fails = []
    if flashes:
        fails.append(f"shot_flash:{len(flashes)}")

    # Check span floors using run list
    runs = flash_check._runs([l for l in labels if l != "ambig"])
    fps = flash_check.FPS
    for i, (lbl, s, e) in enumerate(runs):
        dur = (e - s + 1) / fps
        if dur < TWO_SHOT_MIN_SEC:
            # Jump seam must be >= 1.0s to be a forced cut, not a flash
            fails.append(f"short_span:{lbl}_{dur:.2f}s<{TWO_SHOT_MIN_SEC}s")
        # A-B-A middle check
        if i > 0 and i < len(runs) - 1:
            prev_lbl = runs[i - 1][0]
            nxt_lbl = runs[i + 1][0]
            if prev_lbl == nxt_lbl and lbl != prev_lbl and dur < TWO_SHOT_MIN_MIDDLE_SEC:
                fails.append(f"aba_middle_short:{lbl}_{dur:.2f}s<{TWO_SHOT_MIN_MIDDLE_SEC}s")
    return fails


# ── main ───────────────────────────────────────────────────────────────────────

def check_clip(entry: dict, project: Path) -> list[str]:
    clip_id = entry["clip_id"]
    stem = entry["stem"]
    clip_path = project / entry["path"]
    clip_dir = clip_path.parent
    reel_end = float(entry["reel_end"])
    speechmap = project / "transcripts" / f"{stem}.speechmap.json"
    manifest_path = project / "manifests" / f"{stem}.json"
    src_dir = project / "inputs-archive"

    if not clip_path.exists():
        return ["clip_missing"]

    fails = []

    if (clip_dir / f"{clip_id}.ERROR.mp4").exists():
        fails.append("error_mp4_present")

    fails.extend(_check_words(clip_dir, clip_id, entry))
    fails.extend(_check_audio_start(clip_path))
    fails.extend(_check_tail_silence(speechmap, reel_end))

    duration = _probe_duration(clip_path)
    if duration is not None:
        fails.extend(_check_tail_frames(clip_path, duration))

    fails.extend(_check_shots(clip_path, manifest_path, clip_id, src_dir))

    return fails


def main(yaml_path: str, project: Path = PROJECT) -> int:
    data = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8"))
    clips = data["clips"]

    rows = []
    for entry in clips:
        label = f"{entry['stem']}/{entry['clip_id']}"
        fails = check_clip(entry, project)
        status = "PASS" if not fails else "FAIL"
        rows.append((label, status, fails))

    # Print table
    col = max(len(r[0]) for r in rows)
    print(f"{'clip':<{col}}  status  failing checks")
    print("-" * (col + 40))
    for label, status, fails in rows:
        fail_str = ", ".join(fails) if fails else ""
        print(f"{label:<{col}}  {status:<6}  {fail_str}")

    any_fail = any(r[1] == "FAIL" for r in rows)
    return 1 if any_fail else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <golden.yaml>", file=sys.stderr)
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
