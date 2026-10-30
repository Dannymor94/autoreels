#!/usr/bin/env python3
"""M193 (замер, ничего не пишет): черновики сценариста без правила и с правилом answer_start.

    .venv/bin/python handoff/m193/drafts_diff.py      # из корня проекта

Для каждого источника: handoff/m193/<stem>_off.txt и <stem>_on.txt (arl autocut --scenario … --out).
Печатает: строк M в каждом; строки, которые есть только в одном (без метки M<n>); строки черновика «on»,
где упомянут ответ (новое правило) — заметки над строками и список непринятых.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path.cwd()
D = ROOT / "handoff" / "m193"
STEMS = ["prew_isaev_anna", "prew_isaev_danny", "day_yoga_p1", "day_yoga_p2",
         "disko_beach_p1", "disko_beach_p2", "disko_beach_p3"]


def mlines(text: str) -> list[str]:
    return [re.sub(r"^M\d*\s+", "M ", ln.strip()) for ln in text.splitlines() if re.match(r"^M\d*\s", ln.strip())]


def main() -> int:
    tot_off = tot_on = tot_ans = 0
    for s in STEMS:
        off, on = D / f"{s}_off.txt", D / f"{s}_on.txt"
        if not (off.is_file() and on.is_file()):
            print(f"== {s}: нет {off.name if not off.is_file() else on.name}")
            continue
        a, b = mlines(off.read_text(encoding="utf-8")), mlines(on.read_text(encoding="utf-8"))
        ans = [ln.strip() for ln in on.read_text(encoding="utf-8").splitlines()
               if ln.lstrip().startswith("#") and "ответ" in ln]
        tot_off += len(a); tot_on += len(b); tot_ans += len(ans)
        print(f"== {s}: строк M без правила {len(a)}, с правилом {len(b)}; заметок про ответ {len(ans)}")
        for ln in sorted(set(a) - set(b)):
            print(f"   только без правила: {ln[:150]}")
        for ln in sorted(set(b) - set(a)):
            print(f"   только с правилом:  {ln[:150]}")
        for ln in ans:
            print(f"   {ln[:170]}")
    print(f"ИТОГО: строк M без правила {tot_off}, с правилом {tot_on}; заметок про ответ {tot_ans}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
