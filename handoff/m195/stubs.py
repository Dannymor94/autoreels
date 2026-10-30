#!/usr/bin/env python3
"""M195 (замер, ничего не пишет): сколько слов выравнивания новое правило (заглушка выравнивателя далеко от своего
времени Whisper) выбрасывает в каждом источнике, и какие.

    .venv/bin/python handoff/m195/stubs.py      # из корня проекта, после патча
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "src"))
from autoreels import __main__ as cli                                   # noqa: E402
from autoreels.cloud import plan as P                                   # noqa: E402
from autoreels.core.models import Manifest                              # noqa: E402

STEMS = ["prew_isaev_anna", "prew_isaev_danny", "day_yoga_p1", "day_yoga_p2",
         "disko_beach_p1", "disko_beach_p2", "disko_beach_p3"]
tot = 0
for s in STEMS:
    m = Manifest.model_validate_json((ROOT / "manifests" / f"{s}.json").read_text(encoding="utf-8"))
    al = P.load_alignment(ROOT / "transcripts" / f"{s}.align.json", m.source_sha256)
    if not al:
        print(f"== {s}: нет выравнивания")
        continue
    tx = cli._resolve_cached_transcript(m, ROOT / "data" / "cache")
    text = {round(w.t0 * 1000): w.word for w in (tx.words if tx else [])}
    _, new = P.clean_alignment(al.get("words", []))
    saved = P._align_guess
    P._align_guess = lambda e: False                                    # the rule off: what M194 dropped
    try:
        _, old = P.clean_alignment(al.get("words", []))
    finally:
        P._align_guess = saved
    extra = sorted(set(round(t * 1000) for t in new) - set(round(t * 1000) for t in old))
    tot += len(extra)
    print(f"== {s}: слов выравнивания {len(al.get('words', []))}; выброшено раньше {len(old)}, теперь {len(new)} "
          f"(+{len(extra)})")
    for k in extra[:25]:
        print(f"   {k / 1000:9.3f}  «{text.get(k, '?')}»")
print(f"ИТОГО новых выброшенных: {tot}")
