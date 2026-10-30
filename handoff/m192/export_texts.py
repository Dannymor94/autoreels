#!/usr/bin/env python3
"""M192b (только чтение, пишет в handoff/m192/): тексты 20 клипов гейта ab192 для слепых судей.

    .venv/bin/python handoff/m192/export_texts.py      # из корня проекта

Для каждого клипа reviews/<stem>_ab192.review.json: что зритель слышит, по порядку проигрывания (субтитры),
отдельно — фраза холодного старта, плашка t:, подпись d:, длительность. Клипам даются нейтральные номера
X01…X20 в перемешанном порядке (seed 1921). Строки разметки, метки M<n>, номера rNN и источник в файл для
судей НЕ пишутся. Соответствие номеров — handoff/m192/blind_map.csv.
"""
from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path.cwd()


def dur(r: dict) -> float:
    segs = r.get("segments") or [{"start": r["start"], "end": r["end"]}]
    d = sum(s["end"] - s["start"] for s in segs)
    if r.get("cold_open"):
        d += r["cold_open"]["end"] - r["cold_open"]["start"]
    return round(d / (r.get("speed") or 1.0), 1)


def hook_text(r: dict) -> str:
    co = r.get("cold_open")
    if not co:
        return ""
    return " ".join(w["word"] for w in r.get("subtitles") or [] if co["start"] - 0.05 <= w["t0"] < co["end"])


def main() -> int:
    items = []
    for p in sorted((ROOT / "reviews").glob("*_ab192.review.json")):
        stem = p.name.replace("_ab192.review.json", "")
        for r in json.loads(p.read_text(encoding="utf-8")).get("reels") or []:
            label = (r.get("montage") or "").split()[:1]
            items.append({"stem": stem, "rid": r["id"], "label": label[0] if label else "",
                          "rendered": (ROOT / "reels-out" / stem / "_gate" / "ab192" / f"{r['id']}.mp4").is_file(),
                          "duration_sec": dur(r), "title": r.get("title_overlay") or "",
                          "caption": r.get("description") or "", "hook": hook_text(r),
                          "text": " ".join(w["word"] for w in r.get("subtitles") or [])})
    random.Random(1921).shuffle(items)
    out, rows = [], []
    for n, it in enumerate(items, 1):
        x = f"X{n:02d}"
        rows.append({"x": x, "stem": it["stem"], "rid": it["rid"], "label": it["label"], "rendered": it["rendered"]})
        out.append({"id": x, "duration_sec": it["duration_sec"], "cold_open": it["hook"], "title": it["title"],
                    "caption": it["caption"], "text": it["text"]})
    (ROOT / "handoff" / "m192" / "blind_texts.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                                 encoding="utf-8")
    with open(ROOT / "handoff" / "m192" / "blind_map.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["x", "stem", "rid", "label", "rendered"], delimiter=";")
        w.writeheader()
        w.writerows(rows)
    print(f"клипов: {len(out)} (с видео {sum(r['rendered'] for r in rows)}) → handoff/m192/blind_texts.json, blind_map.csv")
    return 0 if out else 1


if __name__ == "__main__":
    sys.exit(main())
