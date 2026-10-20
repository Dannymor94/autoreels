#!/usr/bin/env python3
"""M118 (замер; пишет только handoff/m118/owner_starts.jsonl): начала клипов, которые владелец выбрал сам (манифесты
с selection_source: human), — запросами судьи начала в том же виде, что задаёт arl autocut. Потом arl judge-bench
задаёт их каждой модели: модель, которая отбраковывает начала владельца, строже владельца.

    .venv/bin/python handoff/m118/owner_starts.py

Начало клипа — первая фраза его субтитров (после холодного старта, если он есть), следующая фраза — вторая. «О чём
клип» — заголовок клипа, иначе описание, иначе его последняя фраза (как autocut берёт вывод).
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

from autoreels.cloud.autocut import STANDALONE_SYSTEM

END = (".", "?", "!", "…")


def sentences(words: list[dict]) -> list[str]:
    out, cur = [], []
    for w in words:
        cur.append(w["word"].strip())
        if w["word"].rstrip().endswith(END):
            out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return [s for s in out if s]


def main() -> int:
    rows, per = [], {}
    for mp in sorted(glob.glob("manifests/*.json")):
        try:
            m = json.load(open(mp, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(m, dict) or m.get("selection_source") != "human":     # *.blocks.json etc. are lists
            continue
        stem = Path(mp).stem
        for r in m.get("reels") or []:
            subs = r.get("subtitles") or []
            co = r.get("cold_open")
            if co:
                subs = [w for w in subs if (w["t0"] + w["t1"]) / 2 > co["end"]]
            ss = sentences(subs)
            if not ss:
                continue
            core = (r.get("title") or r.get("description") or (ss[-1] if len(ss) > 1 else ""))
            core = " ".join(w for w in core.split() if not w.startswith("#")).strip()     # hashtags say nothing
            msg = f"First sentence: «{ss[0]}»\nFollowing sentence: «{ss[1] if len(ss) > 1 else ''}»" + \
                  (f"\nThe clip is about: {core}" if core else "")
            rows.append({"stem": stem, "label": "First sentence", "model": "owner", "system": STANDALONE_SYSTEM,
                         "msg": msg, "ok": True, "why": f"клип владельца {r.get('id')}", "cached": False})
            per[stem] = per.get(stem, 0) + 1
    out = Path("handoff/m118/owner_starts.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
    print(f"начал владельца: {len(rows)} → {out}")
    for k, v in sorted(per.items()):
        print(f"   {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
