"""M164 замер до правки: каким клипам сейчас нужна точечная звуковая проба хвоста (её удаляет этап C).
Проба шла только у клипа без плана (planned: false), когда карты речи нет или флаг speech_map выключен.
Клип с планом или с картой её не видит — для него правка ничего не меняет. Ничего не пишет."""
import glob, json, yaml
from pathlib import Path
flag = bool((yaml.safe_load(open("config/render.yaml")) or {}).get("speech_map"))
print(f"speech_map в config/render.yaml: {flag}")
tot = {"clips": 0, "unplanned": 0, "probe": 0}
for p in sorted(glob.glob("reviews/*.review.json")):
    try:
        m = json.load(open(p, encoding="utf-8"))
    except Exception:
        continue
    stem = Path(m.get("source", "")).stem
    has_map = Path(f"transcripts/{stem}.speechmap.json").is_file()
    reels = m.get("reels") or []
    un = [r["id"] for r in reels if not r.get("planned")]
    probe = un if (not has_map or not flag) else []
    tot["clips"] += len(reels); tot["unplanned"] += len(un); tot["probe"] += len(probe)
    if probe:
        print(f"  {p}: проба у {len(probe)} из {len(reels)} ({', '.join(probe[:8])}) — карта {'есть' if has_map else 'НЕТ'}")
print(f"=== копий разметки {len(glob.glob('reviews/*.review.json'))}, клипов {tot['clips']}, без плана {tot['unplanned']}, "
      f"с пробой хвоста {tot['probe']}")
