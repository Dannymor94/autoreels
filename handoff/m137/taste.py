#!/usr/bin/env python3
"""M137 measure (read-only): can the owner's choice be told from features the code already has or can count?

Unit = a thought of the map (transcripts/<stem>.map.json). Labels from the owner's clips (manifests/<stem>.json,
selection_source human — the only owner-made clips in git):
  taken — the unit lies in an owner clip (≥ 50 % of its time);
  start — an owner clip starts inside the unit (± 1 s).
Features: the map passport (role, punch, standalone, refers, voice), the position, and hook features of the unit's
first words counted by code (a number, «вы/ты», a question, a hedge, a filler or a pointer back first, a contrast,
a strong negation, a name). Plus reviews/verdicts.jsonl (sheet decisions), counted only.

Prints per-feature AUC (0.5 = no signal) for both labels, then a leave-one-source-out logistic regression.
    .venv/bin/python handoff/m137/taste.py            # all sources with a map
"""
from __future__ import annotations

import glob
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

HEDGE = ("наверное", "может быть", "мне кажется", "как бы", "в принципе", "типа", "вроде", "кажется", "возможно")
FILLER = ("ну", "вот", "так", "значит", "короче", "э", "эм")
BACKREF = ("это", "этот", "эта", "эти", "он", "она", "они", "оно", "но", "и", "а", "поэтому", "так что", "тогда",
           "там", "тут", "здесь", "его", "её", "их", "то")
CONTRAST = ("но", "однако", "на самом деле", "а на самом деле", "вместо", "наоборот", "ошибка", "миф")
NEGATE = ("никогда", "никто", "ничего", "нельзя", "невозможно", "не надо", "не нужно", "всегда", "каждый")
NUMW = ("один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять", "десять", "сто", "тысяч",
        "миллион", "первый", "второй", "третий", "половин", "процент")
ROLES = ("question", "thesis", "explanation", "example", "metaphor", "conclusion", "address", "aside")


def norm(t: str) -> str:
    return re.sub(r"[^\w\s-]", " ", t.lower().replace("ё", "е")).strip()


def hook_feats(text: str) -> dict:
    words = text.split()
    first = norm(" ".join(words[:10]))
    fw = first.split()
    head = " ".join(fw[:3])
    return {
        "h_number": int(bool(re.search(r"\d", " ".join(words[:10]))) or any(w.startswith(NUMW) for w in fw)),
        "h_you": int(any(w in ("вы", "ты", "вам", "тебе", "вас", "тебя", "ваш", "твой") for w in fw)),
        "h_question": int("?" in " ".join(words[:14])),
        "h_hedge": int(any(h in first for h in HEDGE)),
        "h_filler_first": int(bool(fw) and fw[0] in FILLER),
        "h_backref_first": int(bool(fw) and (fw[0] in BACKREF or head.startswith(("так что", "и вот")))),
        "h_contrast": int(any(c in first for c in CONTRAST)),
        "h_negate": int(any(n in first for n in NEGATE)),
        "h_name": int(any(w[:1].isupper() for w in words[1:10] if w[:1].isalpha())),
        "h_words_to_stop": next((i + 1 for i, w in enumerate(words) if w.endswith((".", "?", "!"))), len(words)),
    }


def unit_feats(u: dict, dur_src: float) -> dict:
    v = u.get("voice") or {}
    f = {
        "punch": float(u.get("punch") or 0),
        "standalone": int(bool(u.get("standalone"))),
        "refers": int(u.get("refers") is not None),
        "energy": float(v.get("energy") or 0),
        "range_st": float(v.get("range_st") or 0),
        "rate": float(v.get("rate") or 0),
        "level_db": float(v.get("level_db") or -90),
        "dur": float(u["t1"]) - float(u["t0"]),
        "pos": float(u["t0"]) / max(1.0, dur_src),
        "filtered": int(bool(u.get("filtered"))),
        "similar_n": len(u.get("similar") or []),
    }
    for r in ROLES:
        f[f"role_{r}"] = int(u.get("role") == r)
    f.update(hook_feats(u.get("text") or ""))
    return f


def auc(xs, ys) -> float | None:
    pos = [x for x, y in zip(xs, ys) if y]
    neg = [x for x, y in zip(xs, ys) if not y]
    if not pos or not neg:
        return None
    s = 0.0
    for p in pos:
        for n in neg:
            s += 1.0 if p > n else 0.5 if p == n else 0.0
    return s / (len(pos) * len(neg))


def logreg(X, y, l2=1.0, it=400, lr=0.1):
    d = len(X[0]); w = [0.0] * (d + 1)
    for _ in range(it):
        g = [0.0] * (d + 1)
        for xi, yi in zip(X, y):
            z = w[-1] + sum(a * b for a, b in zip(w, xi))
            p = 1 / (1 + math.exp(-max(-30, min(30, z))))
            for k in range(d):
                g[k] += (p - yi) * xi[k]
            g[-1] += p - yi
        for k in range(d):
            w[k] -= lr * (g[k] / len(X) + l2 * w[k] / len(X))
        w[-1] -= lr * g[-1] / len(X)
    return w


def main() -> int:
    rows = []   # (stem, feats, taken, start)
    for mp in sorted(glob.glob("manifests/*.json")):
        try:
            m = json.load(open(mp, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(m, dict) or m.get("selection_source") != "human":
            continue
        stem = Path(mp).stem
        mj = Path("transcripts") / f"{stem}.map.json"
        if not mj.is_file():
            print(f"skip {stem}: no map")
            continue
        units = json.loads(mj.read_text(encoding="utf-8")).get("units") or []
        if not units:
            continue
        dur_src = max(float(u["t1"]) for u in units)
        clips = [[(float(s["start"]), float(s["end"])) for s in (r.get("segments") or [])]
                 or [(float(r["start"]), float(r["end"]))] for r in m.get("reels") or []]
        starts = [min(a for a, _ in c) for c in clips]
        spans = [s for c in clips for s in c]
        for u in units:
            a, b = float(u["t0"]), float(u["t1"])
            ins = sum(max(0.0, min(b, s1) - max(a, s0)) for s0, s1 in spans)
            taken = int(ins >= 0.5 * (b - a))
            start = int(any(a - 1.0 <= s <= b + 1.0 and s < b - 0.5 for s in starts))
            rows.append((stem, unit_feats(u, dur_src), taken, start))
        print(f"{stem}: units {len(units)}, owner clips {len(clips)}, taken {sum(r[2] for r in rows if r[0] == stem)}, "
              f"starts {sum(r[3] for r in rows if r[0] == stem)}")
    vp = Path("reviews/verdicts.jsonl")
    if vp.is_file():
        vs = [json.loads(l) for l in vp.read_text(encoding="utf-8").splitlines() if l.strip()]
        print(f"\nverdicts.jsonl: {len(vs)} rows; " + ", ".join(f"{k} {n}" for k, n in Counter(v.get('verdict') for v in vs).items())
              + "; reasons: " + ", ".join(f"{k} {n}" for k, n in Counter(r for v in vs for r in v.get('reasons') or []).most_common(12)))
    if not rows:
        return 1
    names = list(rows[0][1])
    print(f"\nunits {len(rows)}, taken {sum(r[2] for r in rows)}, starts {sum(r[3] for r in rows)}\n")
    print(f"{'feature':18} {'AUC taken':>10} {'AUC start':>10}   mean in start / others")
    res = []
    for n in names:
        xs = [r[1][n] for r in rows]
        at, as_ = auc(xs, [r[2] for r in rows]), auc(xs, [r[3] for r in rows])
        ms = sum(x for x, r in zip(xs, rows) if r[3]) / max(1, sum(r[3] for r in rows))
        mo = sum(x for x, r in zip(xs, rows) if not r[3]) / max(1, sum(1 - r[3] for r in rows))
        res.append((n, at, as_, ms, mo))
    for n, at, as_, ms, mo in sorted(res, key=lambda t: -abs((t[2] or 0.5) - 0.5)):
        f = lambda v: "   —" if v is None else f"{v:.2f}"
        print(f"{n:18} {f(at):>10} {f(as_):>10}   {ms:.2f} / {mo:.2f}")
    # leave-one-source-out logistic regression on standardized features
    stems = sorted({r[0] for r in rows})
    mu = {n: sum(r[1][n] for r in rows) / len(rows) for n in names}
    sd = {n: (sum((r[1][n] - mu[n]) ** 2 for r in rows) / len(rows)) ** 0.5 or 1.0 for n in names}
    X = [[(r[1][n] - mu[n]) / sd[n] for n in names] for r in rows]
    for li, label in ((2, "taken"), (3, "start")):
        y = [r[li] for r in rows]
        scores, ys = [], []
        for s in stems:
            tr = [i for i, r in enumerate(rows) if r[0] != s]
            te = [i for i, r in enumerate(rows) if r[0] == s]
            if not any(y[i] for i in tr):
                continue
            w = logreg([X[i] for i in tr], [y[i] for i in tr])
            for i in te:
                scores.append(w[-1] + sum(a * b for a, b in zip(w, X[i]))); ys.append(y[i])
        a = auc(scores, ys)
        print(f"\nleave-one-source-out logistic, label {label}: AUC {a:.2f}" if a is not None else f"\n{label}: no AUC")
        w = logreg(X, y)
        top = sorted(zip(names, w), key=lambda t: -abs(t[1]))[:8]
        print("  strongest weights (all data): " + ", ".join(f"{n} {v:+.2f}" for n, v in top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
