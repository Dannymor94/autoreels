"""M181: what each clip opens with — old production set vs m176. Per clip: montage (scenarist) or label clip, the cold
open's words (крючок) or «—», the plate (t:), the first body words. Usage (project root): python hooks.py [source …]"""
import json
import sys
from pathlib import Path

OLD = {"prew_isaev_anna": "m157", "prew_isaev_danny": "m157"}
SRC = sys.argv[1:] or ["prew_isaev_anna", "prew_isaev_danny", "disko_beach_p1", "disko_beach_p2", "disko_beach_p3",
                       "day_yoga_p1", "day_yoga_p2"]


def words_in(r, a, b):
    return " ".join(w["word"] for w in (r.get("subtitles") or []) if a - 0.05 <= w["t0"] < b)


def rows(path, gate_dir):
    out = []
    for r in json.load(open(path, encoding="utf-8"))["reels"]:
        if not (gate_dir / f"{r['id']}.mp4").exists():
            continue                       # not in the gate (excluded, error)
        co = r.get("cold_open")
        hook = words_in(r, co["start"], co["end"]) if co else ""
        segs = r.get("segments") or [{"start": r["start"], "end": r["end"]}]
        body = " ".join(words_in(r, segs[0]["start"], segs[0]["end"]).split()[:12])
        kind = "сборка" if "montage" in (r.get("flags") or []) else "разметка"
        out.append((r["id"], kind, hook, r.get("title_overlay") or "", body))
    return out


for S in SRC:
    print(f"\n######## {S}")
    for tag, gate in ((OLD.get(S, "m163"), OLD.get(S, "m163")), ("m176", "m176")):
        p = Path(f"reviews/{S}_{tag}.review.json")
        d = Path("reels-out") / S / "_gate" / gate
        if not p.exists():
            print(f"== {tag}: нет {p}")
            continue
        rs = rows(p, d)
        n_hook = sum(1 for r in rs if r[2])
        kinds = {k: sum(1 for r in rs if r[1] == k) for k in ("сборка", "разметка")}
        print(f"== {tag}: клипов {len(rs)} (сборок {kinds['сборка']}, разметки {kinds['разметка']}), с крючком {n_hook}")
        for rid, kind, hook, plate, body in rs:
            print(f"  {rid} [{kind}] крючок: {hook[:90] or '—'}")
            print(f"       плашка: {plate[:90] or '—'} | начало: {body[:90]}")
