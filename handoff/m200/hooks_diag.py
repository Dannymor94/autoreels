#!/usr/bin/env python3
"""M200 (только чтение): откуда «оборванные» крючки замера M199 (3 в m196: «…кроватки. Просто», «…нормально. Вы»,
«…в напряжении. И»). Гипотеза ассистента: крючок по звуку кончается на точке, а лишнее слово — первое слово следующей
фразы, которая идёт в теле ролика; его время в субтитрах попадает внутрь окна крючка, и замер (и тексты для судей)
приписали его крючку. Тогда это ошибка замера, не ролика.

    .venv/bin/python handoff/m200/hooks_diag.py m196      # из корня проекта

По каждому такому крючку: окно крючка, лишнее слово (t0–t1), в каком окне тела оно лежит, на сколько его начало
раньше конца окна крючка, и порядок слов вокруг него в субтитрах.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "src"))
from autoreels.cloud.clipcheck import clip_parts, hook_hang  # noqa: E402


def main() -> int:
    gate = sys.argv[1] if len(sys.argv) > 1 else "m196"
    n = 0
    for p in sorted((ROOT / "reviews").glob(f"*_{gate}.review.json")):
        stem = p.name[: -len(f"_{gate}.review.json")]
        for r in json.loads(p.read_text(encoding="utf-8")).get("reels") or []:
            parts = clip_parts(r)
            why = hook_hang(parts["hook"])
            if not why:
                continue
            n += 1
            co = r["cold_open"]
            subs = r.get("subtitles") or []
            last = [w for w in subs if co["start"] - 0.05 <= w["t0"] < co["end"]][-1]
            body = r.get("segments") or [{"start": r["start"], "end": r["end"]}]
            inside = [i + 1 for i, s in enumerate(body) if s["start"] - 0.05 <= last["t0"] < s["end"]]
            k = subs.index(last)
            around = " ".join(f"{w['word']}@{w['t0']:.2f}" for w in subs[max(0, k - 3):k + 3])
            print(f"{stem} {r['id']}: {why}")
            print(f"   крючок {co['start']:.3f}–{co['end']:.3f}; слово «{last['word']}» {last['t0']:.3f}–{last['t1']:.3f}, "
                  f"начало раньше конца крючка на {co['end'] - last['t0']:.3f} с; в окне тела: {inside or 'нет'}")
            spans = ", ".join("%.2f–%.2f" % (s["start"], s["end"]) for s in body)
            print(f"   окна тела: {spans}")
            print(f"   субтитры вокруг: {around}")
    print(f"крючков с лишним словом: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
