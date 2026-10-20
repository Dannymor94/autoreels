#!/usr/bin/env python3
"""M119 (замер, ничего не пишет): черновики arl autocut против клипов владельца.

    .venv/bin/python handoff/m119/owner_drafts.py m116-haiku m119-montage m119-passage

Для каждого источника с ручным выбором (manifests/<источник>.json, selection_source: human) и каждого тега — черновик
reviews/<источник>_auto_<тег>.txt: сколько сборок принято, у скольких начало под сомнением модели (M119 rank: «модель
против»), сколько без холодного старта, средняя длина; сколько клипов владельца покрыто (одна сборка покрывает не
меньше половины его времени; время мысли — t0..t1 в карте transcripts/<источник>.map.json) и какая доля времени
сборок лежит внутри клипов владельца. Нет черновика — прочерк.
"""
from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path


def accepted(draft: Path) -> list[dict]:
    """Accepted clips of a draft: thoughts (#id lines), notes, the line itself."""
    out, cur = [], None
    for ln in draft.read_text(encoding="utf-8").splitlines():
        if ln.startswith("# --- M"):
            cur = {"ids": [], "notes": [], "line": ""}
            out.append(cur)
        elif ln.startswith("# --- "):
            cur = None
        elif cur is not None:
            m = re.match(r"^#   #(\d+) ", ln)
            if m:
                cur["ids"].append(int(m.group(1)))
            elif ln.startswith("#   "):
                cur["notes"].append(ln[4:])
            elif re.match(r"^M\d+ ", ln):
                cur["line"] = ln
    return [c for c in out if c["ids"] and c["line"]]


def ov(a, b) -> float:
    return sum(max(0.0, min(a1, b1) - max(a0, b0)) for a0, a1 in a for b0, b1 in b)


def main() -> int:
    tags = sys.argv[1:]
    if not tags:
        print(__doc__)
        return 2
    tot = {t: [0, 0, 0, 0, 0.0, 0.0, 0] for t in tags}   # accepted, doubt, hookless, covered, inside, secs, owner
    for mp in sorted(glob.glob("manifests/*.json")):
        try:
            m = json.load(open(mp, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(m, dict) or m.get("selection_source") != "human":
            continue
        stem = Path(mp).stem
        mjson = Path("transcripts") / f"{stem}.map.json"
        if not mjson.is_file():
            continue
        by_id = {u["id"]: u for u in json.loads(mjson.read_text(encoding="utf-8")).get("units") or []}
        owner = [[(float(s["start"]), float(s["end"])) for s in (r.get("segments") or [])]
                 or [(float(r["start"]), float(r["end"]))] for r in m.get("reels") or []]
        owner_all = [s for o in owner for s in o]
        rows = []
        for tag in tags:
            d = Path("reviews") / f"{stem}_auto_{tag}.txt"
            if not d.is_file():
                rows.append(f"   {tag:16} —")
                continue
            acc = accepted(d)
            sp = [[(float(by_id[i]["t0"]), float(by_id[i]["t1"])) for i in c["ids"] if i in by_id] for c in acc]
            covered = sum(1 for o in owner if max((ov(o, s) for s in sp), default=0.0) >= 0.5 * sum(b - a for a, b in o))
            secs = sum(sum(b - a for a, b in s) for s in sp)
            inside = sum(ov(s, owner_all) for s in sp)
            doubt = sum(1 for c in acc if any("модель против" in n for n in c["notes"]))
            hookless = sum(1 for c in acc if " | h:" not in c["line"])
            t = tot[tag]
            t[0] += len(acc); t[1] += doubt; t[2] += hookless; t[3] += covered; t[4] += inside; t[5] += secs
            t[6] += len(owner)
            rows.append(f"   {tag:16} сборок {len(acc):2d} (начало под сомнением {doubt}, без крючка {hookless}), "
                        f"средняя {secs / max(1, len(acc)):3.0f} с; клипов владельца покрыто {covered:2d}/{len(owner)}, "
                        f"внутри его клипов {100 * inside / max(1e-9, secs):3.0f}%")
        if any("сборок" in r for r in rows):
            print(f"\n=== {stem} (клипов владельца {len(owner)})")
            print("\n".join(rows))
    print("\n=== ВСЕГО (только источники, где есть черновик тега)")
    for tag, (n, doubt, hl, cov, ins, secs, own) in tot.items():
        print(f"   {tag:16} сборок {n:3d} (под сомнением {doubt}, без крючка {hl}); клипов владельца покрыто {cov}/{own}; "
              f"внутри {100 * ins / max(1e-9, secs):3.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
