#!/usr/bin/env python3
"""M143 measure (read-only): do clip starts come after a real pause, or glued to the speech before them?

m142: 11 of the clip starts of IMG_6848 m126 had loud sound in the 30 ms right before the cut (+24…+42 dB), and 0.15 s
of air changed nothing — the cut cannot move back: the speech before runs right up to the first word. Hypothesis: those
starts are glued to the previous words (no heard pause), the first consonant sits in the coarticulation and is lost.

For each clip start (first sound and, with a cold open, the body start) the first word after the cut is found and the
pause HEARD before it (speech map / alignment; untranscribed speech counts as speech). Compared with the owner's own
clips (manifests, selection_source human). Writes nothing.
    .venv/bin/python handoff/m143/start_pause.py reviews/IMG_6848_m126.review.json [more review copies …]
"""
from __future__ import annotations

import bisect
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
from autoreels import __main__ as M  # noqa: E402
from autoreels.cloud.plan import SpeechTimes, _speech_before, load_alignment  # noqa: E402
from autoreels.cloud.speechmap import SPEECHMAP_VERSION  # noqa: E402
from autoreels.core.models import Manifest  # noqa: E402

_TIMES: dict = {}


def times_for(stem: str):
    if stem in _TIMES:
        return _TIMES[stem]
    m = Manifest.model_validate_json((Path("manifests") / f"{stem}.json").read_text(encoding="utf-8"))
    t, _ = M._resolve_transcript(m, Path("data/cache"))
    if t is None:
        _TIMES[stem] = None
        return None
    smap = None
    sp = Path("transcripts") / f"{stem}.speechmap.json"
    if sp.is_file():
        d = json.loads(sp.read_text(encoding="utf-8"))
        if d.get("version") == SPEECHMAP_VERSION and d.get("source_sha256") == m.source_sha256:
            smap = d
    al = load_alignment(Path("transcripts") / f"{stem}.align.json", m.source_sha256)
    st = SpeechTimes(t.words, smap, al)
    ws = sorted(t.words, key=lambda w: st.audible(w)[0])
    _TIMES[stem] = (st, ws, [st.audible(w)[0] for w in ws])
    return _TIMES[stem]


def pause_at(stem: str, cut: float):
    tt = times_for(stem)
    if tt is None:
        return None
    st, ws, onsets = tt
    i = bisect.bisect_left(onsets, cut - 0.02)
    if i >= len(ws):
        return None
    w = ws[i]
    left, onset = _speech_before(st, w)
    return (onset - left if left is not None else 9.9), onset - cut, w.word


def buckets(xs):
    n = len(xs) or 1
    return (f"< 0.05 с: {sum(1 for x in xs if x < 0.05)}, < 0.15 с: {sum(1 for x in xs if x < 0.15)}, "
            f"< 0.30 с: {sum(1 for x in xs if x < 0.30)} из {len(xs)} "
            f"(медиана {sorted(xs)[len(xs) // 2] if xs else 0:.2f} с)" if xs else "нет данных")


def main(paths) -> int:
    for p in paths:
        m = json.loads(Path(p).read_text(encoding="utf-8"))
        stem = Path(m.get("source", "")).stem
        firsts, bodies = [], []
        print(f"\n=== {p} (источник {stem})")
        for r in m.get("reels") or []:
            segs = r.get("segments") or [{"start": r["start"], "end": r["end"]}]
            co = r.get("cold_open")
            a = pause_at(stem, float(co["start"]) if co else float(segs[0]["start"]))
            b = pause_at(stem, float(segs[0]["start"])) if co else None
            if a is None:
                print(f"  {r['id']}: нет данных")
                continue
            firsts.append(a[0])
            line = f"  {r['id']}: первый звук — пауза перед «{a[2]}» {a[0]:.2f} с (рез за {a[1]:.2f} с до слова)"
            if b is not None:
                bodies.append(b[0])
                line += f"; тело — пауза перед «{b[2]}» {b[0]:.2f} с"
            print(line)
        print(f"  первый звук: {buckets(firsts)}")
        if bodies:
            print(f"  начало тела после холодного старта: {buckets(bodies)}")
    own = []
    for mp in sorted(glob.glob("manifests/*.json")):
        try:
            m = json.load(open(mp, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(m, dict) or m.get("selection_source") != "human":
            continue
        stem = Path(mp).stem
        for r in m.get("reels") or []:
            segs = r.get("segments") or [{"start": r["start"], "end": r["end"]}]
            co = r.get("cold_open")
            a = pause_at(stem, float(co["start"]) if co else float(segs[0]["start"]))
            if a is not None:
                own.append(a[0])
    print(f"\n=== клипы владельца (манифесты human), первый звук: {buckets(own)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
