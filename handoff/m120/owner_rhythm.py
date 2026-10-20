#!/usr/bin/env python3
"""M120 (замер, ничего не пишет): правило скачков (autocut.rhythm_*, config/r0.yaml) на клипах, которые владелец
выбрал сам (манифесты с selection_source: human, куски — сегменты клипа). Правило написано по его практике — его клипы
должны проходить; не прошедший клип печатается с причиной и длинами кусков.

    .venv/bin/python handoff/m120/owner_rhythm.py
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

from autoreels.__main__ import load_r0_config
from autoreels.cloud.autocut import AutoParams, rhythm_pieces, rhythm_why


def main() -> int:
    ac = load_r0_config(Path("config/r0.yaml")).autocut
    p = AutoParams(rhythm=True, max_jumps=ac.rhythm_max_jumps, jump_sec=ac.rhythm_jump_sec,
                   settle_near_sec=ac.rhythm_settle_near, settle_far_sec=ac.rhythm_settle_far,
                   settle_far_at_sec=ac.rhythm_far_sec, settle_tail=ac.rhythm_tail)
    n = bad = 0
    hist: dict = {}
    for mp in sorted(glob.glob("manifests/*.json")):
        try:
            m = json.load(open(mp, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(m, dict) or m.get("selection_source") != "human":
            continue
        for r in m.get("reels") or []:
            sp = [(float(s["start"]), float(s["end"])) for s in (r.get("segments") or [])] \
                or [(float(r["start"]), float(r["end"]))]
            pcs = rhythm_pieces(sp, p.jump_sec)
            n += 1
            hist[len(pcs) - 1] = hist.get(len(pcs) - 1, 0) + 1
            why, _k = rhythm_why(sp, p)
            if why:
                bad += 1
                lens = [round(sum(sp[i][1] - sp[i][0] for i in pc), 1) for pc in pcs]
                print(f"   ✗ {Path(mp).stem} {r.get('id')}: {why}; куски {lens} с; крючок: «{(r.get('hook') or '')[:50]}»")
    print(f"клипов владельца {n}, не проходят {bad}; скачков на клип: "
          + ", ".join(f"{k} — {v}" for k, v in sorted(hist.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
