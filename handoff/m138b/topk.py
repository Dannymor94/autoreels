#!/usr/bin/env python3
"""M138b (замер, ничего не пишет): вкус меняет ПОРЯДОК черновика, а не набор — в m138 пул был меньше потолка
(clips_every_min 2), поэтому в черновик попадали все кандидаты, и покрытие по всему черновику совпало у всех тегов.
Владелец оставляет примерно один клип на 3.5 мин, то есть смотрит на верх листа. Здесь считается, сколько его клипов
накрывают первые k сборок черновика (в порядке файла), при k = число его клипов и k = минуты/3.5, и сколько из первых
k сборок попадают в его клипы (≥ 50 % времени сборки внутри). Плюс: есть ли в черновике заметки «вкус владельца».
    .venv/bin/python handoff/m138b/topk.py m138-off m138-w10 m138-w20
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "m138"))
from owner_drafts import accepted, expand, ov  # noqa: E402


def main() -> int:
    tags = sys.argv[1:]
    tot = {t: {"own": [0, 0, 0], "cov_n": 0, "cov_m": 0, "hit_n": 0, "hit_m": 0, "k_n": 0, "k_m": 0, "taste": 0} for t in tags}
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
            continue
        units = json.loads(mj.read_text(encoding="utf-8")).get("units") or []
        by_id = {u["id"]: u for u in units}
        by_ref = {}
        for u in units:
            for r in expand(u.get("refs") or ""):
                by_ref.setdefault(r, u["id"])
        owner = [[(float(s["start"]), float(s["end"])) for s in (r.get("segments") or [])]
                 or [(float(r["start"]), float(r["end"]))] for r in m.get("reels") or []]
        owner_all = [s for o in owner for s in o]
        src_min = max((float(u["t1"]) for u in units), default=0.0) / 60.0
        k_n, k_m = len(owner), max(1, round(src_min / 3.5))
        print(f"\n=== {stem}: owner clips {len(owner)}, k = {k_n} (his count) / {k_m} (min ÷ 3.5)")
        for tag in tags:
            d = Path("reviews") / f"{stem}_auto_{tag}.txt"
            if not d.is_file():
                print(f"   {tag:10} —")
                continue
            acc = accepted(d)
            text = d.read_text(encoding="utf-8")
            sp = [[(float(by_id[i]["t0"]), float(by_id[i]["t1"])) for i in c["ids"] if i in by_id] for c in acc]

            def cover(k):
                top = sp[:k]
                return sum(1 for o in owner if max((ov(o, s) for s in top), default=0.0) >= 0.5 * sum(b - a for a, b in o))

            def hits(k):
                return sum(1 for s in sp[:k] if sum(b - a for a, b in s) and ov(s, owner_all) >= 0.5 * sum(b - a for a, b in s))
            t = tot[tag]
            t["cov_n"] += cover(k_n); t["cov_m"] += cover(k_m); t["hit_n"] += hits(k_n); t["hit_m"] += hits(k_m)
            t["k_n"] += min(k_n, len(sp)); t["k_m"] += min(k_m, len(sp)); t["own"][0] += len(owner)
            t["taste"] += text.count("вкус владельца")
            print(f"   {tag:10} сборок {len(sp):2d}; первые {k_n}: покрыто {cover(k_n)}/{len(owner)}, в его клипах {hits(k_n)}; "
                  f"первые {k_m}: покрыто {cover(k_m)}/{len(owner)}, в его клипах {hits(k_m)}; заметок «вкус» {text.count('вкус владельца')}")
    print("\n=== ВСЕГО")
    for tag, t in tot.items():
        print(f"   {tag:10} k=его число: покрыто {t['cov_n']}/{t['own'][0]}, сборок в его клипах {t['hit_n']}/{t['k_n']}; "
              f"k=мин÷3.5: покрыто {t['cov_m']}/{t['own'][0]}, в его клипах {t['hit_m']}/{t['k_m']}; заметок «вкус» {t['taste']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
