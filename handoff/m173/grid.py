"""M174: the publishing grid with the fresh first-person posts. Keeps the order and dates of
export/crosspost/schedule.csv (m171); the post of every clip is read again from its <rid>.post.txt (else <rid>.txt).
Writes:
  export/crosspost/grid.csv          Дата;Время;Что;Куда;Текст поста   (the owner's table)
  export/crosspost/schedule.csv      same columns as m171, «пост» refreshed
  export/crosspost/plan_by_date.csv  файл;текст;тип   (crosspost import, grid order)
Usage: python grid.py [--where "куда"]  (run from the project root)."""
import csv, sys
from pathlib import Path

where = sys.argv[sys.argv.index("--where") + 1] if "--where" in sys.argv else "все каналы (crosspost)"
GATE = {"prew_isaev_anna": "m157", "prew_isaev_danny": "m157"}
root = Path(".")
sched = root / "export/crosspost/schedule.csv"
rows = list(csv.DictReader(open(sched, encoding="utf-8-sig", newline=""), delimiter=";"))
fields = list(rows[0].keys())
missing, third = [], []
for r in rows:
    d = root / "reels-out" / r["серия"] / "_gate" / GATE.get(r["серия"], "m163")
    p = d / f"{r['клип']}.post.txt"
    if not p.is_file():
        p = d / f"{r['клип']}.txt"
        missing.append(f"{r['серия']}/{r['клип']}")
    r["пост"] = p.read_text(encoding="utf-8").strip()
    low = " " + r["пост"].lower().replace("ё", "е") + " "
    if any(w in low for w in (" автор ", " автора ", " спикер", " рассказчик")):
        third.append(f"{r['серия']}/{r['клип']}")

def write(path, header, items):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(header)
        w.writerows(items)

write(sched, fields, [[r[k] for k in fields] for r in rows])
write(root / "export/crosspost/grid.csv", ["Дата", "Время", "Что", "Куда", "Текст поста"],
      [[r["дата"], r["время"], r["файл"], where, r["пост"]] for r in rows])
write(root / "export/crosspost/plan_by_date.csv", ["файл", "текст", "тип"], [[r["файл"], r["пост"], "пост"] for r in rows])
print(f"grid.csv: {len(rows)} строк, {rows[0]['дата']} … {rows[-1]['дата']}")
print(f"без .post.txt (взята подпись рендера): {len(missing)}" + (f" — {', '.join(missing)}" if missing else ""))
print(f"в третьем лице: {len(third)}" + (f" — {', '.join(third)}" if third else ""))
