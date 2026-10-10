"""How visible a jump cut is (M30b): the picture difference across a filler cut, from the video.

Why: cutting «э/ммм» out of a talking head makes the face jump at every cut. Owner on the IMG_6848
test (M30): r05 (3 cuts) — shorter and nothing noticed; r01 (27 cuts, one every ~2 s) — «лицо
постоянно дёргается». A cut is invisible when the head is (nearly) where it was: the frame
before the cut and the frame after it differ no more than two frames 0.1 s apart normally do.

Track: the clip framing (setup crop) downscaled to THUMB_W×THUMB_H grey, FPS frames per second,
for the whole source — data/cache/<stem>.motion.npz (local, rebuilt from the video; not in git).
jump(a, b) = mean |frame just before a − frame just after b| / the source's typical motion
(median difference of frames 0.1 s apart). 1.0 = an ordinary moment of speech; larger = a jump.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

import numpy as np

FPS = 10
THUMB_W, THUMB_H = 27, 48
MOTION_VERSION = 1


def thumb_track(src: Path, crop: tuple[int, int, int, int], *, ffmpeg: str = "ffmpeg",
                rotate_vf: str = "") -> np.ndarray:
    """(N, THUMB_H, THUMB_W) uint8 grey thumbnails of the crop region, FPS per second."""
    w, h, x, y = crop
    vf = (f"{rotate_vf}," if rotate_vf else "") + \
        f"fps={FPS},crop={w}:{h}:{x}:{y},scale={THUMB_W}:{THUMB_H}:flags=area,format=gray"
    cmd = [ffmpeg, "-v", "error", "-i", str(src), "-an", "-vf", vf, "-f", "rawvideo", "pipe:1"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    n = len(raw) // (THUMB_W * THUMB_H)
    return np.frombuffer(raw[: n * THUMB_W * THUMB_H], dtype=np.uint8).reshape(n, THUMB_H, THUMB_W)


def baseline(frames: np.ndarray) -> float:
    """Typical picture change between frames 1/FPS apart (median over the source)."""
    if len(frames) < 2:
        return 1.0
    d = np.abs(frames[1:].astype(np.int16) - frames[:-1].astype(np.int16)).mean(axis=(1, 2))
    return max(float(np.median(d)), 0.5)


def jump_lookup(frames: np.ndarray | None) -> Callable[[float, float], float] | None:
    """(a, b) → picture jump of a cut removing source [a, b], in units of typical motion."""
    if frames is None or len(frames) < 2:
        return None
    base = baseline(frames)
    n = len(frames)

    def jump(a: float, b: float) -> float:
        i = min(n - 1, max(0, int(np.floor(a * FPS))))          # last frame shown before the cut
        j = min(n - 1, max(0, int(np.ceil(b * FPS))))           # first frame shown after it
        d = np.abs(frames[j].astype(np.int16) - frames[i].astype(np.int16)).mean()
        return float(d) / base
    return jump


def save(path: Path, frames: np.ndarray, source_sha256: str, crop) -> None:
    np.savez_compressed(path, frames=frames, version=MOTION_VERSION, sha=source_sha256,
                        crop=np.array(crop), fps=FPS)


def load(path: Path, source_sha256: str | None = None, crop=None) -> np.ndarray | None:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        d = np.load(p, allow_pickle=False)
        if int(d["version"]) != MOTION_VERSION or int(d["fps"]) != FPS:
            return None
        if source_sha256 and str(d["sha"]) != source_sha256:
            return None
        if crop is not None and list(d["crop"]) != list(crop):
            return None
        return d["frames"]
    except (OSError, ValueError, KeyError):
        return None
