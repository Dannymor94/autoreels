"""M199: four clip checks of a gate (measurement only). Usage:
    python tools/clip_checks.py <gate> [--stems a,b]
Reads reviews/<stem>_<gate>.review.json; writes reels-out/_score/<gate>_checks.json (every clip, every check).
Checks — src/autoreels/cloud/clipcheck.py: hook_hang, plate_cover, start_morph (pymorphy3), seam_shared.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from autoreels.cloud.clipcheck import check_reel, has_morph  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("gate")
    ap.add_argument("--stems", default=None)
    a = ap.parse_args()
    want = set(a.stems.split(",")) if a.stems else None
    rows = []
    for p in sorted((_REPO / "reviews").glob(f"*_{a.gate}.review.json")):
        stem = p.name[: -len(f"_{a.gate}.review.json")]
        if want and stem not in want:
            continue
        for r in json.loads(p.read_text(encoding="utf-8")).get("reels") or []:
            rows.append({"stem": stem, **check_reel(r)})
    if not rows:
        print(f"нет reviews/*_{a.gate}.review.json")
        return 1
    print(f"гейт {a.gate}: клипов {len(rows)}; морфология: {'pymorphy3' if has_morph() else 'нет (проверка 3 не делается)'}")
    hooked = [r for r in rows if r["hook"]]
    hh = [r for r in hooked if r["hook_hang"]]
    pl = [r for r in rows if r["plate"]]
    pl_low = [r for r in pl if r["plate"]["share"] < 0.25]
    pl_nocore = [r for r in pl if not r["plate"]["core"]]
    sm = [r for r in rows if r["start_morph"]]
    seams = [s for r in rows for s in r["seams"]]
    z1 = [r for r in rows if sum(1 for s in r["seams"] if s == 0) >= 1]
    z2 = [r for r in rows if sum(1 for s in r["seams"] if s == 0) >= 2]
    print(f"1. крючок обрывается: {len(hh)} из {len(hooked)} с крючком")
    print(f"2. плашка: со словами {len(pl)} из {len(rows)}; доля предложений — медиана "
          f"{statistics.median([r['plate']['share'] for r in pl]) if pl else 0:.2f}; меньше 0,25 — {len(pl_low)}; "
          f"нет в начале и выводе — {len(pl_nocore)}")
    print(f"3. начало без опоры: {len(sm)} из {len(rows)}")
    print(f"4. стыки: {len(seams)}, без общих слов {sum(1 for s in seams if s == 0)}; клипов с ≥1 таким — {len(z1)}, с ≥2 — {len(z2)}")
    for name, sel, show in (("1", hh, lambda r: f"«{r['hook'][-50:]}» — {r['hook_hang']}"),
                            ("2", pl_low, lambda r: f"«{r['title']}» доля {r['plate']['share']}"),
                            ("3", sm, lambda r: f"«{r['first'][:60]}» — {r['start_morph']}"),
                            ("4", z2, lambda r: f"«{r['title']}» стыки {r['seams']}")):
        for r in sel[:12]:
            print(f"   [{name}] {r['stem']} {r['rid']}: {show(r)}")
    out = _REPO / "reels-out" / "_score"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.gate}_checks.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ reels-out/_score/{a.gate}_checks.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
