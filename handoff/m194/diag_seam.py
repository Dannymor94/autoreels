#!/usr/bin/env python3
"""M194 (замер, ничего не пишет): что лежит вокруг места «seam inside word» disko_beach_p1 (m191, клип эталона M4,
«cut at 1019.252s splits 'сталкивания'»). Печатает слова 1012–1027 с: временем Whisper, выравниванием (start/end/score),
картой речи (audible_start/end), отрезком слова по плану (SpeechTimes.span), речью без текста (alignment.untranscribed)
и интервалами энергии карты речи в этом же окне.

    .venv/bin/python handoff/m194/diag_seam.py [stem] [t_from] [t_to]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "src"))
from autoreels import __main__ as cli                      # noqa: E402
from autoreels.cloud.plan import SpeechTimes, load_alignment  # noqa: E402
from autoreels.core.models import Manifest                  # noqa: E402

stem = sys.argv[1] if len(sys.argv) > 1 else "disko_beach_p1"
lo = float(sys.argv[2]) if len(sys.argv) > 2 else 1012.0
hi = float(sys.argv[3]) if len(sys.argv) > 3 else 1027.0
m = Manifest.model_validate_json((ROOT / "manifests" / f"{stem}.json").read_text(encoding="utf-8"))
tx = cli._resolve_cached_transcript(m, ROOT / "data" / "cache")
al = load_alignment(ROOT / "transcripts" / f"{stem}.align.json", m.source_sha256)
smap = json.loads((ROOT / "transcripts" / f"{stem}.speechmap.json").read_text(encoding="utf-8"))
times = SpeechTimes(tx.words, smap, al)
a_by = {round(float(e["t0"]) * 1000): e for e in (al or {}).get("words", [])}
s_by = {round(float(e["t0"]) * 1000): e for e in smap.get("words", [])}
print(f"{stem}: слова {lo}–{hi} с (whisper | align start–end score | map audible | план span)")
for w in tx.words:
    if not lo <= w.t0 <= hi:
        continue
    k = round(w.t0 * 1000)
    a, s = a_by.get(k), s_by.get(k)
    sp = times.span(w)
    print(f"  {w.word:18} wh {w.t0:8.3f}–{w.t1:8.3f} | "
          + (f"al {a.get('start')}–{a.get('end')} sc {a.get('score')}" if a else "al —") + " | "
          + (f"map {s.get('audible_start')}–{s.get('audible_end')}" if s else "map —")
          + f" | span {sp[0]:.3f}–{sp[1]:.3f}")
print("речь без текста (align.untranscribed):",
      [(round(a, 3), round(b, 3)) for a, b in (al or {}).get("untranscribed", []) if b >= lo and a <= hi])
print("интервалы энергии карты:", [(round(a, 3), round(b, 3)) for a, b in smap.get("intervals", []) if b >= lo and a <= hi][:40])
