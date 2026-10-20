#!/usr/bin/env python3
"""M118 (замер, ничего не пишет): расшифровки одного источника рядом — слова, концы предложений, выдумки, звук без слов
и доля слов whisper.cpp в каждой.

    .venv/bin/python handoff/m118/tx_variants.py <манифест> <whisper.cpp-эталон> <вариант> [<вариант> …]
    например: IMG_6848 local-m111-novad groq-noprompt groq-noprompt-gp

Первая строка — расшифровка манифеста (Groq с подсказкой); варианты — transcripts/<stem>.<вариант>.transcript.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from autoreels.__main__ import _resolve_cached_transcript, _txcheck_params, load_r0_config
from autoreels.cloud.txcheck import _sent_ends, check, compare_words
from autoreels.core.models import Manifest, Transcript


def main() -> int:
    stem, ref_tag, *tags = sys.argv[1:]
    root = Path(".")
    man = Manifest.model_validate_json((root / "manifests" / f"{stem}.json").read_text(encoding="utf-8"))
    load = lambda t: Transcript.model_validate_json(  # noqa: E731
        (root / "transcripts" / f"{stem}.{t}.transcript.json").read_text(encoding="utf-8"))
    ref = load(ref_tag)
    prm = _txcheck_params(load_r0_config(root / "config" / "r0.yaml"), root)
    intervals = None
    smp = root / "transcripts" / f"{stem}.speechmap.json"
    if smp.is_file():
        d = json.loads(smp.read_text(encoding="utf-8"))
        if d.get("source_sha256") == man.source_sha256:
            intervals = d.get("intervals") or None
    rows = [("Groq с подсказкой (сейчас)", _resolve_cached_transcript(man, root / "data" / "cache"))]
    rows += [(t, load(t)) for t in tags] + [(f"whisper.cpp {ref_tag}", ref)]
    print(f"=== {stem}")
    print(f"   {'расшифровка':30} {'слов':>6} {'концов/100':>10} {'известных':>9} {'на речи':>7} {'повторов':>8} "
          f"{'звук без слов':>13} {'слов whisper.cpp в ней':>22}")
    for name, tr in rows:
        c = check(tr.words, intervals, prm)
        cw = compare_words(ref.words, tr.words)
        print(f"   {name[:30]:30} {len(tr.words):6d} {_sent_ends(tr.words):10} {len(c['known']):9d} {c['serious']:7d} "
              f"{len(c['repeat']):8d} {c['sparse_sec']:12.0f}с {100.0 * cw['matched'] / max(1, cw['ref_words']):21.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
