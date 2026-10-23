#!/usr/bin/env python3
"""M134 measure (read-only): what would change if block cutting took pauses from the SOUND (M1.8 consumer 5).

Today the review block set (sentences B.k, blocks, fingerprint) is cut on Whisper gaps:
compress_transcript breaks a sentence at a gap > sentence_pause_sec, candidate_blocks closes a block at a
gap > min_pause_for_phrase_end. This script builds the same block set a second time from "heard" word times
(speech map / alignment; untranscribed speech counts as speech) and compares. Writes nothing.

Run from the project root:  .venv/bin/python handoff/m134/measure_blocks.py [stem ...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "src"))

from autoreels import __main__ as M                       # noqa: E402
from autoreels.cloud.plan import SpeechTimes, load_alignment  # noqa: E402
from autoreels.cloud.speechmap import SPEECHMAP_VERSION     # noqa: E402
from autoreels.core.config import load_r0_config           # noqa: E402
from autoreels.core.models import Manifest                 # noqa: E402

SIDE = (".discarded.json", ".blocks.json", ".failed_chunks.json")


def heard_transcript(t, times):
    """Word times replaced by the audible ones; a word followed by untranscribed speech is held to its end."""
    ws = t.words
    out = []
    for i, w in enumerate(ws):
        a0, a1 = times.audible(w)
        if i + 1 < len(ws):
            n0 = times.audible(ws[i + 1])[0]
            for u0, u1 in times.untranscribed_between(a1, n0):
                a1 = max(a1, min(u1, n0))
        out.append(w.model_copy(update={"t0": a0, "t1": max(a1, a0)}))
    return t.model_copy(update={"words": out})


def flips(t, th, thr):
    """word pairs where 'gap > thr' differs between Whisper and heard times"""
    n = 0
    for i in range(len(t.words) - 1):
        g_w = t.words[i + 1].t0 - t.words[i].t1
        g_h = th.words[i + 1].t0 - th.words[i].t1
        if (g_w > thr) != (g_h > thr):
            n += 1
    return n


def main(stems):
    r0 = load_r0_config(ROOT / "config" / "r0.yaml")
    rows = []
    for mp in sorted((ROOT / "manifests").glob("*.json")):
        if mp.name.endswith(SIDE) or ".blocks." in mp.name:
            continue
        if stems and mp.stem not in stems:
            continue
        try:
            m = Manifest.model_validate_json(mp.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            rows.append((mp.stem, f"manifest unreadable: {e}")); continue
        t, _ = M._resolve_transcript(m, ROOT / "data" / "cache")
        if t is None:
            rows.append((mp.stem, "no transcript in data/cache")); continue
        smap = None
        sp = ROOT / "transcripts" / f"{mp.stem}.speechmap.json"
        if sp.is_file():
            d = json.loads(sp.read_text(encoding="utf-8"))
            if d.get("version") == SPEECHMAP_VERSION and d.get("source_sha256") == m.source_sha256:
                smap = d
        al = load_alignment(ROOT / "transcripts" / f"{mp.stem}.align.json", m.source_sha256)
        if smap is None and al is None:
            rows.append((mp.stem, "no speech map / alignment for this transcript")); continue
        times = SpeechTimes(t.words, smap, al)
        th = heard_transcript(t, times)
        kind = m.source_kind or r0.source_kind
        A_all, A, _ = M._review_block_set(t, r0, kind)
        B_all, B, _ = M._review_block_set(th, r0, kind)
        # block boundaries by first-word index (times differ by construction, words don't)
        idx = {round(w.t0 * 1000): i for i, w in enumerate(t.words)}
        idx_h = {round(w.t0 * 1000): i for i, w in enumerate(th.words)}
        def bounds(bl, ix, words):
            out = set()
            for blk in bl:
                k = min(range(len(words)), key=lambda i: abs(words[i].t0 - blk.start)) if words else 0
                out.add(k)
            return out
        bA, bB = bounds(A, idx, t.words), bounds(B, idx_h, th.words)
        rows.append((mp.stem, {
            "words": len(t.words),
            "gap_flips@sentence_pause": flips(t, th, r0.sentence_pause_sec),
            "gap_flips@phrase_end": flips(t, th, r0.min_pause_for_phrase_end),
            "blocks_all A→B": f"{len(A_all)}→{len(B_all)}",
            "kept A→B": f"{len(A)}→{len(B)}",
            "kept boundaries same": f"{len(bA & bB)} of {len(bA | bB)}",
            "fingerprint same": M_fp(A) == M_fp(B),
        }))
    print("# M134 measure — block set on Whisper gaps (A) vs heard pauses (B)\n")
    for stem, r in rows:
        print(f"## {stem}")
        if isinstance(r, str):
            print(f"skipped: {r}\n"); continue
        for k, v in r.items():
            print(f"- {k}: {v}")
        print()


def M_fp(bl):
    from autoreels.cloud.blocks import _block_fingerprint
    return _block_fingerprint(bl)


if __name__ == "__main__":
    main(set(sys.argv[1:]))
