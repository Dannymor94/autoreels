"""M78: where the speaker's face is — for the auto crop of a source without a manual calibration.

Owner on PXL_20260729_copy: «ракурс сбит» — the copy has no calibration of its own, the centre crop cut the
speaker who sits left of centre. This module looks at `samples` frames spread over the source (display
orientation, as render sees it), finds the largest frontal face in each (OpenCV Haar cascade — optional
dependency `pip install -e ".[faces]"`; without it the centre crop stays) and returns the face boxes in display
px. core/calibration.face_crop turns them into ONE static rectangle — no tracking (CLAUDE.md).

The result is cached in data/cache/<sha16>.faces.json (local, not in git): every later load is free.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

FACES_VERSION = 1


def _duration(video: Path, ffprobe: str) -> float:
    out = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out or 0.0)


def _gray_frame(video: Path, t: float, size: tuple[int, int], ffmpeg: str):
    import numpy as np
    w, h = size
    cmd = [ffmpeg, "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", "-an",
           "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "pipe:1"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    if len(raw) < w * h:
        return None
    return np.frombuffer(raw[: w * h], dtype=np.uint8).reshape(h, w)


def detect_faces(video, frame_size: tuple[int, int], *, samples: int = 20, ffmpeg: str = "ffmpeg",
                 ffprobe: str = "ffprobe", cache_path: Path | None = None,
                 log=print) -> tuple[list[tuple[float, float, float, float]], int] | None:
    """([(cx, cy, w, h) in display px, one per frame with a face], frames looked at) or None (no OpenCV)."""
    if cache_path is not None and cache_path.is_file():
        try:
            d = json.loads(cache_path.read_text(encoding="utf-8"))
            if d.get("version") == FACES_VERSION and d.get("samples") == samples \
                    and list(d.get("frame") or []) == list(frame_size):
                return [tuple(f) for f in d["faces"]], int(d["samples"])
        except (OSError, ValueError, KeyError):
            pass
    try:
        import cv2
    except ImportError:
        log("поиск лица: OpenCV не установлен (pip install -e \".[faces]\") — кроп по центру")
        return None
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    W, H = frame_size
    sw = min(640, W)
    sw -= sw % 2
    sh = int(round(H * sw / W / 2)) * 2
    dur = _duration(Path(video), ffprobe)
    faces: list[tuple[float, float, float, float]] = []
    k = W / sw
    for i in range(samples):
        t = dur * (i + 0.5) / samples
        img = _gray_frame(Path(video), t, (sw, sh), ffmpeg)
        if img is None:
            continue
        found = cascade.detectMultiScale(img, scaleFactor=1.1, minNeighbors=6, minSize=(max(24, sw // 20),) * 2)
        if len(found):
            x, y, w, h = max(found, key=lambda f: f[2] * f[3])
            faces.append((round(float(x + w / 2) * k, 1), round(float(y + h / 2) * k, 1),
                          round(float(w) * k, 1), round(float(h) * k, 1)))
    if cache_path is not None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"version": FACES_VERSION, "samples": samples, "frame": list(frame_size),
                                              "faces": faces}), encoding="utf-8")
        except OSError:
            pass
    return faces, samples


# ── M96: the cover frame — the face large, the eyes open ───────────────────────────────────────────────────

def cover_candidates(segs, has_cold_open: bool, n: int = 7, edge: float = 0.3) -> list[float]:
    """n source seconds spread evenly over the body windows (the cold open — a teaser — left out), each at least
    `edge` inside its window."""
    body = [s for s in (list(segs[1:]) if has_cold_open and len(segs) > 1 else list(segs))
            if s.end - s.start > 2 * edge]
    total = sum(s.end - s.start - 2 * edge for s in body)
    if total <= 0 or n <= 0:
        return []
    out = []
    for k in range(n):
        x = total * (k + 0.5) / n
        for s in body:
            span = s.end - s.start - 2 * edge
            if x <= span:
                out.append(round(s.start + edge + x, 3))
                break
            x -= span
    return out


def best_face_time(times, grab, detect) -> float | None:
    """The time whose frame shows the largest face with open eyes: score = face area × (1 with two eyes found,
    0.7 with one, 0.4 with none). grab(t) → image or None; detect(img) → (face area, eyes) or None (no face).
    None when no frame has a face."""
    best, best_score = None, 0.0
    for t in times:
        img = grab(t)
        if img is None:
            continue
        found = detect(img)
        if not found:
            continue
        area, eyes = found
        score = float(area) * (1.0 if eyes >= 2 else 0.7 if eyes == 1 else 0.4)
        if score > best_score:
            best, best_score = t, score
    return best


def opencv_face_eyes():
    """detect(img) for best_face_time with OpenCV's Haar cascades (face, then eyes in its upper half), or None when
    OpenCV is not installed."""
    try:
        import cv2
    except ImportError:
        return None
    face = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    eye = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")

    def detect(img):
        h, w = img.shape[:2]
        found = face.detectMultiScale(img, scaleFactor=1.1, minNeighbors=5, minSize=(max(24, w // 10),) * 2)
        if not len(found):
            return None
        x, y, fw, fh = max(found, key=lambda f: f[2] * f[3])
        roi = img[y:y + fh // 2, x:x + fw]
        eyes = eye.detectMultiScale(roi, scaleFactor=1.1, minNeighbors=5, minSize=(max(8, fw // 10),) * 2)
        return int(fw * fh), int(len(eyes))
    return detect
