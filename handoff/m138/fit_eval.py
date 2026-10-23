#!/usr/bin/env python3
"""M138: fit the owner's taste model (cloud/taste.py) on his clips.

Writes config/taste.json (all sources; provenance inside) and data/cache/m138/taste_wo_<stem>.json — one model per
source fitted WITHOUT it (for the leave-one-source-out autocut runs). Prints the held-out AUC of both heads.
    .venv/bin/python handoff/m138/fit_eval.py
"""
from __future__ import annotations

import datetime
import glob
import json
import sys
from pathlib import Path

from autoreels.cloud.taste import features, fit, logit, owner_rows  # noqa: F401


def auc(xs, ys):
    pos = [x for x, y in zip(xs, ys) if y]
    neg = [x for x, y in zip(xs, ys) if not y]
    if not pos or not neg:
        return None
    return sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg) / (len(pos) * len(neg))


def main() -> int:
    by_stem = {}
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
        rows = owner_rows(m, units)
        if rows:
            by_stem[stem] = rows
            print(f"{stem}: thoughts {len(rows)}, taken {sum(r[1] for r in rows)}, starts {sum(r[2] for r in rows)}")
    if len(by_stem) < 2:
        print("too few sources")
        return 1
    out = Path("data/cache/m138")
    out.mkdir(parents=True, exist_ok=True)
    held = {"taken": ([], []), "start": ([], [])}
    for stem in by_stem:
        train = [r for s, rs in by_stem.items() if s != stem for r in rs]
        mdl = fit(train, provenance=f"m138 leave-one-out: all owner clips except {stem}")
        (out / f"taste_wo_{stem}.json").write_text(json.dumps(mdl, ensure_ascii=False, indent=1), encoding="utf-8")
        for head, i in (("taken", 1), ("start", 2)):
            for r in by_stem[stem]:
                held[head][0].append(logit(mdl, r[0], head))
                held[head][1].append(r[i])
    for head, (xs, ys) in held.items():
        print(f"held-out AUC {head}: {auc(xs, ys):.2f}")
    allrows = [r for rs in by_stem.values() for r in rs]
    n_clips = sum(1 for rs in by_stem.values() for r in rs if r[2])
    mdl = fit(allrows, provenance=(f"m138 {datetime.date.today()}: the owner's clips (manifests selection_source human) "
                                   f"of {len(by_stem)} sources — {', '.join(by_stem)}; {len(allrows)} thoughts, "
                                   f"{n_clips} clip starts"))
    Path("config/taste.json").write_text(json.dumps(mdl, ensure_ascii=False, indent=1), encoding="utf-8")
    top = sorted(zip(mdl["features"], mdl["heads"]["start"]["w"]), key=lambda t: -abs(t[1]))[:6]
    print("config/taste.json written; start head strongest: " + ", ".join(f"{k} {w:+.2f}" for k, w in top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
