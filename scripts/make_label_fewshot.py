#!/usr/bin/env python3
"""Build prompts/label_fewshot.json for `arl label` from real, owner-accepted labels (invariant 11:
few-shot only from real data with its provenance).

Source: IMG_6848 review lines v7 — labelled in chat, every clip rendered and viewed by the owner
(M24–M33). Each example is one request window rendered exactly like `arl label` renders it, and
the answer is the accepted review line translated into the JSON the labeller returns (review
numbering → block.sentence ids). The script asserts that every example answer passes the same
checks `arl label` applies, so the examples never teach a broken clip.

Needs the local transcript cache + alignment + prosody of IMG_6848 (analysis machine).
Usage: .venv/bin/python scripts/make_label_fewshot.py <spec.txt>   (writes prompts/label_fewshot.json)
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, "src")
import autoreels.__main__ as M  # noqa: E402
from autoreels.cloud.blocks import parse_compact_answer  # noqa: E402
from autoreels.cloud.edit import merge_group_sentences, strip_credit_words  # noqa: E402
from autoreels.cloud.label import LabelParams, build_wblocks, check_clip, render_window  # noqa: E402
from autoreels.cloud.plan import load_alignment  # noqa: E402
from autoreels.core.models import Manifest  # noqa: E402
from autoreels.local.prosody import load_prosody, tone_lookup  # noqa: E402

STEM = "IMG_6848"
# (window first block, window last block, the review line's first block) — two accepted clips
# with a merge, a cut, close shots and keys; each window also holds a block left unlabelled.
EXAMPLES = [(16, 18, 17), (20, 22, 21)]
PROVENANCE = ("IMG_6848 review lines v7: labelled in chat, every clip rendered and viewed by the "
              "owner (M24–M33). Built by scripts/make_label_fewshot.py.")


def main(spec_path: str) -> int:
    root = Path(".")
    r0 = M.load_r0_config(root / "config" / "r0.yaml")
    m = Manifest.model_validate_json((root / "manifests" / f"{STEM}.json").read_text(encoding="utf-8"))
    tx = M._resolve_cached_transcript(m, root / "data" / "cache")
    _, kept, _ = M._review_block_set(tx, r0, m.source_kind or r0.source_kind)
    words = strip_credit_words(tx.words, r0.credit_word_patterns)
    al = load_alignment(root / "transcripts" / f"{STEM}.align.json", m.source_sha256)
    tone = tone_lookup(load_prosody(root / "transcripts" / f"{STEM}.prosody.json", m.source_sha256, al))
    wb = build_wblocks(kept, words, tone)
    _, entries, errors, _ = parse_compact_answer(Path(spec_path).read_text(encoding="utf-8"))
    if errors:
        print("spec errors:", errors)
        return 1
    by_seq = {e.seq: e for e in entries}
    msgs = []
    p = LabelParams()
    for lo, hi, seq in EXAMPLES:
        e = by_seq[seq]
        win = wb[lo - 1:hi]
        group = win[seq - lo: seq - lo + 1 + e.merge_fwd]
        merged = merge_group_sentences([g.block for g in group], words)
        pos = {}
        for k, ms in enumerate(merged, 1):
            for w in ms:
                pos.setdefault(id(w), k)
        ids = {}
        for g in group:
            for s in g.sents:
                ids.setdefault(pos[id(s.words[0])], []).append(s.sid)
        keys = {}
        for n, ws in e.k:
            keys[ids[n][-1]] = ws[0]
        clip = {"blocks": [g.seq for g in group], "start": ids[e.s][0], "end": ids[e.e][-1],
                "cut": [ids[n][0] for n in e.x], "close": [ids[n][-1] for n in e.c], "keys": keys,
                "title": e.title, "caption": e.description, "score": e.score}
        ch = check_clip(clip, win, words, p=p)
        print(f"example {lo}-{hi}: {ch.line}\n  problems: {ch.problems or 'none'}")
        if ch.problems:
            return 1
        msgs.append({"role": "user", "content": render_window(win, p)})
        msgs.append({"role": "assistant", "content": json.dumps({"clips": [clip]}, ensure_ascii=False)})
    out = root / "prompts" / "label_fewshot.json"
    out.write_text(json.dumps({"provenance": PROVENANCE, "messages": msgs}, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print(f"→ {out}  ({sum(len(x['content']) for x in msgs)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
