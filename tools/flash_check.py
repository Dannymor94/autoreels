#!/usr/bin/env python3
"""Source-accurate flash detection for two-shot rendered clips.

For each frame, compares the rendered crop to the source with wide and close VF strings.
A frame is classified "wide" or "close" based on which source crop it more closely matches.
Frames where both distances are nearly equal (|d_wide - d_close| < AMBIG_MARGIN) are
treated as ambiguous and skipped — this eliminates false positives from appearance variation.

A flash is a run of non-ambiguous frames shorter than FLASH_THRESH surrounded by the opposite type.

Usage:
  .venv/bin/python tools/flash_check.py <manifest.json> <clip_dir> [--src-dir <dir>]
"""
import argparse, json, subprocess, sys
import numpy as np
from pathlib import Path

FFMPEG = "ffmpeg"
FPS = 30.0
THUMB_W, THUMB_H = 80, 142   # 9:16 at 80px
FLASH_THRESH = 10             # runs shorter than this (surrounded by opposite) → flash
AMBIG_MARGIN = 5.0            # |d_wide - d_close| below this → ambiguous, skip
CLOSE_SCALE = 1.25
CLOSE_ANCHOR_Y = 0.35
PROJECT = Path(__file__).parent.parent


# ── crop geometry ──────────────────────────────────────────────────────────────

def _wide_vf(setup: dict) -> str:
    c = setup["crop"]
    sw, sh = setup["scale"]
    return f"crop={c['w']}:{c['h']}:{c['x']}:{c['y']},scale={sw}:{sh},setsar=1"


def _close_vf(setup: dict) -> str:
    c = setup["crop"]
    cx, cy, cw, ch = c["x"], c["y"], c["w"], c["h"]
    frame_w, frame_h = setup["frame"]
    sw, sh = setup["scale"]
    nch = max(2, int(ch / CLOSE_SCALE)) & ~1
    ncw = max(2, round(nch * cw / ch / 2) * 2)
    ncx = cx + (cw - ncw) // 2
    ncy = cy + int(CLOSE_ANCHOR_Y * (ch - nch))
    ncx = max(0, min(ncx, frame_w - ncw))
    ncy = max(0, min(ncy, frame_h - nch))
    ncw = min(ncw, frame_w - ncx) & ~1
    nch = min(nch, frame_h - ncy) & ~1
    return f"crop={ncw}:{nch}:{ncx}:{ncy},scale={sw}:{sh},setsar=1"


# ── frame extraction ───────────────────────────────────────────────────────────

def _frames(path: Path, ss: float, dur: float, vf: str = "null", force_fps: bool = False) -> np.ndarray:
    fps_filter = f",fps={FPS}" if force_fps else ""
    cmd = [FFMPEG, "-ss", f"{ss:.6f}", "-t", f"{dur:.6f}", "-i", str(path),
           "-vf", f"{vf}{fps_filter},scale={THUMB_W}:{THUMB_H},format=gray",
           "-f", "rawvideo", "-pix_fmt", "gray", "-loglevel", "error", "pipe:1"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    fsz = THUMB_W * THUMB_H
    n = len(raw) // fsz
    return np.frombuffer(raw[:n * fsz], dtype=np.uint8).reshape(n, THUMB_H, THUMB_W)


# ── runs helper ────────────────────────────────────────────────────────────────

def _runs(labels: list) -> list[tuple]:
    """(label, start_frame_1idx, end_frame_1idx) for each run."""
    if not labels:
        return []
    out, cur, s = [], labels[0], 0
    for i, l in enumerate(labels[1:], 1):
        if l != cur:
            out.append((cur, s + 1, i))
            cur, s = l, i
    out.append((cur, s + 1, len(labels)))
    return out


# ── classification ─────────────────────────────────────────────────────────────

def _classify(rendered: np.ndarray, src_wide: np.ndarray, src_close: np.ndarray) -> list[str]:
    n = min(len(rendered), len(src_wide), len(src_close))
    r = rendered[:n].astype(np.float32)
    dw = np.mean(np.abs(r - src_wide[:n].astype(np.float32)), axis=(1, 2))
    dc = np.mean(np.abs(r - src_close[:n].astype(np.float32)), axis=(1, 2))
    labels = []
    for i in range(n):
        diff = float(dw[i]) - float(dc[i])
        if abs(diff) < AMBIG_MARGIN:
            labels.append("ambig")
        elif diff > 0:
            labels.append("close")
        else:
            labels.append("wide")
    return labels


# ── flash detection ────────────────────────────────────────────────────────────

def _find_flashes(labels: list[str], clip_id: str) -> list[str]:
    """Identify short runs (<FLASH_THRESH) of one type surrounded by the opposite type."""
    # Collapse ambig into the neighbour's label for run building
    resolved: list[str] = []
    for l in labels:
        if l != "ambig":
            resolved.append(l)
        elif resolved:
            resolved.append(resolved[-1])  # carry previous
        else:
            resolved.append("wide")  # default at start
    run_list = _runs(resolved)
    flashes = []
    for i, (lbl, s, e) in enumerate(run_list):
        n = e - s + 1
        if n >= FLASH_THRESH:
            continue
        prev = run_list[i - 1][0] if i > 0 else None
        nxt = run_list[i + 1][0] if i < len(run_list) - 1 else None
        if i == len(run_list) - 1 and nxt is None:
            continue  # tail artifact
        if (prev == "close" and nxt == "close" and lbl == "wide") or \
           (prev == "wide" and nxt == "wide" and lbl == "close"):
            t_s = (s - 1) / FPS
            flashes.append(f"  FLASH {clip_id}: {lbl} {n}fr at {t_s:.3f}s")
    return flashes


def _shot_list_str(labels: list[str], fps: float) -> str:
    run_list = _runs(labels)
    lines = []
    for lbl, s, e in run_list:
        n = e - s + 1
        t_s = (s - 1) / fps
        t_e = e / fps
        tag = f" [SHORT<{FLASH_THRESH}fr]" if n < FLASH_THRESH else ""
        lines.append(f"  {lbl:5s} fr {s}–{e} ({n}fr, {t_s:.3f}–{t_e:.3f}s){tag}")
    return "\n".join(lines)


# ── per-reel check ─────────────────────────────────────────────────────────────

def _snap(t: float) -> float:
    return round(t * FPS) / FPS


def check_reel(reel: dict, mp4: Path, src: Path, wide_vf: str, close_vf: str) -> tuple:
    """Returns (all_labels, flashes)."""
    segs = reel.get("segments", [])
    all_labels: list[str] = []
    out_t = 0.0
    for seg in segs:
        src_start = _snap(seg["start"])
        snap_dur = _snap(seg["end"]) - src_start
        if snap_dur <= 0:
            continue
        rendered = _frames(mp4, out_t, snap_dur, "null", force_fps=False)
        src_w = _frames(src, src_start, snap_dur, wide_vf, force_fps=True)
        src_c = _frames(src, src_start, snap_dur, close_vf, force_fps=True)
        seg_labels = _classify(rendered, src_w, src_c)
        all_labels.extend(seg_labels)
        out_t += snap_dur
    rid = reel["id"]
    flashes = _find_flashes(all_labels, rid)
    return all_labels, flashes


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("clip_dir", type=Path)
    ap.add_argument("--src-dir", type=Path, default=PROJECT / "inputs-archive")
    ap.add_argument("--shot-lists", nargs="*", metavar="RID",
                    help="Print per-frame shot list for these reel ids (e.g. r01 r02 r06)")
    args = ap.parse_args()

    m = json.load(open(args.manifest))
    setup = m["setup"]
    wide_vf = _wide_vf(setup)
    close_vf_str = _close_vf(setup)

    stem = setup["setup_id"]
    src = next((args.src_dir / f"{stem}{ext}" for ext in (".mp4", ".MP4", ".mov")
                if (args.src_dir / f"{stem}{ext}").exists()), None)
    if src is None:
        sys.exit(f"Source not found for {stem} in {args.src_dir}")

    print(f"Source:    {src.name}")
    print(f"Wide VF:   {wide_vf}")
    print(f"Close VF:  {close_vf_str}")
    print(f"Clips dir: {args.clip_dir}")
    print()

    show_shot_lists = set(args.shot_lists or [])
    total_flashes = 0
    print(f"{'Clip':<10} {'Frames':>7} {'Ambig%':>7} {'Flashes':>9}")
    print("-" * 40)
    for reel in m["reels"]:
        rid = reel["id"]
        mp4 = args.clip_dir / f"{rid}.mp4"
        if not mp4.exists():
            print(f"{rid:<10} {'missing':>7}")
            continue
        labels, flashes = check_reel(reel, mp4, src, wide_vf, close_vf_str)
        n_ambig = labels.count("ambig")
        pct = f"{100*n_ambig/max(1,len(labels)):.1f}%"
        flag = " !" if flashes else ""
        print(f"{rid:<10} {len(labels):>7} {pct:>7} {len(flashes):>9}{flag}")
        for f in flashes:
            print(f)
        if rid in show_shot_lists:
            non_ambig = [l if l != "ambig" else (labels[i-1] if i else "wide")
                         for i, l in enumerate(labels)]
            print(_shot_list_str(non_ambig, FPS))
        total_flashes += len(flashes)
    print("-" * 40)
    print(f"TOTAL FLASHES: {total_flashes}")


if __name__ == "__main__":
    main()
