"""M185: number the clips of a finished gate r01, r02, … without gaps — no re-render.
Per source: the clips present in reels-out/<S>/_gate/<gate>/ (rNN.mp4, ERROR files left out) in their order get new
ids; every file of a clip (rNN.*) is renamed (through a temporary name, so r03 → r01 never meets an old r01);
reviews/<S>_<gate>.review.json keeps only those clips with the new ids (the old one saved as .before-m185.json);
export/crosspost/schedule.csv gets the new ids in «клип» and «файл».
Dry run by default; --do renames. Usage (project root): python renumber_gate.py GATE [--do]"""
import csv
import json
import re
import shutil
import sys
from pathlib import Path

gate, do = sys.argv[1], "--do" in sys.argv
SRC = ["disko_beach_p1", "disko_beach_p2", "disko_beach_p3", "day_yoga_p1", "day_yoga_p2",
       "prew_isaev_anna", "prew_isaev_danny"]
maps = {}
for S in SRC:
    d = Path("reels-out") / S / "_gate" / gate
    clips = sorted(p.stem for p in d.glob("r*.mp4") if re.fullmatch(r"r\d+", p.stem))
    m = {old: f"r{i:02d}" for i, old in enumerate(clips, 1)}
    maps[S] = m
    moved = {k: v for k, v in m.items() if k != v}
    print(f"{S}: {len(clips)} клипов, переименовать {len(moved)}: " + ", ".join(f"{k}→{v}" for k, v in moved.items()))
    if not do or not moved:
        continue
    files = {old: [f for f in d.iterdir() if f.is_file() and f.name.split(".")[0] == old] for old in moved}
    for old, fs in files.items():                       # phase 1: temporary names
        for f in fs:
            f.rename(d / ("__m185_" + moved[old] + f.name[len(old):]))
    for f in d.iterdir():                               # phase 2: final names
        if f.name.startswith("__m185_"):
            f.rename(d / f.name[len("__m185_"):])
    rj = Path("reviews") / f"{S}_{gate}.review.json"
    if rj.exists():
        shutil.copyfile(rj, rj.with_name(rj.stem + ".before-m185.json"))
        man = json.loads(rj.read_text(encoding="utf-8"))
        man["reels"] = [dict(r, id=m[r["id"]]) for r in man["reels"] if r["id"] in m]
        man["reels"].sort(key=lambda r: r["id"])
        rj.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
sched = Path("export/crosspost/schedule.csv")
if sched.exists():
    rows = list(csv.DictReader(open(sched, encoding="utf-8-sig", newline=""), delimiter=";"))
    n = 0
    for r in rows:
        new = maps.get(r["серия"], {}).get(r["клип"])
        if new and new != r["клип"]:
            n += 1
            r["клип"], r["файл"] = new, f"{r['серия']}/{new}.mp4"
    print(f"schedule.csv: строк {len(rows)}, номер сменился у {n}")
    if do and rows:
        with open(sched, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), delimiter=";")
            w.writeheader()
            w.writerows(rows)
print("готово" if do else "пробный прогон — --do переименовывает")
