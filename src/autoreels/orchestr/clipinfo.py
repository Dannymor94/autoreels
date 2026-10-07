"""Per-clip facts for the overview screen: duration, title, poster frame.

Everything is derived from files on disk and cached by (path, mtime, size), so a re-render
automatically gets a fresh duration and poster. Missing ffmpeg/ffprobe → None, never a crash.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

POSTER_AT_S = 1.5  # title plate is fully visible by then
POSTER_WIDTH = 360

_duration_cache: dict[tuple[str, int, int], float | None] = {}


def _key(path: Path) -> tuple[str, int, int]:
    st = path.stat()
    return (str(path), st.st_mtime_ns, st.st_size)


def duration_s(path: Path) -> float | None:
    k = _key(path)
    if k in _duration_cache:
        return _duration_cache[k]
    ffprobe = shutil.which("ffprobe")
    value: float | None = None
    if ffprobe:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=20,
        )
        try:
            value = round(float(r.stdout.strip()), 2)
        except ValueError:
            value = None
    _duration_cache[k] = value
    return value


def title(path: Path) -> str | None:
    """First non-empty line of r05.txt next to r05.mp4 (the publish caption file)."""
    txt = path.with_suffix(".txt")
    if not txt.is_file():
        return None
    try:
        for line in txt.read_text(encoding="utf-8").splitlines():
            if line.strip():
                return line.strip()
    except (OSError, UnicodeDecodeError):
        return None
    return None


def poster(path: Path, cache_dir: Path) -> Path | None:
    """JPEG poster for a clip, generated once per (path, mtime, size). None if ffmpeg is missing."""
    digest = hashlib.sha1("|".join(map(str, _key(path))).encode()).hexdigest()
    out = cache_dir / f"{digest}.jpg"
    if out.is_file():
        return out
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    dur = duration_s(path) or 0.0
    at = min(POSTER_AT_S, dur / 2) if dur else 0.0
    fd, tmp = tempfile.mkstemp(suffix=".jpg", dir=cache_dir)
    os.close(fd)
    r = subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", str(path), "-frames:v", "1",
         "-vf", f"scale={POSTER_WIDTH}:-2", "-q:v", "4", tmp],
        capture_output=True, timeout=30,
    )
    if r.returncode != 0 or os.path.getsize(tmp) == 0:
        os.unlink(tmp)
        return None
    os.replace(tmp, out)  # atomic: parallel requests never see a half-written file
    return out
