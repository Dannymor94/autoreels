#!/usr/bin/env python3
"""M143 measure (read-only): is the START of a rendered clip quieter than the same speech later in it?

m142 measured the SOURCE around the cut and found nothing the air could fix. The owner hears the first letter / the first
phrase too quiet in the RENDERED clip. Suspect: the single-pass loudnorm (dynamic) — it estimates loudness over a window
and its gain settles in the first second(s); and the 10 ms edge fade. Here, for each rendered clip of a gate: the gain
the render applied = rendered level − source level, in 100 ms frames over the first window (rendered t=0 ↔ the source
cut; speed 1 only). Gain in 0–0.3 s, 0.3–1 s, 1–2 s vs the steady gain (median of 3 s … end of the first window).
    .venv/bin/python handoff/m143/ramp.py reviews/IMG_6848_m126.review.json reels-out/IMG_6848/_gate/m126
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

SR = 16000
STEP = SR // 10


def find_source(name: str) -> Path | None:
    for d in ("inputs", "inputs-archive"):
        for p in Path(d).rglob("*"):
            if p.is_file() and p.name == Path(name).name:
                return p
    return None


def audio(src: Path, t0: float, dur: float) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t0):.3f}", "-t", f"{dur:.3f}", "-i", str(src),
                          "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def fdb(x: np.ndarray) -> np.ndarray:
    n = len(x) // STEP
    return np.array([20 * np.log10(np.sqrt(np.mean(x[i * STEP:(i + 1) * STEP] ** 2)) + 1e-9) for i in range(n)])


def main(review: str, gate: str) -> int:
    m = json.loads(Path(review).read_text(encoding="utf-8"))
    src = find_source(m.get("source", ""))
    if src is None:
        print("source not found")
        return 1
    rows = []
    for r in m.get("reels") or []:
        mp4 = Path(gate) / f"{r['id']}.mp4"
        if not mp4.is_file():
            continue
        if float(r.get("speed") or 1.0) != 1.0:
            print(f"  {r['id']}: speed {r.get('speed')} — skipped")
            continue
        co = r.get("cold_open")
        segs = r.get("segments") or [{"start": r["start"], "end": r["end"]}]
        w0 = co if co else segs[0]
        a, b = float(w0["start"]), float(w0["end"])
        dur = min(b - a, 12.0)
        if dur < 3.5:
            print(f"  {r['id']}: first window {b - a:.1f} s — too short to compare")
            continue
        s = fdb(audio(src, a, dur))
        o = fdb(audio(mp4, 0.0, dur))
        n = min(len(s), len(o))
        g = o[:n] - s[:n]
        speech = s[:n] > np.percentile(s[:n], 40)       # only frames with speech in the source
        def gain(i0, i1):
            sel = [g[i] for i in range(i0, min(i1, n)) if speech[i]]
            return float(np.median(sel)) if sel else float("nan")
        steady = gain(30, n)
        row = (r["id"], gain(0, 3) - steady, gain(3, 10) - steady, gain(10, 20) - steady, steady)
        rows.append(row)
        print(f"  {row[0]}: усиление относительно устойчивого — 0–0.3 с {row[1]:+.1f} dB, 0.3–1 с {row[2]:+.1f}, "
              f"1–2 с {row[3]:+.1f} (устойчивое {row[4]:+.1f} dB)")
    if rows:
        def med(k):
            v = [x[k] for x in rows if x[k] == x[k]]
            return sorted(v)[len(v) // 2] if v else float("nan")
        print(f"медиана по клипам: 0–0.3 с {med(1):+.1f} dB, 0.3–1 с {med(2):+.1f}, 1–2 с {med(3):+.1f}; "
              f"клипов с провалом начала ≥ 3 dB: {sum(1 for x in rows if x[1] <= -3)} из {len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
