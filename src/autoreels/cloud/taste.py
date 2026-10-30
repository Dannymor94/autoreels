"""M138: the owner's taste as a score of map thoughts — learned from his own clips, used only to ORDER (invariant 1).

m137 (7 sources, 66 owner clips, 799 thoughts): the owner starts a clip on a longer finished thought (AUC 0.71), takes
thoughts the map calls strong (punch, 0.65–0.67), from the first half of a talk, said louder; the «viral» hook
features (a number, a question, «вы», a contrast) carry nothing (≈ 0.50). Leave-one-source-out logistic regression:
start 0.65, taken 0.59 — a weak but real signal.

A model is two logistic heads over standardized features of a thought:
  taken — the thought lies in an owner clip;  start — an owner clip starts on it.
`fit(rows)` builds it from (features, taken, start) rows; config/taste.json holds the model fitted on all the owner's
clips (with its provenance). autocut adds `taste_weight × clip_taste(clip)` to a proposal's score (taste_weight 0 =
off: the score and the order are as before).
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Sequence

VERSION = 1
HEDGE = ("наверное", "может быть", "мне кажется", "как бы", "в принципе", "типа", "вроде", "кажется", "возможно")
FILLER = ("ну", "вот", "так", "значит", "короче", "э", "эм")
BACKREF = ("это", "этот", "эта", "эти", "он", "она", "они", "оно", "но", "и", "а", "поэтому", "тогда",
           "там", "тут", "здесь", "его", "её", "их", "то")
ROLES = ("question", "thesis", "explanation", "example", "metaphor", "conclusion", "address", "aside")


def _norm(t: str) -> str:
    return re.sub(r"[^\w\s-]", " ", t.lower().replace("ё", "е")).strip()


def features(u: dict, src_dur: float) -> dict[str, float]:
    """Features of one map thought (transcripts/<stem>.map.json unit); `src_dur` — the source's length (max t1)."""
    v = u.get("voice") or {}
    words = str(u.get("text") or "").split()
    fw = _norm(" ".join(words[:10])).split()
    f = {
        "punch": float(u.get("punch") or 0),
        "standalone": float(bool(u.get("standalone"))),
        "refers": float(u.get("refers") is not None),
        "energy": float(v.get("energy") or 0),
        "level_db": float(v.get("level_db") if v.get("level_db") is not None else -90.0),
        "rate": float(v.get("rate") or 0),
        "dur": float(u["t1"]) - float(u["t0"]),
        "pos": float(u["t0"]) / max(1.0, src_dur),
        "filtered": float(bool(u.get("filtered"))),
        "h_words_to_stop": float(next((i + 1 for i, w in enumerate(words) if w.endswith((".", "?", "!"))), len(words))),
        "h_name": float(any(w[:1].isupper() for w in words[1:10] if w[:1].isalpha())),
        "h_backref_first": float(bool(fw) and fw[0] in BACKREF),
        "h_filler_first": float(bool(fw) and fw[0] in FILLER),
        "h_hedge": float(any(h in " ".join(fw) for h in HEDGE)),
    }
    for r in ROLES:
        f[f"role_{r}"] = float(u.get("role") == r)
    return f


def _logreg(X: list[list[float]], y: list[int], l2: float = 1.0, it: int = 400, lr: float = 0.1) -> list[float]:
    d = len(X[0])
    w = [0.0] * (d + 1)
    n = len(X)
    for _ in range(it):
        g = [0.0] * (d + 1)
        for xi, yi in zip(X, y):
            z = w[-1] + sum(a * b for a, b in zip(w, xi))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            for k in range(d):
                g[k] += (p - yi) * xi[k]
            g[-1] += p - yi
        for k in range(d):
            w[k] -= lr * (g[k] / n + l2 * w[k] / n)
        w[-1] -= lr * g[-1] / n
    return w


def fit(rows: Sequence[tuple[dict, int, int]], provenance: str = "") -> dict:
    """rows: (features, taken, start). Returns the model (JSON-ready)."""
    if not rows:
        raise ValueError("no rows to fit the taste model on")
    names = sorted(rows[0][0])
    n = len(rows)
    mu = {k: sum(r[0][k] for r in rows) / n for k in names}
    sd = {k: (sum((r[0][k] - mu[k]) ** 2 for r in rows) / n) ** 0.5 or 1.0 for k in names}
    X = [[(r[0][k] - mu[k]) / sd[k] for k in names] for r in rows]
    heads = {}
    for i, head in ((1, "taken"), (2, "start")):
        y = [int(r[i]) for r in rows]
        if not any(y) or all(y):
            raise ValueError(f"taste head «{head}»: every row has the same label")
        w = _logreg(X, y)
        heads[head] = {"w": [round(x, 6) for x in w[:-1]], "b": round(w[-1], 6)}
    return {"version": VERSION, "features": names, "mu": mu, "sd": sd, "heads": heads,
            "rows": n, "provenance": provenance}


def load(path: str | Path) -> dict:
    m = json.loads(Path(path).read_text(encoding="utf-8"))
    if m.get("version") != VERSION:
        raise ValueError(f"{path}: taste model version {m.get('version')} ≠ {VERSION}")
    return m


def logit(model: dict, f: dict[str, float], head: str) -> float:
    h = model["heads"][head]
    return h["b"] + sum(w * (f.get(k, model["mu"][k]) - model["mu"][k]) / model["sd"][k]
                        for w, k in zip(h["w"], model["features"]))


def clip_taste(clip: Sequence[dict], model: dict, src_dur: float) -> float:
    """Half the mean «taken» logit of the clip's thoughts + half the «start» logit of its first thought."""
    if not clip:
        return 0.0
    taken = sum(logit(model, features(u, src_dur), "taken") for u in clip) / len(clip)
    return 0.5 * taken + 0.5 * logit(model, features(clip[0], src_dur), "start")


def owner_rows(manifest: dict, units: Sequence[dict]) -> list[tuple[dict, int, int]]:
    """(features, taken, start) of every thought of a source with owner clips (manifest selection_source human):
    taken — ≥ 50 % of the thought lies in an owner clip; start — an owner clip starts inside it (± 1 s)."""
    if not units:
        return []
    src_dur = max(float(u["t1"]) for u in units)
    clips = [[(float(s["start"]), float(s["end"])) for s in (r.get("segments") or [])]
             or [(float(r["start"]), float(r["end"]))] for r in manifest.get("reels") or []]
    starts = [min(a for a, _ in c) for c in clips if c]
    spans = [s for c in clips for s in c]
    out = []
    for u in units:
        a, b = float(u["t0"]), float(u["t1"])
        ins = sum(max(0.0, min(b, s1) - max(a, s0)) for s0, s1 in spans)
        out.append((features(u, src_dur), int(ins >= 0.5 * (b - a)),
                    int(any(a - 1.0 <= s <= b + 1.0 and s < b - 0.5 for s in starts))))
    return out
