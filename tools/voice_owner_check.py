"""M211: does the voice tell the thoughts the owner put in his clips from the rest?

For each source: the map's thoughts (transcripts/<source>.map.json, voice measured by local/voice.py) and the owner's
clips (manifests/<source>.json, selection_source human — the body segments). A thought is the owner's when at least half
of its time is inside an owner clip's body. For every measure — level, pitch, pitch range, rate, energy, and the model's
strength (punch) for comparison — the AUC of «owner's» against «the rest»: 0.5 = no signal, 1.0 = the owner's are always
higher, 0.0 = always lower. The measures are compared within each source (rank-based, so a loud recording does not
weigh more). Read only.
Run from the project root: .venv/bin/python tools/voice_owner_check.py"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ("disko_beach_p1", "disko_beach_p2", "disko_beach_p3", "day_yoga_p1", "day_yoga_p2",
           "prew_isaev_anna", "prew_isaev_danny")
FEATURES = (("level_db", "громкость"), ("pitch_st", "тон"), ("range_st", "размах тона"), ("rate", "темп"),
            ("energy", "энергия"), ("punch", "сила (модель)"))


def auc(pos: list[float], neg: list[float]) -> float | None:
    """Mann–Whitney: the chance a random owner's thought is above a random other one (ties count half)."""
    if not pos or not neg:
        return None
    above = sum((1.0 if p > q else 0.5 if p == q else 0.0) for p in pos for q in neg)
    return above / (len(pos) * len(neg))


def owner_body(manifest: dict) -> list[tuple[float, float]] | None:
    if manifest.get("selection_source") != "human":
        return None
    out = []
    for r in manifest.get("reels") or []:
        segs = r.get("segments") or [{"start": r["start"], "end": r["end"]}]
        out += [(float(s["start"]), float(s["end"])) for s in segs]
    return out


def value(u: dict, key: str):
    if key == "punch":
        return u.get("punch")
    return (u.get("voice") or {}).get(key)


def main(argv=None) -> int:
    stems = list(argv if argv is not None else sys.argv[1:]) or list(SOURCES)
    pooled = {k: ([], []) for k, _ in FEATURES}
    print(f"{'источник':18} {'мыслей':>6} {'у владельца':>11} " + " ".join(f"{name:>13}" for _, name in FEATURES))
    for stem in stems:
        mp, mf = ROOT / "transcripts" / f"{stem}.map.json", ROOT / "manifests" / f"{stem}.json"
        if not mp.is_file() or not mf.is_file():
            print(f"{stem:18} нет карты или манифеста")
            continue
        body = owner_body(json.loads(mf.read_text(encoding="utf-8")))
        if body is None:
            print(f"{stem:18} нет ручной разметки владельца")
            continue
        units = json.loads(mp.read_text(encoding="utf-8")).get("units") or []
        mine = []
        for u in units:
            t0, t1 = float(u["t0"]), float(u["t1"])
            inside = sum(max(0.0, min(t1, b) - max(t0, a)) for a, b in body)
            mine.append(t1 > t0 and inside >= 0.5 * (t1 - t0))
        cells = []
        for key, _ in FEATURES:
            vals = [(value(u, key), m) for u, m in zip(units, mine) if value(u, key) is not None]
            order = sorted(range(len(vals)), key=lambda i: vals[i][0])
            ranks = [0.0] * len(vals)
            for r, i in enumerate(order):                      # within-source rank 0..1
                ranks[i] = r / max(1, len(vals) - 1)
            pos = [ranks[i] for i, (_, m) in enumerate(vals) if m]
            neg = [ranks[i] for i, (_, m) in enumerate(vals) if not m]
            pooled[key][0].extend(pos)
            pooled[key][1].extend(neg)
            a = auc(pos, neg)
            cells.append(f"{a:13.2f}" if a is not None else f"{'—':>13}")
        print(f"{stem:18} {len(units):6} {sum(mine):11} " + " ".join(cells))
    cells = []
    for key, _ in FEATURES:
        a = auc(*pooled[key])
        cells.append(f"{a:13.2f}" if a is not None else f"{'—':>13}")
    n_pos = len(pooled["energy"][0])
    print(f"{'ВСЕ':18} {'':6} {n_pos:11} " + " ".join(cells))
    print("\nAUC: 0.50 — не отличает; ≥ 0.60 или ≤ 0.40 — сигнал (≤ 0.40: у клипов владельца ниже).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
