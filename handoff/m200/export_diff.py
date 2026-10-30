#!/usr/bin/env python3
"""M200 (только чтение, пишет в handoff/m200/): клипы, которые есть только в m196 или только в m200, — тексты для
слепых судей. Клип «тот же», если звучит в другом гейте на ≥ 50 % (gatescore.coverage, как M188/M191/M196).

    .venv/bin/python handoff/m200/export_diff.py      # из корня проекта

blind_texts.json — номера Z01…, перемешанные (seed 200), без источника, гейта, rNN и строк разметки.
blind_map.csv — соответствие (ассистенту; владельцу не показывать).
"""
from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "src"))
from autoreels.cloud.gatescore import coverage  # noqa: E402

OLD, NEW = "m196", "m200"
OUT = ROOT / "handoff" / "m200"
STEMS = ["prew_isaev_anna", "prew_isaev_danny", "day_yoga_p1", "day_yoga_p2",
         "disko_beach_p1", "disko_beach_p2", "disko_beach_p3"]


def reels(stem: str, gate: str) -> list[dict]:
    p = ROOT / "reviews" / f"{stem}_{gate}.review.json"
    return (json.loads(p.read_text(encoding="utf-8")).get("reels") or []) if p.is_file() else []


def dur(r: dict) -> float:
    segs = r.get("segments") or [{"start": r["start"], "end": r["end"]}]
    d = sum(s["end"] - s["start"] for s in segs) + ((r["cold_open"]["end"] - r["cold_open"]["start"])
                                                   if r.get("cold_open") else 0.0)
    return round(d / (r.get("speed") or 1.0), 1)


def hook_text(r: dict) -> str:
    co = r.get("cold_open")
    if not co:
        return ""
    return " ".join(w["word"] for w in r.get("subtitles") or [] if co["start"] - 0.05 <= w["t0"] < co["end"])


def main() -> int:
    items, same = [], 0
    for s in STEMS:
        old, new = reels(s, OLD), reels(s, NEW)
        if not new:
            print(f"  {s}: нет {s}_{NEW}.review.json — пропущен")
            continue
        miss_old = coverage(old, new)["missed"] if old else []
        miss_new = coverage(new, old)["missed"] if old else list(range(len(new)))
        same += len(new) - len(miss_new)
        print(f"  {s}: {OLD} {len(old)}, {NEW} {len(new)}; только {OLD} {len(miss_old)}, только {NEW} {len(miss_new)}")
        for gate, rs, idx in ((OLD, old, miss_old), (NEW, new, miss_new)):
            for i in idx:
                r = rs[i]
                words = [w["word"] for w in r.get("subtitles") or []]
                print(f"     {gate} {r['id']}: {' '.join(words[:14])}")
                items.append({"stem": s, "gate": gate, "rid": r["id"], "duration_sec": dur(r),
                              "cold_open": hook_text(r), "title": r.get("title_overlay") or "",
                              "caption": r.get("description") or "", "text": " ".join(words)})
    random.Random(200).shuffle(items)
    out, rows = [], []
    for n, it in enumerate(items, 1):
        z = f"Z{n:02d}"
        rows.append({"z": z, "stem": it["stem"], "gate": it["gate"], "rid": it["rid"]})
        out.append({"id": z, **{k: it[k] for k in ("duration_sec", "cold_open", "title", "caption", "text")}})
    (OUT / "blind_texts.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(OUT / "blind_map.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["z", "stem", "gate", "rid"], delimiter=";")
        w.writeheader()
        w.writerows(rows)
    n_old = sum(r["gate"] == OLD for r in rows)
    print(f"одинаковых ({NEW} ≈ {OLD}): {same}; для судей: {len(out)} (только {OLD} {n_old}, только {NEW} {len(out) - n_old})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
