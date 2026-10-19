#!/usr/bin/env python3
"""M116 (замер, ничего не пишет): сборки одних и тех же источников разными моделями — по черновикам
reviews/<источник>_auto_m116-<модель>.txt и логам handoff/m116/run_<модель>.txt.

    .venv/bin/python handoff/m116/compare_models.py <модель> [<модель> …]      (например: cloud haiku sonnet)

По каждому источнику и модели: сборок, с тизером, без понятного начала, не прошли проверку, похожи, конец «→»;
плашки t: и ключевые слова k:. По логу: сколько первых фраз модель признала непонятными, сколько тизеров отбросила,
цена (для Claude) и время.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SOURCES = ("IMG_6848", "2026-08-08 11h 42m 49s", "Pxl 20260621 112938952")
SECTIONS = {
    "начало ссылается на вырезанное": "без начала",
    "не прошли проверку": "не прошли",
    "слишком похожи на принятые": "похожи",
    "конец звучит с продолжением": "конец «→»",
    "без холодного старта — не взяты": "без крючка не взяты",
}


def draft(path: Path) -> dict:
    out = {"clips": [], **{v: 0 for v in SECTIONS.values()}}
    if not path.is_file():
        return {}
    cur = None
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.startswith("# --- "):
            cur = next((v for k, v in SECTIONS.items() if k in ln), None)
            continue
        if cur and (ln.startswith("#   ") and cur in ("без начала", "похожи", "конец «→»")
                    or ln.startswith("#! ") and cur in ("не прошли", "без крючка не взяты")):
            out[cur] += 1
            continue
        if re.match(r"M\d+ ", ln):
            f = {p.split(":", 1)[0]: p.split(":", 1)[1].strip() for p in ln.split(" | ")[1:] if re.match(r"^[a-z]:", p)}
            out["clips"].append({"line": ln.split(" | ")[0], "hook": "h" in f, "t": f.get("t", "—"),
                                 "k": f.get("k", "")})
    return out


def log_facts(path: Path, src: str) -> dict:
    facts = {}
    if not path.is_file():
        return facts
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = text.split("=== ")
    for b in blocks:
        if not b.startswith(src):
            continue
        m = re.search(r"начало: модель оценила (\d+) первых фраз, непонятных без предыдущего (\d+)", b)
        if m:
            facts["начала"] = f"{m.group(2)} из {m.group(1)} непонятны"
        m = re.search(r"крючки: модель оценила (\d+), отброшено (\d+)", b)
        if m:
            facts["крючки"] = f"отброшено {m.group(2)} из {m.group(1)}"
        m = re.search(r"Claude \S+: запросов (\d+).*?≈ \$([0-9.]+)", b)
        if m:
            facts["цена"] = f"${m.group(2)} ({m.group(1)} запросов)"
        m = re.search(r"^real\s+(\S+)", b, re.M) or re.search(r"(\d+(?:\.\d+)?) real", b)
        if m:
            facts["время"] = m.group(1)
    return facts


def main() -> int:
    models = sys.argv[1:] or ["cloud", "haiku", "sonnet"]
    for src in SOURCES:
        print(f"\n=== {src}")
        print(f"   {'модель':12} {'сборок':>6} {'с тизером':>9} {'без начала':>10} {'не прошли':>9} {'похожи':>6} "
              f"{'конец →':>7}   по логу")
        rows = {}
        for m in models:
            d = draft(Path("reviews") / f"{src}_auto_m116-{m}.txt")
            rows[m] = d
            if not d:
                print(f"   {m:12} (нет черновика)")
                continue
            lf = log_facts(Path("handoff/m116") / f"run_{m}.txt", src)
            print(f"   {m:12} {len(d['clips']):6d} {sum(c['hook'] for c in d['clips']):9d} {d['без начала']:10d} "
                  f"{d['не прошли']:9d} {d['похожи']:6d} {d['конец «→»']:7d}   "
                  + "; ".join(f"{k}: {v}" for k, v in lf.items()))
        for m in models:
            d = rows.get(m) or {}
            if d.get("clips"):
                print(f"   — {m}:")
                for c in d["clips"]:
                    print(f"       {c['line']:4} {'h' if c['hook'] else ' '} t: {c['t'][:60]}" + (f"   k: {c['k']}" if c["k"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
