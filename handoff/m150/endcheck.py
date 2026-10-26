"""M150: конец клипа в двух review.json — было (оригинальный файл ответа) / стало (копия с продлённым e:).
  python handoff/m150/endcheck.py reviews/<S>_m150a.review.json reviews/<S>_m150.review.json r06
Печатает конец, длину, open_thought, предупреждения и последние слова субтитров; «добавлено» — слова, которых не было."""
import json, sys

a_path, b_path, rid = sys.argv[1], sys.argv[2], sys.argv[3]


def reel(p):
    for r in json.load(open(p, encoding="utf-8"))["reels"]:
        if r["id"] == rid:
            return r
    sys.exit(f"{rid} нет в {p}")


def words(r):
    return [w["word"] for w in (r.get("subtitles") or [])]


A, B = reel(a_path), reel(b_path)
for tag, r in (("было ", A), ("стало", B)):
    segs = r.get("segments") or [{"start": r["start"], "end": r["end"]}]
    dur = sum(s["end"] - s["start"] for s in segs)
    print(f"{tag}: {r['start']:.2f}–{r['end']:.2f}, {dur:.1f} с, open_thought={r.get('open_thought')}, "
          f"предупреждений {len(r.get('warnings') or [])}")
    for w in r.get("warnings") or []:
        print(f"        ⚠ {w}")
    print(f"        …{' '.join(words(r)[-14:])}")
wa, wb = words(A), words(B)
print("добавлено:", " ".join(wb[len(wa):]) if wb[:len(wa)] == wa else "(начало или середина тоже изменились — смотреть глазами)")
