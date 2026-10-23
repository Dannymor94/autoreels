#!/usr/bin/env python3
"""M137 measure B (read-only for the project): is laughter / applause in the room a sign of the owner's clips?

PANNs Cnn14_DecisionLevelMax (AudioSet, 527 classes, framewise) over each source with owner clips
(manifests/<stem>.json, selection_source human). Per second: max probability of the laughter classes and of the
applause/cheering classes → data/cache/m137/<stem>.laugh.json (kept, so a rerun is instant). Then:
  * owner clips with laughter inside or within 3 s after the end vs random windows of the same lengths;
  * enrichment: share of laughter seconds inside owner clips / share of the source time they cover;
  * map units (transcripts/<stem>.map.json): AUC of «laughter in the unit or 3 s after» for taken / start.

Run with its own venv (torch is not a project dependency):
    ~/.venvs/m137/bin/python handoff/m137/laugh.py [stem ...]
"""
from __future__ import annotations

import glob
import json
import random
import subprocess
import sys
from pathlib import Path

import numpy as np

SR = 32000
CHUNK_S = 30
THRS = (0.2, 0.4)
LAUGH_KEYS = ("laugh", "chuckle", "giggle", "chortle")
APPL_KEYS = ("applause", "cheering", "clapping")
AFTER_S = 3.0
OUT = Path("data/cache/m137")


def find_source(name: str) -> Path | None:
    for d in ("inputs", "inputs-archive"):
        for p in Path(d).rglob("*"):
            if p.is_file() and p.name == Path(name).name:
                return p
    return None


def per_second(src: Path, stem: str) -> dict:
    cache = OUT / f"{stem}.laugh.json"
    if cache.is_file():
        return json.loads(cache.read_text())
    import torch  # noqa: F401
    from panns_inference import SoundEventDetection, labels
    li = [i for i, l in enumerate(labels) if any(k in l.lower() for k in LAUGH_KEYS)]
    ai = [i for i, l in enumerate(labels) if any(k in l.lower() for k in APPL_KEYS)]
    sed = SoundEventDetection(checkpoint_path=None, device="cpu")
    OUT.mkdir(parents=True, exist_ok=True)
    raw = OUT / f"{stem}.f32"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", str(SR),
                    "-f", "f32le", str(raw)], check=True)
    audio = np.memmap(raw, dtype=np.float32, mode="r")
    n_sec = len(audio) // SR
    laugh, appl = np.zeros(n_sec), np.zeros(n_sec)
    for c0 in range(0, n_sec, CHUNK_S):
        seg = np.array(audio[c0 * SR:min(n_sec, c0 + CHUNK_S) * SR], dtype=np.float32)
        if len(seg) < SR:
            break
        fw = sed.inference(seg[None, :])[0]               # (frames, 527)
        fps = fw.shape[0] / (len(seg) / SR)
        for s in range(len(seg) // SR):
            f0, f1 = int(s * fps), max(int(s * fps) + 1, int((s + 1) * fps))
            laugh[c0 + s] = float(fw[f0:f1, li].max())
            appl[c0 + s] = float(fw[f0:f1, ai].max())
        print(f"  {stem}: {min(n_sec, c0 + CHUNK_S)}/{n_sec} s", end="\r", flush=True)
    print()
    del audio
    raw.unlink()
    d = {"laugh": [round(x, 3) for x in laugh], "applause": [round(x, 3) for x in appl],
         "classes": {"laugh": [labels[i] for i in li], "applause": [labels[i] for i in ai]}}
    cache.write_text(json.dumps(d))
    return d


def peak(arr, a, b) -> float:
    i0, i1 = max(0, int(a)), min(len(arr), int(b) + 1)
    return max(arr[i0:i1]) if i1 > i0 else 0.0


def auc(xs, ys):
    pos = [x for x, y in zip(xs, ys) if y]
    neg = [x for x, y in zip(xs, ys) if not y]
    if not pos or not neg:
        return None
    return sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg) / (len(pos) * len(neg))


def main(only) -> int:
    rnd = random.Random(137)
    tot = {"clips": 0, "rand": 0}
    hit = {t: [0, 0] for t in THRS}
    uni = {"x": [], "taken": [], "start": []}
    for mp in sorted(glob.glob("manifests/*.json")):
        try:
            m = json.load(open(mp, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(m, dict) or m.get("selection_source") != "human":
            continue
        stem = Path(mp).stem
        if only and stem not in only:
            continue
        src = find_source(m.get("source", ""))
        if src is None:
            print(f"skip {stem}: source not found in inputs*/")
            continue
        d = per_second(src, stem)
        L = d["laugh"]; A = d["applause"]
        both = [max(x, y) for x, y in zip(L, A)]
        clips = [[(float(s["start"]), float(s["end"])) for s in (r.get("segments") or [])]
                 or [(float(r["start"]), float(r["end"]))] for r in m.get("reels") or []]
        dur = len(both)
        line = [f"{stem}: {dur} s, laughter seconds ≥0.4: {sum(1 for x in L if x >= 0.4)}, applause ≥0.4: "
                f"{sum(1 for x in A if x >= 0.4)}"]
        for t in THRS:
            c_hit = sum(1 for c in clips if max(peak(both, a, b + (AFTER_S if (a, b) == c[-1] else 0)) for a, b in c) >= t)
            r_hit = 0
            for _ in range(20):
                for c in clips:
                    ln = sum(b - a for a, b in c)
                    s0 = rnd.uniform(0, max(1.0, dur - ln - AFTER_S))
                    r_hit += peak(both, s0, s0 + ln + AFTER_S) >= t
            hit[t][0] += c_hit; hit[t][1] += r_hit
            line.append(f"  thr {t}: owner clips with laughter/applause {c_hit}/{len(clips)}, random {r_hit / 20:.1f}/{len(clips)}")
        inside = set()
        for c in clips:
            for a, b in c:
                inside.update(range(int(a), int(b) + 1))
        ls = [i for i, x in enumerate(both) if x >= 0.4]
        if ls:
            line.append(f"  enrichment: {sum(1 for i in ls if i in inside) / len(ls):.2f} of laughter seconds inside clips "
                        f"that cover {len(inside) / max(1, dur):.2f} of the source")
        tot["clips"] += len(clips); tot["rand"] += len(clips)
        mj = Path("transcripts") / f"{stem}.map.json"
        if mj.is_file():
            starts = [min(a for a, _ in c) for c in clips]
            spans = [s for c in clips for s in c]
            for u in json.loads(mj.read_text(encoding="utf-8")).get("units") or []:
                a, b = float(u["t0"]), float(u["t1"])
                uni["x"].append(peak(both, a, b + AFTER_S))
                uni["taken"].append(int(sum(max(0.0, min(b, s1) - max(a, s0)) for s0, s1 in spans) >= 0.5 * (b - a)))
                uni["start"].append(int(any(a - 1.0 <= s <= b + 1.0 and s < b - 0.5 for s in starts)))
        print("\n".join(line))
    print("\n=== ALL")
    for t in THRS:
        print(f"thr {t}: owner clips {hit[t][0]}/{tot['clips']} ({hit[t][0] / max(1, tot['clips']):.0%}), "
              f"random {hit[t][1] / 20:.1f}/{tot['clips']} ({hit[t][1] / 20 / max(1, tot['clips']):.0%})")
    if uni["x"]:
        print(f"map units {len(uni['x'])}: AUC laughter→taken {auc(uni['x'], uni['taken']):.2f}, "
              f"→start {auc(uni['x'], uni['start']):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(set(sys.argv[1:])))
