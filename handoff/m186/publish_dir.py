"""M186: one folder with every clip of the grid, named in publishing order — export/publish/NNN_rXX_<источник>.mp4
(number of the grid row first, the source last), the post beside it as NNN_rXX_<источник>.txt and the cover
(.jpg/.png) if crosspost made one. Files are hard links to the gate's clips (no extra disk; a copy where a link is
impossible). grid.csv (the owner's table) gets the new names in «Что»; schedule.csv and plan_by_date.csv (crosspost
import, paths inside export/crosspost) stay as they are.
Dry run by default; --do writes. Usage (project root): python publish_dir.py GATE [--do]"""
import csv
import os
import shutil
import sys
from pathlib import Path

gate, do = sys.argv[1], "--do" in sys.argv
root = Path(".")
out = root / "export" / "publish"
sched = root / "export/crosspost/schedule.csv"
rows = list(csv.DictReader(open(sched, encoding="utf-8-sig", newline=""), delimiter=";"))
width = max(3, len(str(len(rows))))
plan = []
missing = []
for i, r in enumerate(rows, 1):
    S, rid = r["серия"], r["клип"]
    src = root / "reels-out" / S / "_gate" / gate
    name = f"{i:0{width}d}_{rid}_{S}"
    mp4 = src / f"{rid}.mp4"
    if not mp4.is_file():
        missing.append(f"{S}/{rid}")
        continue
    post = src / f"{rid}.post.txt"
    if not post.is_file():
        post = src / f"{rid}.txt"
    plan.append((r, name, mp4, post, [p for p in (root / "export/crosspost" / S).glob(f"{rid}.*")
                                      if p.suffix.lower() in (".jpg", ".jpeg", ".png")]))
print(f"строк сетки {len(rows)}, клипов найдено {len(plan)}, нет файла: {len(missing)}" + (f" — {', '.join(missing)}" if missing else ""))
for r, name, *_ in plan[:3]:
    print(f"  {name}.mp4  ← {r['серия']}/{r['клип']}.mp4  ({r['дата']})")
if not do:
    print("пробный прогон — --do пишет export/publish/")
    sys.exit(1 if missing else 0)
if missing:
    sys.exit("СТОП: у строк сетки нет клипов — сначала сетка и гейт должны совпасть")
if out.exists():
    trash = Path.home() / ".Trash" / "autoreels-m186-publish-old"
    shutil.move(str(out), str(trash))
out.mkdir(parents=True)


def put(src: Path, dst: Path):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


for r, name, mp4, post, covers in plan:
    put(mp4, out / f"{name}.mp4")
    if post.is_file():
        shutil.copyfile(post, out / f"{name}.txt")
    for c in covers:
        put(c, out / f"{name}{c.suffix.lower()}")
for fn, header, key in (("grid.csv", "Что", None),):
    p = root / "export/crosspost" / fn
    if not p.exists():
        continue
    g = list(csv.DictReader(open(p, encoding="utf-8-sig", newline=""), delimiter=";"))
    for row, (r, name, *_ ) in zip(g, plan):
        row[header] = f"{name}.mp4"
    with open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(g[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(g)
n_mp4 = len(list(out.glob("*.mp4")))
print(f"export/publish: {n_mp4} видео, {len(list(out.glob('*.txt')))} постов, обложек {len([p for p in out.iterdir() if p.suffix in ('.jpg', '.jpeg', '.png')])}")
