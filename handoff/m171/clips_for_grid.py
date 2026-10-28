"""M171: всё, что уходит в продакшн, одним списком для сетки — из таблиц export/crosspost/*_m163.csv и *_m157.csv
(после перевыгрузки под новыми именами) и копий разметки: серия, клип, файл, заголовок (t:), длина, пост.
    .venv/bin/python handoff/m171/clips_for_grid.py  → handoff/m171/clips.md и handoff/m171/clips.json"""
import csv, glob, json, re
from pathlib import Path

rows = []
for c in sorted(glob.glob("export/crosspost/*_m163.csv") + glob.glob("export/crosspost/*_m157.csv")):
    series, gate = re.match(r"(.+)_(m\d+)\.csv$", Path(c).name).groups()
    rv = Path(f"reviews/{series}_{gate}.review.json")
    reels = {r["id"]: r for r in json.loads(rv.read_text(encoding="utf-8"))["reels"]} if rv.is_file() else {}
    with open(c, encoding="utf-8-sig", newline="") as fh:
        for rec in csv.reader(fh, delimiter=";"):
            if not rec or rec[0] in ("файл", "file"):
                continue
            f, text = rec[0], rec[1]
            rid = Path(f).stem
            r = reels.get(rid, {})
            segs = r.get("segments") or [{"start": r.get("start", 0), "end": r.get("end", 0)}]
            rows.append({"series": series, "gate": gate, "clip": rid, "file": f, "title": r.get("title") or "",
                         "sec": round(sum(s["end"] - s["start"] for s in segs), 1), "post": text.strip()})
Path("handoff/m171/clips.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
with open("handoff/m171/clips.md", "w", encoding="utf-8") as fh:
    for i, r in enumerate(rows, 1):
        fh.write(f"## {i}. {r['series']} {r['clip']} ({r['sec']} с) — {r['title']}\n{r['post']}\n\n")
print(f"клипов: {len(rows)}, серий: {len({r['series'] for r in rows})}")
