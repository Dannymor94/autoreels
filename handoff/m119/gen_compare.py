#!/usr/bin/env python3
"""M119 (замер, ничего не пишет): какие кандидаты код строит без модели — сборка из разных мест (сейчас) против
отрезков подряд (passage) — и сколько клипов владельца они покрывают.

    .venv/bin/python handoff/m119/gen_compare.py

Источники — манифесты с ручным выбором (selection_source: human), у которых есть карта мыслей. Для каждого arl autocut
готовит всё, что получает propose (мысли, фразы, тон концов), с --llm none; затем propose запускается в вариантах:
  A  сейчас: generator montage, роли зерна STORY, target_sec из config/r0.yaml
  E  montage, но мысль берёт с собой только ту, на которую опирается (lean_depth 1), а не всю цепочку
  F  E + зерно ещё explanation и address + target_sec 35
  B  passage, роли STORY
  C  passage + зерно ещё explanation и address (сила ≥ seed_punch)
  D  C + target_sec 35 (медиана клипов владельца 36 с)
Кандидаты, слишком похожие на уже взятые (too_close, max_shared 0), отбрасываются, как в arl autocut. Модели нет —
судьи начала и крючка не участвуют. Покрыт клип владельца — один кандидат покрывает не меньше половины его времени
(время мысли — её t0..t1 в карте). «Внутри» — доля времени кандидатов, лежащая внутри клипов владельца (владелец выбирал
не всё хорошее, так что это не точность, а «похожесть на выбор владельца»). «Первые N» — то же для N лучших по оценке
кода кандидатов, N = числу клипов владельца в этом источнике: сколько его клипов попадает в верх списка.
"""
from __future__ import annotations

import contextlib
import glob
import io
import json
from dataclasses import replace
from pathlib import Path

import autoreels.__main__ as cli
import autoreels.cloud.autocut as ac

WIDE = tuple(ac.STORY) + ("explanation", "address")
VARIANTS = [
    ("A сейчас (montage)", {}),
    ("E montage + lean_depth 1", {"lean_depth": 1}),
    ("F E + explanation/address + 35 с", {"lean_depth": 1, "seed_roles": WIDE, "target_sec": 35.0}),
    ("B passage", {"generator": "passage"}),
    ("C passage + explanation/address", {"generator": "passage", "seed_roles": WIDE}),
    ("D C + target 35 с", {"generator": "passage", "seed_roles": WIDE, "target_sec": 35.0}),
]


def capture(stem: str):
    """Everything arl autocut hands to propose (rules only), or None when it stops before."""
    got: dict = {}
    orig = ac.propose

    def grab(units, p, sentences=None, **kw):
        got.update(units=units, p=p, sentences=sentences, kw=kw)
        return []
    ac.propose = grab
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            cli.cmd_autocut(stem, llm="none", check=False, clips=50, out=str(Path("/tmp") / "m119_gen_scratch.txt"))
    finally:
        ac.propose = orig
        Path("/tmp/m119_gen_scratch.txt").unlink(missing_ok=True)
    return got or None, buf.getvalue()


def ov(a, b) -> float:
    return sum(max(0.0, min(a1, b1) - max(a0, b0)) for a0, a1 in a for b0, b1 in b)


def main() -> int:
    tot = {name: [0, 0, 0, 0.0, 0.0, 0] for name, _ in VARIANTS}   # candidates, covered, owner clips, inside, secs, top-N
    for mp in sorted(glob.glob("manifests/*.json")):
        try:
            m = json.load(open(mp, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(m, dict) or m.get("selection_source") != "human":
            continue
        stem = Path(mp).stem
        if not (Path("transcripts") / f"{stem}.map.json").is_file():
            print(f"\n=== {stem}: нет карты — пропущен")
            continue
        got, log = capture(stem)
        if got is None:
            print(f"\n=== {stem}: arl autocut остановился до сборок — пропущен: {log.strip().splitlines()[-1:]}")
            continue
        units, p, sentences, kw = got["units"], got["p"], got["sentences"], got["kw"]
        kw = {k: v for k, v in kw.items() if k in ("end_tone",)}
        by_id = {u["id"]: u for u in units}
        owner = [[(float(s["start"]), float(s["end"])) for s in (r.get("segments") or [])]
                 or [(float(r["start"]), float(r["end"]))] for r in m.get("reels") or []]
        owner_all = [s for sp in owner for s in sp]
        print(f"\n=== {stem}: мыслей {len(units)}, клипов владельца {len(owner)}")
        for name, upd in VARIANTS:
            props = ac.propose(units, replace(p, clips=500, **upd), sentences, **kw)
            acc = []
            for pr in props:
                if ac.too_close(pr, acc, 0) is None:
                    acc.append(pr)
            sp = [[(float(by_id[i]["t0"]), float(by_id[i]["t1"])) for i in pr.units if i in by_id] for pr in acc]
            def n_cov(spans) -> int:
                return sum(1 for o in owner
                           if max((ov(o, s) for s in spans), default=0.0) >= 0.5 * sum(b - a for a, b in o))
            covered, top = n_cov(sp), n_cov(sp[:len(owner)])
            secs = sum(sum(b - a for a, b in s) for s in sp)
            inside = sum(ov(s, owner_all) for s in sp)
            t = tot[name]
            t[0] += len(acc); t[1] += covered; t[2] += len(owner); t[3] += inside; t[4] += secs; t[5] += top
            print(f"   {name:34} кандидатов {len(acc):3d}  покрыто клипов владельца {covered:2d}/{len(owner):<2d} "
                  f"(первыми {len(owner)}: {top:2d})  "
                  f"внутри {100 * inside / max(1e-9, secs):3.0f}%  средняя длина {secs / max(1, len(acc)):4.0f} с")
    print("\n=== ВСЕГО")
    for name, (n, c, o, ins, secs, top) in tot.items():
        print(f"   {name:34} кандидатов {n:3d}  покрыто клипов владельца {c:2d}/{o:<2d} (первыми N: {top:2d})  "
              f"внутри {100 * ins / max(1e-9, secs):3.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
