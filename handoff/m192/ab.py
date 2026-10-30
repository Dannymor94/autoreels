#!/usr/bin/env python3
"""M192 (замер, пишет только в handoff/m192/): слепое сравнение «эталон ассистента против автоматики».

    .venv/bin/python handoff/m192/ab.py            # из корня проекта

Берёт клипы, которые есть только в одном из гейтов:
  A — клип эталона ref191, которого нет в m183 (coverage ≥ 50 % — как в M188/M191);
  B — клип m183, которого нет в ref191, и только строки сборки «M» (у них Reel.montage — строка черновика).
Выбирает по 10 из A и B (не больше 3 на источник с каждой стороны), детерминированно (seed 192).
Для каждого источника пишет черновик handoff/m192/<stem>_ab192.txt: заголовок с fingerprint из
handoff/m191/<stem>_ref191.txt, затем выбранные строки в перемешанном порядке, перенумерованные M1, M2…,
без комментариев — по строке не видно, чья она. Ключ — handoff/m192/key.csv (владельцу не показывать).
"""
from __future__ import annotations

import csv
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "src"))
from autoreels.cloud.gatescore import coverage  # noqa: E402

STEMS = ["prew_isaev_anna", "prew_isaev_danny", "day_yoga_p1", "day_yoga_p2",
         "disko_beach_p1", "disko_beach_p2", "disko_beach_p3"]
PER_SIDE, CAP, SEED = 10, 3, 192
OUT = ROOT / "handoff" / "m192"


def reels(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8")).get("reels") or []


def pick(cands: list[tuple], rng: random.Random) -> list[tuple]:
    pool = cands[:]
    rng.shuffle(pool)
    out, per = [], {}
    for c in pool:
        if len(out) == PER_SIDE:
            break
        if per.get(c[0], 0) >= CAP:
            continue
        per[c[0]] = per.get(c[0], 0) + 1
        out.append(c)
    return out


def main() -> int:
    rng = random.Random(SEED)
    side_a, side_b = [], []
    for stem in STEMS:
        pr, pm = ROOT / "reviews" / f"{stem}_ref191.review.json", ROOT / "reviews" / f"{stem}_m183.review.json"
        if not (pr.is_file() and pm.is_file()):
            print(f"  {stem}: нет {pr.name if not pr.is_file() else pm.name} — пропущен")
            continue
        ref, auto = reels(pr), reels(pm)
        for i in coverage(ref, auto)["missed"]:
            r = ref[i]
            if r.get("montage"):
                side_a.append((stem, r["id"], r["montage"], "ref191"))
        for i in coverage(auto, ref)["missed"]:
            r = auto[i]
            if r.get("montage"):
                side_b.append((stem, r["id"], r["montage"], "m183"))
    print(f"кандидатов: только в эталоне {len(side_a)}, только в m183 (строки M) {len(side_b)}")
    chosen = pick(side_a, rng) + pick(side_b, rng)
    by_stem: dict[str, list[tuple]] = {}
    for c in chosen:
        by_stem.setdefault(c[0], []).append(c)
    OUT.mkdir(parents=True, exist_ok=True)
    key_rows = []
    for stem in STEMS:
        lines = by_stem.get(stem) or []
        if not lines:
            continue
        rng.shuffle(lines)
        head = (ROOT / "handoff" / "m191" / f"{stem}_ref191.txt").read_text(encoding="utf-8").splitlines()[:5]
        if not any(h.startswith("# fingerprint:") for h in head):
            print(f"ОШИБКА: в заголовке {stem}_ref191.txt нет fingerprint")
            return 1
        body = []
        for n, (_, rid, raw, origin) in enumerate(lines, 1):
            line = re.sub(r"^M\d*\s+", f"M{n} ", raw.strip())
            body.append(line)
            key_rows.append({"stem": stem, "label": f"M{n}", "origin": origin, "src_rid": rid, "line": line})
        (OUT / f"{stem}_ab192.txt").write_text("\n".join(head + ["# m192: слепое сравнение", ""] + body) + "\n",
                                               encoding="utf-8")
        print(f"  {stem}: {len(lines)} клипов → handoff/m192/{stem}_ab192.txt")
    with open(OUT / "key.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["stem", "label", "origin", "src_rid", "line"], delimiter=";")
        w.writeheader()
        w.writerows(key_rows)
    na = sum(r["origin"] == "ref191" for r in key_rows)
    print(f"выбрано: {len(key_rows)} (сторона A {na}, сторона B {len(key_rows) - na}); ключ → handoff/m192/key.csv")
    return 0 if key_rows else 1


if __name__ == "__main__":
    sys.exit(main())
