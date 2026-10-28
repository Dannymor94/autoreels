"""M171: проверка сетки export/crosspost/schedule.csv — каждый клип продакшна ровно один раз, по одному в день подряд
с первой даты, файл существует. Колонки: №;дата;время;серия;клип;файл;заголовок;пост;связь."""
import csv, datetime as dt, json, sys
from pathlib import Path

clips = json.loads(Path("handoff/m171/clips.json").read_text(encoding="utf-8"))
want = {(c["series"], c["clip"]) for c in clips}
rows = list(csv.DictReader(open("export/crosspost/schedule.csv", encoding="utf-8-sig", newline=""), delimiter=";"))
got = [(r["серия"], r["клип"]) for r in rows]
err = []
if len(got) != len(set(got)):
    err.append(f"повторы: {[g for g in got if got.count(g) > 1][:5]}")
if set(got) != want:
    err.append(f"нет в сетке: {sorted(want - set(got))[:8]}; лишние: {sorted(set(got) - want)[:8]}")
d0 = dt.date.fromisoformat(rows[0]["дата"]) if rows else None
for i, r in enumerate(rows):
    if dt.date.fromisoformat(r["дата"]) != d0 + dt.timedelta(days=i):
        err.append(f"строка {i + 1}: дата {r['дата']} — не по одному в день подряд"); break
    if not (Path("export/crosspost") / r["файл"]).is_file():
        err.append(f"строка {i + 1}: нет файла {r['файл']}"); break
    if not r.get("связь", "").strip():
        err.append(f"строка {i + 1}: пустая «связь»"); break
print("\n".join(err) if err else f"OK: {len(rows)} роликов, {rows[0]['дата']} … {rows[-1]['дата']}")
sys.exit(1 if err else 0)
