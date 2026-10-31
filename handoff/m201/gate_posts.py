"""M201, часть 4: сколько готовых клипов гейта без поста (<rid>.post.txt). arl describe не пишет файл, когда модель не
ответила (тогда crosspost берёт подпись рендера <rid>.txt) — в m197 «описание: модель не ответила» 9 раз.
Только чтение. Запуск из корня: .venv/bin/python handoff/m201/gate_posts.py m183 m196"""
from __future__ import annotations

import sys
from pathlib import Path

root = Path.cwd()
assert (root / "config" / "r0.yaml").is_file(), "запускать из корня проекта"
SRC = ("disko_beach_p1", "disko_beach_p2", "disko_beach_p3", "day_yoga_p1", "day_yoga_p2",
       "prew_isaev_anna", "prew_isaev_danny")
for gate in sys.argv[1:] or ("m183", "m196"):
    tot = tot_post = 0
    print(f"== гейт {gate}")
    for s in SRC:
        d = root / "reels-out" / s / "_gate" / gate
        if not d.is_dir():
            print(f"  {s:18} папки нет")
            continue
        clips = sorted(p for p in d.glob("r*.mp4") if ".ERROR" not in p.name)
        missing = [p.stem for p in clips if not p.with_name(p.stem + ".post.txt").is_file()]
        tot += len(clips)
        tot_post += len(clips) - len(missing)
        print(f"  {s:18} клипов {len(clips):2}, с постом {len(clips) - len(missing):2}"
              + (f", без поста: {' '.join(missing)}" if missing else ""))
    print(f"  ИТОГО {gate}: клипов {tot}, с постом {tot_post}, без поста {tot - tot_post}")
