#!/usr/bin/env python3
"""M192, часть B (ничего не пишет): оценки владельца по гейту ab192 → итог по сторонам A (эталон) и B (m183).

    .venv/bin/python handoff/m192/ab_score.py      # из корня проекта, после arl review-apply всех файлов решений

Строки reviews/verdicts.jsonl с gate == "ab192", kind == "montage" сопоставляются с handoff/m192/key.csv
по (stem, метка M<n>). Последняя оценка клипа главнее прежней (так пишет review-apply).
"""
from __future__ import annotations

import collections
import csv
import json
import sys
from pathlib import Path

ROOT = Path.cwd()


def main() -> int:
    key = {}
    with open(ROOT / "handoff" / "m192" / "key.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            key[(r["stem"], r["label"])] = r
    vp = ROOT / "reviews" / "verdicts.jsonl"
    rows = [json.loads(l) for l in vp.read_text(encoding="utf-8").splitlines() if l.strip()] if vp.is_file() else []
    rows = [r for r in rows if r.get("gate") == "ab192" and r.get("kind") == "montage"]
    last = {}
    for r in rows:
        last[(r.get("stem"), str(r.get("ref")))] = r
    by_side = {"ref191": collections.Counter(), "m183": collections.Counter()}
    reasons = {"ref191": collections.Counter(), "m183": collections.Counter()}
    detail = []
    unmatched = 0
    for k, r in sorted(last.items()):
        kr = key.get(k)
        if kr is None:
            unmatched += 1
            continue
        side = kr["origin"]
        by_side[side][r.get("verdict")] += 1
        reasons[side].update(r.get("reasons") or [])
        detail.append(f"  {k[0]:18} {k[1]:4} {side:6} {r.get('verdict'):5} {', '.join(r.get('reasons') or [])}"
                      f"{' | ' + r['note'] if r.get('note') else ''}")
    print(f"оценок ab192: {len(last)} из {len(key)} клипов; без ключа: {unmatched}")
    for side, name in (("ref191", "A эталон ассистента"), ("m183", "B автоматика m183")):
        c = by_side[side]
        n = sum(c.values())
        keep = c.get("ok", 0)
        print(f"{name}: оценено {n}; оставить {keep}" + (f" ({100 * keep / n:.0f}%)" if n else "")
              + f"; все решения: {dict(c)}; причины: {dict(reasons[side].most_common())}")
    print("по клипам:")
    print("\n".join(detail))
    return 0


if __name__ == "__main__":
    sys.exit(main())
