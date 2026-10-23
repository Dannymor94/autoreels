#!/usr/bin/env python3
"""M141 step B (project venv, read-only): what the speaker map says about the owner's clips and the host's questions.

Per source with data/cache/m141/<stem>.diar.json: speakers and their share of talk (the main one = most talk);
owner clips (manifests, selection_source human): share of clip time spoken by the main speaker, clips with another
speaker inside, clips that start on another speaker; transcript sentences that start on ANOTHER speaker after the main
one and end with «?» — the host's questions — with 8 examples to check by ear, and how many of them the pause rule of
the code would catch (pause ≥ host_turn_min_pause before the sentence and «вы/ты» in it).
    .venv/bin/python handoff/m141/diar_stats.py
"""
from __future__ import annotations

import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "src")
from autoreels import __main__ as M  # noqa: E402
from autoreels.core.config import load_r0_config  # noqa: E402
from autoreels.core.models import Manifest  # noqa: E402

YOU = ("вы", "ты", "вам", "тебе", "вас", "тебя", "ваш", "твой", "ваше", "твоё")


def speaker_at(turns, t):
    best, cov = None, 0.0
    for a, b, s in turns:
        if a <= t < b and (b - a) > cov:
            best, cov = s, b - a
    return best


def main() -> int:
    r0 = load_r0_config(Path("config/r0.yaml"))
    tot = defaultdict(int)
    for dp in sorted(glob.glob("data/cache/m141/*.diar.json")):
        d = json.loads(Path(dp).read_text(encoding="utf-8"))
        stem, turns = d["stem"], d["turns"]
        talk = defaultdict(float)
        for a, b, s in turns:
            talk[s] += b - a
        if not talk:
            continue
        main_spk = max(talk, key=talk.get)
        all_t = sum(talk.values())
        print(f"\n=== {stem} (source_kind {d.get('source_kind')}): говорящих {len(talk)}; доли: "
              + ", ".join(f"{s} {v / all_t:.0%}" for s, v in sorted(talk.items(), key=lambda kv: -kv[1])))
        mp = Path("manifests") / f"{stem}.json"
        m = Manifest.model_validate_json(mp.read_text(encoding="utf-8"))
        clips = [[(float(s.start), float(s.end)) for s in (r.segments or [])] or [(float(r.start), float(r.end))]
                 for r in m.reels]
        other_in, other_start, share = 0, 0, []
        for c in clips:
            dur = sum(b - a for a, b in c)
            main_t = 0.0
            others = False
            for a, b in c:
                for ta, tb, s in turns:
                    ov = max(0.0, min(b, tb) - max(a, ta))
                    if ov > 0 and s == main_spk:
                        main_t += ov
                    elif ov > 0.8:
                        others = True
            share.append(main_t / max(1e-9, dur))
            other_in += others
            other_start += speaker_at(turns, c[0][0] + 0.3) not in (main_spk, None)
        print(f"клипы владельца {len(clips)}: доля главного голоса в среднем {sum(share) / max(1, len(share)):.0%}; "
              f"с другим голосом внутри {other_in}; начинаются с другого голоса {other_start}")
        t, _ = M._resolve_transcript(m, Path("data/cache"))
        if t is None:
            print("транскрипт не найден — вопросы ведущего не посчитаны")
            continue
        words = t.words
        sents, cur = [], []
        for w in words:
            cur.append(w)
            if w.word.rstrip().endswith((".", "?", "!", "…")):
                sents.append(cur)
                cur = []
        q_host, caught, ex = 0, 0, []
        prev_end = None
        for s in sents:
            spk = speaker_at(turns, s[0].t0 + 0.1)
            text = " ".join(w.word for w in s)
            if spk not in (main_spk, None) and text.rstrip().endswith("?"):
                q_host += 1
                pause = (s[0].t0 - prev_end) if prev_end is not None else 9.9
                you = any(w.word.lower().strip(",.?!") in YOU for w in s)
                caught += int(pause >= r0.host_turn_min_pause and you)
                if len(ex) < 8:
                    ex.append(f"  {s[0].t0:7.1f} с [{'пойман' if pause >= r0.host_turn_min_pause and you else 'НЕ пойман'}] {text[:110]}")
            prev_end = s[-1].t1
        print(f"вопросов другим голосом: {q_host}; правило «пауза + вы/ты» поймало бы {caught}")
        print("\n".join(ex))
        tot["clips"] += len(clips); tot["other_in"] += other_in; tot["q"] += q_host; tot["caught"] += caught
    print(f"\n=== ВСЕГО: клипов {tot['clips']}, с другим голосом внутри {tot['other_in']}; "
          f"вопросов другим голосом {tot['q']}, правило поймало бы {tot['caught']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
