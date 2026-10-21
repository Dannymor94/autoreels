#!/usr/bin/env python3
"""M124 (ничего не пишет): включать ли groq.dual — по строке groq-dual таблицы tx_variants.py, правило объявлено
заранее: слов whisper.cpp ≥ 85%, концов предложения ≥ 7 на 100 слов, известных выдумок 0.

    .venv/bin/python handoff/m124/decide_tx.py handoff/m124/tx.txt     → последняя строка: включить | оставить выключенным
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    row = next((ln for ln in text.splitlines() if ln.strip().startswith("groq-dual")), None)
    if row is None:
        print("ошибка: нет строки groq-dual в таблице")
        return 1
    nums = re.findall(r"-?\d+(?:[.,]\d+)?", row.split("groq-dual", 1)[1])
    # columns: слов, концов/100, известных, на речи, повторов, звук без слов (с), слов whisper.cpp в ней (%)
    if len(nums) < 7:
        print(f"ошибка: не разобрать строку: {row}")
        return 1
    words, ends, known, share = int(nums[0]), float(nums[1].replace(",", ".")), int(nums[2]), float(nums[6].replace(",", "."))
    ok = share >= 85.0 and ends >= 7.0 and known == 0
    print(f"groq-dual: слов {words}, концов на 100 слов {ends:g} (нужно ≥ 7), известных выдумок {known} (нужно 0), "
          f"слов whisper.cpp {share:g}% (нужно ≥ 85)")
    print("включить" if ok else "оставить выключенным")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
