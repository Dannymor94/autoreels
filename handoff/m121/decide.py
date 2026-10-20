#!/usr/bin/env python3
"""M121 (ничего не пишет): какой генератор включить по умолчанию — по замерам m120, правило объявлено заранее.

    .venv/bin/python handoff/m121/decide.py        → последняя строка: mixed | montage

mixed, если оба условия:
  (a) без модели на всех источниках (handoff/m120/gen.txt, «ВСЕГО»): X (mixed) покрывает клипов владельца не меньше, чем
      R (montage + скачки);
  (b) с моделью на трёх источниках (handoff/m120/drafts.txt, «ВСЕГО»): у m120-mixed сборок не меньше, чем у m120-montage.
Иначе montage. Нет файла или строки — ошибка (код 1), ничего не выбирается.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def total_section(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    idx = max(i for i, ln in enumerate(lines) if ln.startswith("=== ВСЕГО"))
    return lines[idx + 1:]


def main() -> int:
    try:
        gen = total_section(Path("handoff/m120/gen.txt"))
        drafts = total_section(Path("handoff/m120/drafts.txt"))
    except (OSError, ValueError) as exc:
        print(f"ошибка: нет замеров m120 ({exc})")
        return 1
    cov = {}
    for ln in gen:
        m = re.match(r"^\s+(\S+) .*?кандидатов\s+(\d+)\s+покрыто клипов владельца\s+(\d+)/(\d+)", ln)
        if m:
            cov[m.group(1)] = (int(m.group(3)), int(m.group(4)), int(m.group(2)))
    n = {}
    for ln in drafts:
        m = re.match(r"^\s+(m120-\w+)\s+сборок\s+(\d+).*клипов владельца покрыто (\d+)/(\d+)", ln)
        if m:
            n[m.group(1)] = (int(m.group(2)), int(m.group(3)), int(m.group(4)))
    if "R" not in cov or "X" not in cov or "m120-montage" not in n or "m120-mixed" not in n:
        print(f"ошибка: не найдены строки R/X в gen.txt или m120-montage/m120-mixed в drafts.txt: {cov} {n}")
        return 1
    a = cov["X"][0] >= cov["R"][0]
    b = n["m120-mixed"][0] >= n["m120-montage"][0]
    print(f"(a) без модели: X покрыто {cov['X'][0]}/{cov['X'][1]} (кандидатов {cov['X'][2]}), "
          f"R {cov['R'][0]}/{cov['R'][1]} (кандидатов {cov['R'][2]}) → {'да' if a else 'нет'}")
    print(f"(b) с моделью: m120-mixed сборок {n['m120-mixed'][0]} (покрыто {n['m120-mixed'][1]}/{n['m120-mixed'][2]}), "
          f"m120-montage {n['m120-montage'][0]} (покрыто {n['m120-montage'][1]}/{n['m120-montage'][2]}) → {'да' if b else 'нет'}")
    print("mixed" if a and b else "montage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
