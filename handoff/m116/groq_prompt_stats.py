#!/usr/bin/env python3
"""M116 (замер, ничего не пишет): расшифровка Groq с подсказкой (как сейчас) и без неё — против whisper.cpp без VAD.

    .venv/bin/python handoff/m116/groq_prompt_stats.py <манифест> <тег варианта Groq> <расшифровка whisper.cpp>
    например: IMG_6848 noprompt local-m111-novad

Печатает для трёх расшифровок: слов, концов предложений на 100 слов, известных выдумок (куски подсказки, «Субтитры
создавал…») и выдумок на речи, повторов, «звука без слов» (с) — и какую долю слов whisper.cpp каждая содержит.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from autoreels.__main__ import _resolve_cached_transcript, _txcheck_params, load_r0_config
from autoreels.cloud.txcheck import _sent_ends, check, compare_words
from autoreels.core.models import Manifest, Transcript


def main() -> int:
    stem, tag, ref_tag = sys.argv[1:4]
    root = Path(".")
    man = Manifest.model_validate_json((root / "manifests" / f"{stem}.json").read_text(encoding="utf-8"))
    cur = _resolve_cached_transcript(man, root / "data" / "cache")
    var = Transcript.model_validate_json((root / "transcripts" / f"{stem}.groq-{tag}.transcript.json").read_text(encoding="utf-8"))
    ref = Transcript.model_validate_json((root / "transcripts" / f"{stem}.{ref_tag}.transcript.json").read_text(encoding="utf-8"))
    r0 = load_r0_config(root / "config" / "r0.yaml")
    prm = _txcheck_params(r0, root)
    intervals = None
    smp = root / "transcripts" / f"{stem}.speechmap.json"
    if smp.is_file():
        d = json.loads(smp.read_text(encoding="utf-8"))
        if d.get("source_sha256") == man.source_sha256:
            intervals = d.get("intervals") or None
    print(f"=== {stem}")
    print(f"   {'расшифровка':28} {'слов':>6} {'концов/100':>10} {'известных':>9} {'на речи':>7} {'повторов':>8} "
          f"{'звук без слов':>13} {'слов whisper.cpp в ней':>22}")
    for name, tr in ((f"Groq с подсказкой ({cur.provider})", cur), (f"Groq {tag}", var), (f"whisper.cpp {ref_tag}", ref)):
        c = check(tr.words, intervals, prm)
        cw = compare_words(ref.words, tr.words)
        share = 100.0 * cw["matched"] / max(1, cw["ref_words"])
        print(f"   {name[:28]:28} {len(tr.words):6d} {_sent_ends(tr.words):10} {len(c['known']):9d} {c['serious']:7d} "
              f"{len(c['repeat']):8d} {c['sparse_sec']:12.0f}с {share:21.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
