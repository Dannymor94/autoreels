#!/usr/bin/env python3
"""M139 (замер, ничего не пишет): решения владельца с листа ревью (reviews/verdicts.jsonl, arl review-apply) —
хватит ли их, чтобы учить вкус и чинить «переделать» автоматически.

Печатает: сколько строк и по каким источникам и гейтам; решения; причины (одним касанием) и свободные заметки;
для монтажных строк (M…) — мысли карты по фразам строки, средняя сила мысли и «вкус» (config/taste.json) по
каждому решению, и AUC вкуса и силы «это решение против остальных».
    .venv/bin/python handoff/m139/verdicts.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


def expand(field: str) -> list[str]:
    out = []
    for piece in field.split():
        m = re.fullmatch(r"(\w+)\.(\d+)(?:-(\d+))?", piece)
        if m:
            out += [f"{m.group(1)}.{k}" for k in range(int(m.group(2)), int(m.group(3) or m.group(2)) + 1)]
    return out


def auc(xs, ys):
    pos = [x for x, y in zip(xs, ys) if y]
    neg = [x for x, y in zip(xs, ys) if not y]
    if not pos or not neg:
        return None
    return sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg) / (len(pos) * len(neg))


def main() -> int:
    vp = Path("reviews/verdicts.jsonl")
    if not vp.is_file():
        print("reviews/verdicts.jsonl нет — решений с листа не записано")
        return 0
    rows = []
    for ln in vp.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(ln))
        except ValueError:
            continue
    print(f"строк: {len(rows)}")
    print("по виду: " + ", ".join(f"{k} {n}" for k, n in Counter(r.get("kind") for r in rows).items()))
    print("решения: " + ", ".join(f"{k} {n}" for k, n in Counter(r.get("verdict") for r in rows).most_common()))
    print("по источнику / гейту:")
    for (s, g), n in Counter((r.get("stem"), r.get("gate")) for r in rows).most_common():
        print(f"  {s} / {g or '—'}: {n}")
    print("даты: " + ", ".join(sorted({str(r.get('date'))[:10] for r in rows})))
    rc = Counter(x for r in rows for x in r.get("reasons") or [])
    print("причины: " + (", ".join(f"«{k}» {n}" for k, n in rc.most_common(25)) or "нет"))
    by_v = defaultdict(Counter)
    for r in rows:
        for x in r.get("reasons") or []:
            by_v[r.get("verdict")][x] += 1
    for v, c in by_v.items():
        print(f"  {v}: " + ", ".join(f"«{k}» {n}" for k, n in c.most_common(10)))
    notes = [r for r in rows if (r.get("note") or "").strip()]
    print(f"свободных заметок: {len(notes)}")
    for r in notes[:30]:
        print(f"  [{r.get('verdict')}] {r.get('stem')} {r.get('ref')}: {r.get('note')[:120]}")

    model = None
    tp = Path("config/taste.json")
    if tp.is_file():
        sys.path.insert(0, "src")
        from autoreels.cloud.taste import clip_taste, load
        model = load(tp)
    mrows = []
    maps = {}
    for r in rows:
        if r.get("kind") != "montage" or " | " not in (r.get("line") or ""):
            continue
        stem = r.get("stem") or ""
        if stem not in maps:
            mj = Path("transcripts") / f"{stem}.map.json"
            maps[stem] = json.loads(mj.read_text(encoding="utf-8")).get("units") if mj.is_file() else None
        units = maps[stem]
        if not units:
            continue
        by_ref = {}
        for u in units:
            for x in expand(u.get("refs") or ""):
                by_ref.setdefault(x, u)
        refs = expand(r["line"].split(" | ")[1])
        clip = list({id(by_ref[x]): by_ref[x] for x in refs if x in by_ref}.values())
        if not clip:
            continue
        src_dur = max(float(u["t1"]) for u in units)
        punch = sum(int(u.get("punch") or 0) for u in clip) / len(clip)
        taste = clip_taste(clip, model, src_dur) if model else None
        mrows.append((r.get("verdict"), punch, taste))
    print(f"\nмонтажных строк с мыслями карты: {len(mrows)}")
    for v in sorted({m[0] for m in mrows}, key=str):
        sel = [m for m in mrows if m[0] == v]
        line = f"  {v}: {len(sel)}, сила {sum(m[1] for m in sel) / len(sel):.2f}"
        if model:
            line += f", вкус {sum(m[2] for m in sel) / len(sel):+.2f}"
        ys = [int(m[0] == v) for m in mrows]
        a_p = auc([m[1] for m in mrows], ys)
        a_t = auc([m[2] for m in mrows], ys) if model else None
        line += f"; AUC против остальных: сила {a_p if a_p is None else round(a_p, 2)}, вкус {a_t if a_t is None else round(a_t, 2)}"
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
