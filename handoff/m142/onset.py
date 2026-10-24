#!/usr/bin/env python3
"""M142 measure (read-only): is the first sound of each clip cut into? And how loud is the first sentence?

For each manifest (a review.json copy) and each clip: the clip's first cut (cold open start, else the body start) and the
body start. Around each cut the source audio (16 kHz mono) is read; level in 10 ms frames. «Cut into speech» = the 30 ms
right BEFORE the cut are ≥ 15 dB above the quiet level of the 0.4 s before it (the speech was already sounding — the
first consonant is lost). Also: the first 2 s of the body vs the median of the clip's first 20 s (dB) — «плохо слышно».
    .venv/bin/python handoff/m142/onset.py reviews/IMG_6848_m126.review.json reviews/IMG_6848_m142.review.json
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

SR = 16000


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


def db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9)) if len(x) else -120.0


def frames_db(x: np.ndarray, step: int = SR // 100) -> np.ndarray:
    n = len(x) // step
    return np.array([db(x[i * step:(i + 1) * step]) for i in range(n)])


def cut_check(src: Path, cut: float) -> tuple[bool, float]:
    a = audio(src, cut - 0.4, 0.45)
    f = frames_db(a)
    if len(f) < 40:
        return False, 0.0
    quiet = float(np.percentile(f[:30], 20))
    before = float(np.max(f[37:40]))           # the 30 ms right before the cut
    return before - quiet >= 15.0, before - quiet


def main(paths) -> int:
    for mp in paths:
        m = json.loads(Path(mp).read_text(encoding="utf-8"))
        src = find_source(m.get("source", ""))
        if src is None:
            print(f"{mp}: source not found")
            continue
        n_cut = 0
        print(f"\n=== {mp}")
        for r in m.get("reels") or []:
            segs = r.get("segments") or [{"start": r["start"], "end": r["end"]}]
            co = r.get("cold_open")
            body0 = float(segs[0]["start"])
            first = float(co["start"]) if co else body0
            c1, d1 = cut_check(src, first)
            c2, d2 = cut_check(src, body0) if co else (c1, d1)
            head = audio(src, body0, 20.0)
            fr = frames_db(head)
            loud = fr[fr > np.percentile(fr, 30)] if len(fr) else fr
            f2 = fr[:200]
            first2 = float(np.median(f2[f2 > np.percentile(f2, 30)])) if len(f2) > 10 else -120.0
            med = float(np.median(loud)) if len(loud) else -120.0
            n_cut += int(c1) + (int(c2) if co else 0)
            print(f"  {r['id']}: первый звук {'ВРЕЗАН' if c1 else 'ок'} (+{d1:.0f} dB до реза)"
                  + (f", начало тела {'ВРЕЗАН' if c2 else 'ок'} (+{d2:.0f} dB)" if co else "")
                  + f"; первые 2 с тела {first2 - med:+.1f} dB к медиане клипа")
        print(f"  врезанных начал: {n_cut}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
