"""M208: the map's passport by rules (cloud/textmap.py) against the model's, on the maps the sources have.

For each transcripts/<source>.map.json: the rules recompute role, strength, standalone and topics from the thoughts'
text and voice; the table says how often they agree with the model and how both are spread. The model is not the
truth — what counts is the clips (score_gate coverage of the owner's clips in an A/B of arl auto); this shows where the
rules and the model part. Read only.
Run from the project root: .venv/bin/python tools/map_rules_check.py [source …]"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from autoreels.cloud.textmap import apply_rules  # noqa: E402

SOURCES = ("disko_beach_p1", "disko_beach_p2", "disko_beach_p3", "day_yoga_p1", "day_yoga_p2",
           "prew_isaev_anna", "prew_isaev_danny")


def _spearman(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 3:
        return None

    def ranks(x):
        order = sorted(range(n), key=lambda i: x[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and x[order[j + 1]] == x[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2.0
            i = j + 1
        return r
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else None


def _borders(topics: list) -> set[int]:
    return {i for i in range(1, len(topics)) if topics[i] != topics[i - 1]}


def _border_f1(model: set[int], rules: set[int], tol: int = 1) -> tuple[int, int, int]:
    hit = sum(1 for b in rules if any(abs(b - m) <= tol for m in model))
    return hit, len(rules), len(model)


def main(argv=None) -> int:
    stems = list(argv if argv is not None else sys.argv[1:]) or list(SOURCES)
    T = Counter()
    roles_m, roles_r, punch_m, punch_r, confusion = Counter(), Counter(), Counter(), Counter(), Counter()
    all_pm, all_pr = [], []
    print(f"{'источник':18} {'мыслей':>6} {'роль':>6} {'сила±1':>7} {'ρ силы':>7} {'самост.':>8} {'границы тем':>14}")
    for stem in stems:
        mp = ROOT / "transcripts" / f"{stem}.map.json"
        if not mp.is_file():
            print(f"{stem:18} нет карты")
            continue
        m = json.loads(mp.read_text(encoding="utf-8"))
        r = apply_rules(m)
        mu = [u for u in m.get("units") or [] if u.get("role")]
        ru = {u["id"]: u for u in r["units"]}
        n = len(mu)
        if not n:
            print(f"{stem:18} нет паспорта модели")
            continue
        same_role = sum(1 for u in mu if ru[u["id"]]["role"] == u["role"])
        pm = [int(u.get("punch") or 0) for u in mu]
        pr = [int(ru[u["id"]]["punch"]) for u in mu]
        near = sum(1 for a, b in zip(pm, pr) if abs(a - b) <= 1)
        same_st = sum(1 for u in mu if bool(ru[u["id"]]["standalone"]) == bool(u.get("standalone", True)))
        units_all = m.get("units") or []
        hit, nr, nm = _border_f1(_borders([u.get("topic") for u in units_all]),
                                 _borders([ru[u["id"]]["topic"] for u in units_all]))
        rho = _spearman([float(x) for x in pm], [float(x) for x in pr])
        print(f"{stem:18} {n:6} {100 * same_role / n:5.0f}% {100 * near / n:6.0f}% "
              f"{(f'{rho:.2f}' if rho is not None else '—'):>7} {100 * same_st / n:7.0f}% "
              f"{hit:>4}/{nr} ({nm} у модели)")
        T.update(n=n, role=same_role, near=near, st=same_st, hit=hit, nr=nr, nm=nm)
        for u in mu:
            roles_m[u["role"]] += 1
            roles_r[ru[u["id"]]["role"]] += 1
            punch_m[int(u.get("punch") or 0)] += 1
            punch_r[int(ru[u["id"]]["punch"])] += 1
            if ru[u["id"]]["role"] != u["role"]:
                confusion[(u["role"], ru[u["id"]]["role"])] += 1
        all_pm += pm
        all_pr += pr
    if T["n"]:
        rho = _spearman([float(x) for x in all_pm], [float(x) for x in all_pr])
        print(f"{'ИТОГО':18} {T['n']:6} {100 * T['role'] / T['n']:5.0f}% {100 * T['near'] / T['n']:6.0f}% "
              f"{(f'{rho:.2f}' if rho is not None else '—'):>7} {100 * T['st'] / T['n']:7.0f}% "
              f"{T['hit']:>4}/{T['nr']} ({T['nm']} у модели)")
        print("\nроли (модель → правила): " + ", ".join(f"{k} {roles_m[k]}→{roles_r[k]}"
                                                       for k in sorted(set(roles_m) | set(roles_r))))
        print("сила (модель → правила): " + ", ".join(f"{k}: {punch_m[k]}→{punch_r[k]}" for k in range(1, 6)))
        print("частые расхождения ролей (модель → правила): "
              + ", ".join(f"{a}→{b} {c}" for (a, b), c in confusion.most_common(6)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
