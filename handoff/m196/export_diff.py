#!/usr/bin/env python3
"""M196 (только чтение, пишет в handoff/m196/): клипы, которые есть только в m183 или только в m196, — тексты для
слепых судей. Клип «тот же», если звучит в другом гейте на ≥ 50 % (gatescore.coverage, как M188/M191).

    .venv/bin/python handoff/m196/export_diff.py      # из корня проекта

blind_texts.json — номера Y01…, перемешанные (seed 196), без источника, гейта, rNN и строк разметки.
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

STEMS = ["prew_isaev_anna", "prew_isaev_danny", "day_yoga_p1", "day_yoga_p2",
         "disko_beach_p1", "disko_beach_p2", "disko_beach_p3"]


def reels(stem: str, gate: str) -> list[dict]:
    p = ROOT / "reviews" / f"{stem}_{gate}.review.json"
    return json.loads(p.read_text(encoding="utf-8")).get("reels") or [] if p.is_file() else []


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
        old, new = reels(s, "m183"), reels(s, "m196")
        if not new:
            print(f"  {s}: нет {s}_m196.review.json — пропущен")
            continue
        miss_old = coverage(old, new)["missed"] if old else []
        miss_new = coverage(new, old)["missed"] if old else list(range(len(new)))
        same += len(new) - len(miss_new)
        print(f"  {s}: m183 {len(old)}, m196 {len(new)}; только m183 {len(miss_old)}, только m196 {len(miss_new)}")
        for gate, rs, idx in (("m183", old, miss_old), ("m196", new, miss_new)):
            for i in idx:
                r = rs[i]
                items.append({"stem": s, "gate": gate, "rid": r["id"], "duration_sec": dur(r),
                              "cold_open": hook_text(r), "title": r.get("title_overlay") or "",
                              "caption": r.get("description") or "",
                              "text": " ".join(w["word"] for w in r.get("subtitles") or [])})
    random.Random(196).shuffle(items)
    out, rows = [], []
    for n, it in enumerate(items, 1):
        y = f"Y{n:02d}"
        rows.append({"y": y, "stem": it["stem"], "gate": it["gate"], "rid": it["rid"]})
        out.append({"id": y, **{k: it[k] for k in ("duration_sec", "cold_open", "title", "caption", "text")}})
    d = ROOT / "handoff" / "m196"
    (d / "blind_texts.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(d / "blind_map.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["y", "stem", "gate", "rid"], delimiter=";")
        w.writeheader()
        w.writerows(rows)
    n_old = sum(r["gate"] == "m183" for r in rows)
    print(f"одинаковых (m196 ≈ m183): {same}; для судей: {len(out)} (только m183 {n_old}, только m196 {len(out) - n_old})")
    return 0 if out else 1


if __name__ == "__main__":
    sys.exit(main())
