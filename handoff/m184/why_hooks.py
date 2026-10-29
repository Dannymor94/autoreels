"""M184: why a line of the draft with h: has no cold open in the rendered clip. Per clip of reviews/<S>_m183.review.json:
the line's h: (montage raw), whether a cold open is there, and every warning about the hook / cold open.
Usage (project root): python why_hooks.py [source …]"""
import json
import re
import sys
from pathlib import Path

SRC = sys.argv[1:] or ["prew_isaev_anna", "prew_isaev_danny", "day_yoga_p1", "day_yoga_p2",
                       "disko_beach_p1", "disko_beach_p2", "disko_beach_p3"]
tot = {"h_in_line": 0, "cold_open": 0, "lost": 0}
for S in SRC:
    p = Path(f"reviews/{S}_m183.review.json")
    if not p.exists():
        print(f"{S}: нет {p}")
        continue
    gate = Path("reels-out") / S / "_gate" / "m183"
    print(f"\n######## {S}")
    for r in json.load(open(p, encoding="utf-8"))["reels"]:
        if not (gate / f"{r['id']}.mp4").exists():
            continue
        raw = r.get("montage") or ""
        h = re.search(r"(?:^|[|\s])h:(\S+)", raw)
        co = r.get("cold_open")
        ws = [w for w in (r.get("warnings") or []) if re.search(r"hook|cold open|h:\d|крюч", w, re.I)]
        kind = "сборка" if "montage" in (r.get("flags") or []) else "разметка"
        tot["h_in_line"] += bool(h)
        tot["cold_open"] += bool(co)
        lost = bool(h) and not co
        tot["lost"] += lost
        print(f"  {r['id']} [{kind}] h: {h.group(1) if h else '—'} | крючок в клипе: {'да' if co else 'НЕТ'}"
              + ("   ← ПОТЕРЯН" if lost else ""))
        for w in ws:
            print(f"       ! {w[:160]}")
print(f"\nВСЕГО: h: в строке {tot['h_in_line']}, крючок в клипе {tot['cold_open']}, потеряно {tot['lost']}")
