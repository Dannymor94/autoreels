#!/usr/bin/env python3
"""M144 measure (read-only): how many draft clips start (and open with a cold open) glued to the speech before them.

For every reviews/<stem>_auto_<tag>.txt: each M line's first sentence (its first piece) and its cold open h:, the silence
heard before that sentence (speech map / alignment, the same numbering arl autocut uses).
    .venv/bin/python handoff/m144/drafts_glued.py m138-off m144-on
"""
from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, "src")
from autoreels import __main__ as M  # noqa: E402
from autoreels.cloud.montage import montage_blocks  # noqa: E402
from autoreels.cloud.edit import merge_group_sentences, strip_credit_words  # noqa: E402
from autoreels.cloud.plan import SpeechTimes, _speech_before, load_alignment  # noqa: E402
from autoreels.cloud.speechmap import SPEECHMAP_VERSION  # noqa: E402
from autoreels.core.config import load_r0_config  # noqa: E402
from autoreels.core.models import Manifest  # noqa: E402


def pauses_for(stem, r0):
    m = Manifest.model_validate_json((Path("manifests") / f"{stem}.json").read_text(encoding="utf-8"))
    t, _ = M._resolve_transcript(m, Path("data/cache"))
    if t is None:
        return None
    smap = None
    sp = Path("transcripts") / f"{stem}.speechmap.json"
    if sp.is_file():
        d = json.loads(sp.read_text(encoding="utf-8"))
        if d.get("version") == SPEECHMAP_VERSION and d.get("source_sha256") == m.source_sha256:
            smap = d
    al = load_alignment(Path("transcripts") / f"{stem}.align.json", m.source_sha256)
    times = SpeechTimes(t.words, smap, al)
    all_b, kept, _ = M._review_block_set(t, r0, m.source_kind or r0.source_kind)
    words = t.words
    if getattr(r0, "credit_word_patterns", None):
        words = strip_credit_words(words, r0.credit_word_patterns)
    out = {}
    for key, b in montage_blocks(all_b, kept).items():
        for k, st in enumerate(merge_group_sentences([b], words), 1):
            if st:
                left, onset = _speech_before(times, st[0])
                out[f"{key}.{k}"] = 9.9 if left is None else max(0.0, onset - left)
    return out


def main(tags) -> int:
    r0 = load_r0_config(Path("config/r0.yaml"))
    tot = {t: [0, 0, 0, 0] for t in tags}          # starts, glued starts, hooks, glued hooks
    for mp in sorted(glob.glob("manifests/*.json")):
        stem = Path(mp).stem
        if ".blocks" in stem or ".discarded" in stem:
            continue
        ds = {t: Path("reviews") / f"{stem}_auto_{t}.txt" for t in tags}
        if not any(d.is_file() for d in ds.values()):
            continue
        pz = pauses_for(stem, r0)
        if pz is None:
            print(f"{stem}: transcript not found")
            continue
        line = [f"{stem}:"]
        for t, d in ds.items():
            if not d.is_file():
                line.append(f"{t} —")
                continue
            s = g = h = gh = 0
            for ln in d.read_text(encoding="utf-8").splitlines():
                if not re.match(r"^M\d* ", ln) or " | " not in ln:
                    continue
                parts = [x.strip() for x in ln.split(" | ")]
                first = parts[1].split()[0] if len(parts) > 1 and parts[1] else ""
                m1 = re.match(r"(\w+)\.(\d+)", first)
                if m1:
                    ref = f"{m1.group(1)}.{m1.group(2)}"
                    s += 1
                    g += int(pz.get(ref, 9.9) < 0.15)
                hm = re.search(r"\bh:(\w+\.\d+)", ln)
                if hm:
                    h += 1
                    gh += int(pz.get(hm.group(1), 9.9) < 0.15)
            tot[t][0] += s; tot[t][1] += g; tot[t][2] += h; tot[t][3] += gh
            line.append(f"{t}: начал {s}, склеено {g}; крючков {h}, склеено {gh}")
        print("  ".join(line))
    print("\n=== ВСЕГО (склеено = пауза < 0.15 с)")
    for t, (s, g, h, gh) in tot.items():
        print(f"   {t:12} начал {s}, склеено {g}; крючков {h}, склеено {gh}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
