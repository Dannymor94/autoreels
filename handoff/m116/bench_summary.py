#!/usr/bin/env python3
"""M116 (замер, ничего не пишет): одни и те же суждения (начало клипа, тизер) разными моделями.

    .venv/bin/python handoff/m116/bench_summary.py handoff/m116/judge_cloud.jsonl handoff/m116/bench_*.jsonl

Первый файл — журнал прогона (arl autocut --judge-log, модель Groq), остальные — arl judge-bench других моделей на
тех же запросах. Печатает по каждому виду суждения: сколько ответов, доля «да», секунд на запрос; попарное совпадение
моделей (на запросах, где ответили обе); и примеры, где модели расходятся — их стоит прочитать глазами.
"""
from __future__ import annotations

import json
import sys
from itertools import combinations
from pathlib import Path


def load(path: Path) -> tuple[str, dict]:
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    res: dict = {}
    name = path.stem.replace("bench_", "").replace("judge_", "")
    for r in rows:
        key = (r.get("label"), r.get("msg"))
        if key in res and not res[key].get("cached", False):
            continue
        res[key] = {"ok": r.get("ok"), "why": r.get("why"), "sec": r.get("sec"), "cached": r.get("cached", False)}
    return name, res


def main() -> int:
    files = [Path(a) for a in sys.argv[1:]]
    models = [load(f) for f in files if f.is_file()]
    if len(models) < 2:
        print("нужно не меньше двух файлов")
        return 1
    labels = sorted({k[0] for _, res in models for k in res})
    for lab in labels:
        print(f"\n=== {lab}")
        for name, res in models:
            ks = [k for k in res if k[0] == lab]
            ans = [res[k] for k in ks if res[k]["ok"] is not None]
            secs = [res[k]["sec"] for k in ks if isinstance(res[k].get("sec"), (int, float))]
            print(f"   {name:12} ответов {len(ans)}/{len(ks)}, «да» {100 * sum(a['ok'] for a in ans) / max(1, len(ans)):.0f}%"
                  + (f", {sum(secs) / len(secs):.1f} с на запрос" if secs else ""))
        print("   совпадение (на запросах, где ответили обе):")
        for (n1, r1), (n2, r2) in combinations(models, 2):
            common = [k for k in r1 if k[0] == lab and k in r2 and r1[k]["ok"] is not None and r2[k]["ok"] is not None]
            same = sum(r1[k]["ok"] == r2[k]["ok"] for k in common)
            print(f"     {n1} ↔ {n2}: {same}/{len(common)}" + (f" ({100 * same / len(common):.0f}%)" if common else ""))
        keys = [k for k in models[0][1] if k[0] == lab]
        diff = [k for k in keys if len({m[1][k]["ok"] for m in models if k in m[1] and m[1][k]["ok"] is not None}) > 1]
        print(f"   расходятся: {len(diff)} из {len(keys)}; примеры (✓ — годится, ✗ — нет, причина модели):")
        for k in diff[:12]:
            first = k[1].split("\n")[0][:150]
            print(f"     {first}")
            for name, res in models:
                v = res.get(k)
                if v and v["ok"] is not None:
                    print(f"         {name:12} {'✓' if v['ok'] else '✗'} {v['why'] or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
