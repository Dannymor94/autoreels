#!/usr/bin/env python3
"""Cover candidate images for a rendered reel clip.

Reads:   <clip.mp4>
         <clip_dir>/<id>.render.json   (source_start, source_end, synthetic_tail_sec)
         <project_root>/manifests/<stem>.json  (reel title + subtitle words)
Writes:  reels-out/<stem>/_covers/<gate|final>/<id>_cover_1.png  (top 3 candidates)

Usage:
    python scripts/make_covers.py reels-out/video/_gate/g1/r01.mp4
    python scripts/make_covers.py reels-out/video/r01.mp4 --out /custom/out/
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import cv2
    _CV2_OK = True
except ImportError:
    _CV2_OK = False

try:
    import numpy as np
    _NP_OK = True
except ImportError:
    _NP_OK = False

from PIL import Image, ImageDraw, ImageFont

COVER_W, COVER_H = 1080, 1920
MAX_TITLE_LINES = 3
MIN_FRAME_GAP_SEC = 2.0
SKIP_START_SEC = 0.5
FADE_GUARD_SEC = 1.5
TOP_N = 3


# ── project / path helpers ─────────────────────────────────────────────────────


def _project_root(start: Path) -> Path:
    """Walk up from start until a directory containing manifests/ is found."""
    p = start.resolve()
    for _ in range(12):
        if (p / "manifests").is_dir():
            return p
        p = p.parent
    raise FileNotFoundError(f"manifests/ not found above {start}")


def resolve_clip_context(clip: Path) -> tuple[str, str, str]:
    """Return (reel_id, video_stem, gate_label) from the clip path.

    gate_label is the _gate/<name> subdirectory name, or "final" for top-level clips.
    """
    reel_id = clip.stem
    parts = clip.resolve().parts
    for i, part in enumerate(parts):
        if part == "reels-out" and i + 1 < len(parts):
            video_stem = parts[i + 1]
            rest = parts[i + 2 :]
            if len(rest) >= 2 and rest[0] == "_gate":
                return reel_id, video_stem, rest[1]
            return reel_id, video_stem, "final"
    # Fallback: use the parent dir name as video stem
    return reel_id, clip.parent.name, "final"


# ── sidecar / manifest readers ─────────────────────────────────────────────────


def read_render_json(clip: Path) -> dict:
    p = clip.with_suffix("").with_name(f"{clip.stem}.render.json")
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def read_reel(project_root: Path, video_stem: str, reel_id: str) -> dict | None:
    mpath = project_root / "manifests" / f"{video_stem}.json"
    if not mpath.exists():
        return None
    try:
        data = json.loads(mpath.read_text(encoding="utf-8"))
    except Exception:
        return None
    for r in data.get("reels", []):
        if r.get("id") == reel_id:
            return r
    return None


# ── candidate-time logic ───────────────────────────────────────────────────────


def subtitle_sentence_starts(reel: dict, render_json: dict) -> list[float]:
    """Return output-timeline timestamps at sentence starts.

    Uses manifest subtitle words; considers a gap > 0.5 s between consecutive
    words as a sentence boundary.  Handles single-segment and multi-segment
    reels by remapping source-time words onto the output timeline.
    """
    words = reel.get("subtitles", [])
    if not words:
        return []

    segments = reel.get("segments") or [{"start": reel["start"], "end": reel["end"]}]
    speed = reel.get("speed") or 1.0
    BREAK_GAP = 0.5

    # Build sorted list of (out_t0, word) by remapping each word onto output timeline
    remapped: list[float] = []
    for seg in segments:
        seg_start, seg_end = seg["start"], seg["end"]
        offset = sum(
            s["end"] - s["start"]
            for s in segments[: segments.index(seg)]
        )
        for w in words:
            if seg_start <= w["t0"] < seg_end:
                remapped.append((w["t0"] - seg_start + offset) / speed)

    remapped.sort()

    times: list[float] = []
    prev_out: float | None = None
    for out_t in remapped:
        if prev_out is None or (out_t - prev_out) > BREAK_GAP:
            times.append(out_t)
        prev_out = out_t

    return times


def filter_candidate_times(
    times: list[float],
    clip_duration: float,
    *,
    skip_start: float = SKIP_START_SEC,
    fade_guard: float = FADE_GUARD_SEC,
    synthetic_tail: float = 0.0,
) -> list[float]:
    """Remove times in the skip zone, near the fade, or in the synthetic tail."""
    guard_end = max(0.0, clip_duration - fade_guard - synthetic_tail)
    return [t for t in times if skip_start <= t <= guard_end]


# ── frame sampling & scoring ───────────────────────────────────────────────────


def _probe_duration(clip: Path) -> float:
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
    return 0.0


def _extract_frame_bgr(clip: Path, t: float, tmp_dir: Path):
    """Extract one frame at time t via ffmpeg; returns BGR ndarray or None."""
    fname = f"frame_{t:.3f}".replace(".", "_") + ".png"
    out = tmp_dir / fname
    r = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(clip), "-frames:v", "1", str(out)],
        capture_output=True,
    )
    if r.returncode != 0 or not out.exists():
        return None
    if _CV2_OK:
        return cv2.imread(str(out))
    # PIL fallback → BGR array
    import numpy as _np
    arr = _np.array(Image.open(out).convert("RGB"))
    return arr[:, :, ::-1]


def sharpness(img_bgr) -> float:
    """Variance of Laplacian — higher is sharper."""
    if not (_CV2_OK and _NP_OK):
        return 0.0
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


# ── cascade availability ───────────────────────────────────────────────────────


class CascadeUnavailableError(RuntimeError):
    """Raised when the Haar face cascade cannot be loaded (cv2 missing or too new)."""


def require_cascade() -> None:
    """Check that face detection is operational; raise CascadeUnavailableError if not.

    Call once at start-up before processing any clips.  The error message tells
    the user exactly how to fix the situation.
    """
    if not _CV2_OK:
        raise CascadeUnavailableError(
            "face detection unavailable: cv2 not installed — "
            "run: pip install 'autoreels[publish]'"
        )
    if not getattr(cv2, "CascadeClassifier", None):
        raise CascadeUnavailableError(
            "face detection unavailable: CascadeClassifier removed in cv2 "
            f"{cv2.__version__} (cv2 5.x) — "
            "run: pip install 'autoreels[publish]'  "
            "(pins opencv-python-headless>=4.9,<5)"
        )
    xml = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    if not Path(xml).exists():
        raise CascadeUnavailableError(
            "face detection unavailable: haarcascade XML not found — "
            "run: pip install 'autoreels[publish]'"
        )
    cc = cv2.CascadeClassifier(xml)
    if cc.empty():
        raise CascadeUnavailableError(
            "face detection unavailable: cascade file loaded empty — "
            "run: pip install 'autoreels[publish]'"
        )


# Cascade caches (loaded once on first use after require_cascade() is called)
_cascade_obj = None
_cascade_loaded = False
_eye_cascade_obj = None
_eye_cascade_loaded = False


def _load_cascade():
    global _cascade_obj, _cascade_loaded
    if _cascade_loaded:
        return _cascade_obj
    _cascade_loaded = True
    if not _CV2_OK or not getattr(cv2, "CascadeClassifier", None):
        return None
    xml = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    if Path(xml).exists():
        cc = cv2.CascadeClassifier(xml)
        _cascade_obj = None if cc.empty() else cc
    return _cascade_obj


def _load_eye_cascade():
    global _eye_cascade_obj, _eye_cascade_loaded
    if _eye_cascade_loaded:
        return _eye_cascade_obj
    _eye_cascade_loaded = True
    if not _CV2_OK or not getattr(cv2, "CascadeClassifier", None):
        return None
    xml = cv2.data.haarcascades + "haarcascade_eye.xml"
    if Path(xml).exists():
        cc = cv2.CascadeClassifier(xml)
        _eye_cascade_obj = None if cc.empty() else cc
    return _eye_cascade_obj


def _detect_faces(gray, *, cascade) -> list:
    """Return list of (x, y, w, h) tuples for each detected face."""
    try:
        result = cascade.detectMultiScale(gray, 1.05, 3, minSize=(30, 30))
    except Exception:
        return []
    return list(result) if hasattr(result, "__len__") and len(result) else []


def _eyes_in_face(gray, face_bbox, *, eye_cascade) -> int:
    """Count eyes (0..2) found inside the face ROI."""
    if eye_cascade is None:
        return 0
    x, y, w, h = face_bbox
    roi = gray[y : y + h, x : x + w]
    try:
        eyes = eye_cascade.detectMultiScale(roi, 1.05, 1, minSize=(10, 10))
    except Exception:
        return 0
    return min(2, len(eyes) if hasattr(eyes, "__len__") else 0)


def face_area_fraction(img_bgr, *, cascade=None) -> float:
    """Largest face area as fraction of image area (0..1).  cascade=None → module-level."""
    if not (_CV2_OK and _NP_OK):
        return 0.0
    if cascade is None:
        cascade = _load_cascade()
    if cascade is None:
        return 0.0
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    faces = _detect_faces(gray, cascade=cascade)
    if not faces:
        return 0.0
    h, w = img_bgr.shape[:2]
    return max(fw * fh / (w * h) for _, _, fw, fh in faces)


def score_frame(img_bgr, *, cascade=None, eye_cascade=None) -> float:
    """Composite score: sharpness + face area (2×) + eye bonus (+1 if two eyes visible)."""
    if not (_CV2_OK and _NP_OK):
        return sharpness(img_bgr) / 500.0

    if cascade is None:
        cascade = _load_cascade()
    if eye_cascade is None:
        eye_cascade = _load_eye_cascade()

    sharp = sharpness(img_bgr)
    if cascade is None:
        return sharp / 500.0

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    faces = _detect_faces(gray, cascade=cascade)

    if not faces:
        return sharp / 500.0

    h, w = img_bgr.shape[:2]
    face_score = max(fw * fh / (w * h) for _, _, fw, fh in faces)

    # Eye bonus: +1.0 if any detected face has two visible eyes
    eye_bonus = 0.0
    for face_bbox in faces:
        if _eyes_in_face(gray, face_bbox, eye_cascade=eye_cascade) >= 2:
            eye_bonus = 1.0
            break

    return sharp / 500.0 + face_score * 2.0 + eye_bonus


def pick_top_frames(
    scored: list[tuple[float, float]],
    n: int = TOP_N,
    min_gap: float = MIN_FRAME_GAP_SEC,
) -> list[tuple[float, float]]:
    """From [(time, score), ...] pick top-n at least min_gap seconds apart (greedy)."""
    ranked = sorted(scored, key=lambda x: -x[1])
    picked: list[tuple[float, float]] = []
    for t, sc in ranked:
        if all(abs(t - pt) >= min_gap for pt, _ in picked):
            picked.append((t, sc))
        if len(picked) == n:
            break
    return sorted(picked, key=lambda x: x[0])


# ── font / cover rendering ─────────────────────────────────────────────────────

_font_path_cache: str | None = None
_font_path_searched = False


def _find_font_path() -> str | None:
    global _font_path_cache, _font_path_searched
    if _font_path_searched:
        return _font_path_cache
    _font_path_searched = True
    project = Path(__file__).resolve().parent.parent
    candidates = [
        project / "assets" / "fonts" / "DejaVuSans-Bold.ttf",
        project / "assets" / "fonts" / "InterBold.ttf",
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    for p in candidates:
        if p.exists():
            _font_path_cache = str(p)
            return _font_path_cache
    return None


def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = _find_font_path()
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def wrap_title(
    text: str,
    font,
    *,
    max_lines: int = MAX_TITLE_LINES,
    max_width_px: int = COVER_W - 80,
) -> list[str]:
    """Greedily wrap text into ≤ max_lines lines, each ≤ max_width_px (PIL estimate)."""
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    cur: list[str] = []
    for idx, w in enumerate(words):
        trial = " ".join(cur + [w])
        try:
            w_px = font.getbbox(trial)[2]
        except Exception:
            w_px = len(trial) * 14
        if cur and w_px > max_width_px:
            lines.append(" ".join(cur))
            if len(lines) == max_lines - 1:
                # Dump all remaining words into the last line
                lines.append(" ".join(words[idx:]))
                return lines[:max_lines]
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    return lines[:max_lines]


def render_cover(frame_bgr, title: str, out: Path, *, font_size_hint: int = 120) -> None:
    """Write a 1080×1920 cover: frame as background, title in the upper third."""
    if _CV2_OK:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
    else:
        import numpy as _np
        img = Image.fromarray(frame_bgr[:, :, ::-1])

    img = img.resize((COVER_W, COVER_H), Image.LANCZOS)
    draw = ImageDraw.Draw(img)

    title_area_h = COVER_H // 3
    margin = 40
    max_w = COVER_W - margin * 2

    # Auto-size: find largest font that fits the wrapped text in the title area
    chosen_font = _get_font(font_size_hint)
    chosen_lines: list[str] = [title]
    chosen_line_h = font_size_hint + 16

    for fs in range(font_size_hint, 32, -4):
        font = _get_font(fs)
        lines = wrap_title(title, font, max_width_px=max_w)
        try:
            _, top, _, bot = font.getbbox("Ag")
            line_h = (bot - top) + 16
        except Exception:
            line_h = fs + 16
        total_h = line_h * len(lines)
        if total_h <= int(title_area_h * 0.85):
            chosen_font, chosen_lines, chosen_line_h = font, lines, line_h
            break

    total_h = chosen_line_h * len(chosen_lines)
    y = margin + max(0, (title_area_h - margin - total_h) // 2)
    for line in chosen_lines:
        for dx, dy in [(-2, 2), (2, 2), (-2, -2), (2, -2), (0, 3), (3, 0), (-3, 0), (0, -3)]:
            draw.text((margin + dx, y + dy), line, font=chosen_font, fill=(0, 0, 0))
        draw.text((margin, y), line, font=chosen_font, fill=(255, 255, 255))
        y += chosen_line_h

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out))


# ── main ───────────────────────────────────────────────────────────────────────


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate cover candidate images for a reel clip.")
    ap.add_argument("clip", type=Path, help="Path to the rendered clip (.mp4)")
    ap.add_argument("--out", type=Path, default=None, help="Output directory (auto-detected if omitted)")
    args = ap.parse_args(argv)

    # Face detection is required — fail early with a clear install instruction.
    try:
        require_cascade()
    except CascadeUnavailableError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    clip: Path = args.clip.resolve()
    if not clip.exists():
        print(f"ERROR: clip not found: {clip}", file=sys.stderr)
        return 1

    reel_id, video_stem, gate_label = resolve_clip_context(clip)
    render_json = read_render_json(clip)

    try:
        root = _project_root(clip)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    reel = read_reel(root, video_stem, reel_id)
    if reel is None:
        print(f"ERROR: reel {reel_id!r} not found in manifests/{video_stem}.json", file=sys.stderr)
        return 1

    title = reel.get("title_overlay") or reel.get("title") or ""

    # Determine output directory
    if args.out:
        out_dir = args.out.resolve()
    else:
        reels_out = root / "reels-out"
        out_dir = reels_out / video_stem / "_covers" / gate_label

    clip_duration = _probe_duration(clip)
    synthetic_tail = render_json.get("synthetic_tail_sec", 0.0)

    # Sample times from subtitle sentence starts
    times = subtitle_sentence_starts(reel, render_json)
    times = filter_candidate_times(times, clip_duration, synthetic_tail=synthetic_tail)

    if not times:
        # Fallback: sample every 3 seconds
        times = list(range(int(SKIP_START_SEC) + 1, max(1, int(clip_duration - FADE_GUARD_SEC)), 3))
        times = [float(t) for t in times]

    # Extract frames, score, pick top 3
    scored: list[tuple[float, float]] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for t in times:
            frame = _extract_frame_bgr(clip, t, tmp_dir)
            if frame is None:
                continue
            scored.append((t, score_frame(frame)))

    if not scored:
        print("ERROR: no frames extracted", file=sys.stderr)
        return 1

    top = pick_top_frames(scored, n=TOP_N)

    # Re-extract and render covers
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for n, (t, sc) in enumerate(top, 1):
            frame = _extract_frame_bgr(clip, t, tmp_dir)
            if frame is None:
                continue
            out_path = out_dir / f"{reel_id}_cover_{n}.png"
            render_cover(frame, title, out_path)
            print(f"  cover {n}: {out_path.relative_to(root) if root else out_path}  (t={t:.2f}s, score={sc:.2f})")

    print(f"Done: {len(top)} covers in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
