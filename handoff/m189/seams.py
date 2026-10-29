"""M189: швы без смены плана в готовых гейтах (замер, ничего не меняет).

Шов — граница двух кусков, которые идут из разных мест источника: крючок → тело и стык кусков тела
(у второго куска window_cut == False). По правилу REEL_SPEC §3 на каждом шве план меняется
(общий ↔ крупный); одинаковый план с двух сторон шва — скачок кадра.
Запуск (корень проекта): python handoff/m189/seams.py reviews/*_m183.review.json
"""
import json
import sys

E = 1e-3


def start_shot(s):
    ci = s.get("close_intervals") or []
    return "close" if s.get("shot") == "close" or (ci and ci[0][0] < E) else "wide"


def end_shot(s):
    if s.get("shot") == "close":
        return "close"
    ci = s.get("close_intervals") or []
    return "close" if ci and ci[-1][1] >= (s["end"] - s["start"]) - E else "wide"


total_seams = total_bad = 0
for path in sys.argv[1:]:
    stem = path.split("/")[-1].replace(".review.json", "")
    m = json.load(open(path, encoding="utf-8"))
    seams = bad = 0
    names = []
    for r in m["reels"]:
        body = r.get("segments") or [{"start": r["start"], "end": r["end"], "shot": "wide", "close_intervals": []}]
        segs = ([dict(r["cold_open"], shot="close")] if r.get("cold_open") else []) + body
        for i in range(1, len(segs)):
            is_seam = (i == 1 and r.get("cold_open")) or not segs[i].get("window_cut", False)
            if not is_seam:
                continue
            seams += 1
            if end_shot(segs[i - 1]) == start_shot(segs[i]):
                bad += 1
                names.append(f"{r['id']}@{segs[i]['start']:.2f}")
    total_seams += seams
    total_bad += bad
    print(f"{stem}: швов {seams}, без смены плана {bad}" + (f" — {', '.join(names)}" if names else ""))
print(f"ВСЕГО: швов {total_seams}, без смены плана {total_bad}")
