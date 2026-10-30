"""M174 (tools/ since M187): the publishing grid after a re-run (new gate). Keeps the meaning order of export/crosspost/schedule.csv:
every old clip is matched to the new clip of the same source that plays the most of the same source seconds
(overlap ≥ half of the shorter). Matched — same place in the grid with the new file, title and post; an old clip
with no match leaves the grid; a new clip with no match goes to the end. Dates are laid again from the first date,
one a day, same time.
Usage (project root): python tools/grid.py NEW_GATE --from OLD_GATE [--where "…"]
--from: the gate the clips of export/crosspost/schedule.csv come from (the same as NEW_GATE when the schedule already
names the new clips — then only dates, titles and posts are laid again). Clips: reviews/<S>_<gate>.review.json.
Writes export/crosspost/schedule.csv, grid.csv (Дата;Время;Что;Куда;Заголовок;Текст поста), plan_by_date.csv."""
import csv, datetime as dt, json, re, sys
from pathlib import Path

new_gate = sys.argv[1]
where = (sys.argv[sys.argv.index("--where") + 1] if "--where" in sys.argv
         else "Telegram, VK Клипы, Instagram Reels, Дзен, MAX, YouTube Shorts")
if "--from" not in sys.argv:
    sys.exit("нужно --from <гейт>, из которого клипы в schedule.csv (тот же, что NEW_GATE, если сетка уже на новых клипах)")
FROM = sys.argv[sys.argv.index("--from") + 1]
root = Path(".")
sched = root / "export/crosspost/schedule.csv"
rows = list(csv.DictReader(open(sched, encoding="utf-8-sig", newline=""), delimiter=";"))
fields = list(rows[0].keys())


def spans(r):
    segs = r.get("segments") or [{"start": r["start"], "end": r["end"]}]
    return [(s["start"], s["end"]) for s in segs]


def overlap(a, b):
    o = sum(max(0.0, min(y1, y2) - max(x1, x2)) for x1, y1 in a for x2, y2 in b)
    la, lb = sum(y - x for x, y in a), sum(y - x for x, y in b)
    return o / max(1e-6, min(la, lb))


reels = {}
for S in sorted({r["серия"] for r in rows}):
    old = {x["id"]: x for x in json.load(open(root / f"reviews/{S}_{FROM}.review.json"))["reels"]}
    new = {x["id"]: x for x in json.load(open(root / f"reviews/{S}_{new_gate}.review.json"))["reels"]}
    vdir = root / "reels-out" / S / "_gate" / new_gate
    new = {k: v for k, v in new.items() if (vdir / f"{k}.mp4").is_file()}
    reels[S] = (old, new, vdir)

used, out, gone = set(), [], []
for r in rows:
    S = r["серия"]
    old, new, vdir = reels[S]
    o = old.get(r["клип"])
    best = max(((overlap(spans(o), spans(n)), k) for k, n in new.items() if (S, k) not in used),
               default=(0.0, None)) if o else (0.0, None)
    if best[1] is None or best[0] < 0.5:
        gone.append(f"{S}/{r['клип']}")
        continue
    used.add((S, best[1]))
    out.append(dict(r, клип=best[1], файл=f"{S}/{best[1]}.mp4", _was=r["клип"]))
added = []
for S, (old, new, vdir) in reels.items():
    for k in sorted(new):
        if (S, k) not in used:
            out.append({f: "" for f in fields} | {"серия": S, "клип": k, "файл": f"{S}/{k}.mp4", "время": rows[0]["время"],
                                                    "связь": "новый ролик перепрогона — место по смыслу не выбрано",
                                                    "_was": ""})
            added.append(f"{S}/{k}")

d0 = dt.date.fromisoformat(rows[0]["дата"])
for i, r in enumerate(out):
    S = r["серия"]
    vdir = reels[S][2]
    r["№"], r["дата"] = str(i + 1), (d0 + dt.timedelta(days=i)).isoformat()
    p = vdir / f"{r['клип']}.post.txt"
    cap = vdir / f"{r['клип']}.txt"
    r["пост"] = (p if p.is_file() else cap).read_text(encoding="utf-8").strip()
    t = cap.read_text(encoding="utf-8").strip().split("\n")[0] if cap.is_file() else ""
    t = " ".join(x for x in t.split() if not x.startswith("#")).strip()
    r["заголовок"] = t if len(t) <= 100 else t[:99] + "…"


def write(path, header, items):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(header)
        w.writerows(items)


write(sched, fields, [[r.get(k, "") for k in fields] for r in out])
write(root / "export/crosspost/grid.csv", ["Дата", "Время", "Что", "Куда", "Заголовок", "Текст поста"],
      [[r["дата"], r["время"], r["файл"], where, r["заголовок"], r["пост"]] for r in out])
write(root / "export/crosspost/plan_by_date.csv", ["файл", "текст", "тип"], [[r["файл"], r["пост"], "пост"] for r in out])
same = sum(1 for r in out if r["_was"] and r["_was"] == r["клип"])
print(f"grid.csv: {len(out)} строк, {out[0]['дата']} … {out[-1]['дата']}; на месте {len(out) - len(added)} "
      f"(номер тот же у {same}), выпали {len(gone)}, новые в конце {len(added)}")
if gone:
    print("выпали: " + ", ".join(gone))
if added:
    print("новые: " + ", ".join(added))
third = [r["файл"] for r in out if re.search(r"(?i)\b(автор|спикер|рассказчик)", r["пост"])]
print(f"в третьем лице: {len(third)}" + (f" — {', '.join(third)}" if third else ""))
print(f"с хэштегом в заголовке: {sum('#' in r['заголовок'] for r in out)}")
