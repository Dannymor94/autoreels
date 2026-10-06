#!/usr/bin/env python3
"""Face/eye detection parameter calibration on real clip frames.

Usage:
    python scripts/calib_faces.py <clip1.mp4> [clip2.mp4 ...]

Extracts 10 evenly-spaced frames per clip via ffmpeg, then runs Haar cascade
detection across four param sets. Writes:
  reviews/_covers_calib/report.csv
  reviews/_covers_calib/boxes/<frame>_A.jpg
  reviews/_covers_calib/boxes/<frame>_B.jpg
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

PARAM_SETS = {
    "A": dict(scaleFactor=1.1,  minNeighbors=5, minSize=(60, 60)),
    "B": dict(scaleFactor=1.05, minNeighbors=3, minSize=(30, 30)),
    "C": dict(scaleFactor=1.1,  minNeighbors=4, minSize=(80, 80)),
    "D": dict(scaleFactor=1.05, minNeighbors=5, minSize=(120, 120)),
}

N_FRAMES = 10


def _probe_duration(clip: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(clip)],
        capture_output=True, text=True,
    )
    import json
    for s in json.loads(r.stdout).get("streams", []):
        if s.get("codec_type") == "video":
            return float(s.get("duration", 0))
    return 0.0


def extract_frames(clip: Path, out_dir: Path) -> list[Path]:
    dur = _probe_duration(clip)
    if dur <= 0:
        print(f"  WARN: cannot probe {clip.name}", file=sys.stderr)
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    # include parent dir name to avoid collisions between clips with the same stem
    clip_tag = f"{clip.parent.name[:20]}_{clip.stem}"
    paths = []
    for k in range(N_FRAMES):
        t = dur * (k + 0.5) / N_FRAMES
        out = out_dir / f"{clip_tag}_{k:02d}.jpg"
        if not out.exists():
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(t), "-i", str(clip),
                 "-frames:v", "1", "-q:v", "2", str(out)],
                capture_output=True,
            )
        paths.append(out)
    return paths


def load_cascades():
    fc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    ec = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
    return fc, ec


def detect_faces(gray: np.ndarray, params: dict) -> list:
    fc, _ = _CASCADES
    rects = fc.detectMultiScale(gray, **params)
    return list(rects) if len(rects) > 0 else []


def count_eyes(gray: np.ndarray, face: tuple, mn: int) -> int:
    _, ec = _CASCADES
    x, y, w, h = face
    roi = gray[y:y+h, x:x+w]
    eyes = ec.detectMultiScale(roi, scaleFactor=1.1, minNeighbors=mn, minSize=(15, 15))
    return len(eyes)


def draw_boxes(img_bgr: np.ndarray, faces: list, eyes_per_face: list[list]) -> np.ndarray:
    out = img_bgr.copy()
    for i, (x, y, w, h) in enumerate(faces):
        cv2.rectangle(out, (x, y), (x+w, y+h), (0, 200, 0), 2)
        for (ex, ey, ew, eh) in eyes_per_face[i]:
            cv2.rectangle(out, (x+ex, y+ey), (x+ex+ew, y+ey+eh), (200, 0, 0), 1)
    return out


_CASCADES = None  # set in main


def process_frame(frame_path: Path) -> list[dict]:
    """Return one row dict per param_set for this frame."""
    img = cv2.imread(str(frame_path))
    if img is None:
        return []
    h_img, w_img = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    rows = []
    for name, params in PARAM_SETS.items():
        faces = detect_faces(gray, params)
        n = len(faces)
        # largest face — convert to plain tuples to avoid numpy array bool ambiguity
        face_tuples = [tuple(int(v) for v in f) for f in faces]
        largest = max(face_tuples, key=lambda f: f[2]*f[3]) if face_tuples else None
        frac = (largest[2] * largest[3]) / (w_img * h_img) if largest is not None else 0.0
        eyes1 = count_eyes(gray, largest, 1) if largest is not None else 0
        eyes3 = count_eyes(gray, largest, 3) if largest is not None else 0
        eyes5 = count_eyes(gray, largest, 5) if largest is not None else 0
        rows.append({
            "frame": frame_path.name,
            "param_set": name,
            "n_faces": n,
            "largest_face_frac": round(frac, 4),
            "eyes_mn1": eyes1,
            "eyes_mn3": eyes3,
            "eyes_mn5": eyes5,
        })
        # draw boxes for A and B
        if name in ("A", "B"):
            _, ec = _CASCADES
            eyes_rects = []
            if largest is not None:
                x, y, w, hh = largest
                roi = gray[y:y+hh, x:x+w]
                er = ec.detectMultiScale(roi, scaleFactor=1.1, minNeighbors=3, minSize=(15, 15))
                eyes_rects = [tuple(int(v) for v in e) for e in er] if len(er) > 0 else []
            vis = draw_boxes(img, face_tuples, [eyes_rects] + [[] for _ in face_tuples[1:]])
            boxes_dir = frame_path.parent.parent / "boxes"
            boxes_dir.mkdir(exist_ok=True)
            out_path = boxes_dir / f"{frame_path.stem}_{name}.jpg"
            cv2.imwrite(str(out_path), vis)
    return rows


def summarise(rows: list[dict]) -> None:
    from collections import defaultdict
    by_set: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_set[r["param_set"]].append(r)

    print("\n=== Calibration summary ===")
    print(f"{'Set':4}  {'%1face':>7}  {'%0face':>7}  {'%≥2face':>8}  {'med_frac':>9}  {'%eyes3≥2':>9}  n")
    print("-" * 68)
    for name in ("A", "B", "C", "D"):
        rs = by_set[name]
        n = len(rs)
        if n == 0:
            continue
        n1 = sum(1 for r in rs if r["n_faces"] == 1)
        n0 = sum(1 for r in rs if r["n_faces"] == 0)
        n2 = sum(1 for r in rs if r["n_faces"] >= 2)
        fracs = sorted(r["largest_face_frac"] for r in rs if r["n_faces"] >= 1)
        med = fracs[len(fracs)//2] if fracs else 0.0
        eyes3_ok = sum(1 for r in rs if r["eyes_mn3"] >= 2)
        print(f"{name:4}  {100*n1/n:>6.1f}%  {100*n0/n:>6.1f}%  {100*n2/n:>7.1f}%  {med:>9.4f}  {100*eyes3_ok/n:>8.1f}%  {n}")


def main(argv=None):
    global _CASCADES
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+", type=Path)
    args = ap.parse_args(argv)

    if not getattr(cv2, "CascadeClassifier", None):
        sys.exit("ERROR: opencv 4.x required (CascadeClassifier missing)")

    _CASCADES = load_cascades()

    # project root: find manifests/
    root = Path(__file__).resolve().parent.parent
    while root != root.parent and not (root / "manifests").is_dir():
        root = root.parent

    frames_dir = root / "reviews" / "_covers_calib" / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    csv_path = root / "reviews" / "_covers_calib" / "report.csv"
    all_rows: list[dict] = []

    for clip in args.clips:
        clip = Path(clip)
        print(f"Extracting frames: {clip.name}")
        frame_paths = extract_frames(clip, frames_dir)
        for fp in frame_paths:
            if fp.exists():
                all_rows.extend(process_frame(fp))

    if not all_rows:
        print("No frames processed.", file=sys.stderr)
        return 1

    fieldnames = ["frame", "param_set", "n_faces", "largest_face_frac", "eyes_mn1", "eyes_mn3", "eyes_mn5"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(all_rows)

    print(f"\nReport: {csv_path}")
    summarise(all_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
