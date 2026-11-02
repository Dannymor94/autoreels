"""M203: how often the key-word rule (cloud/autocut.keywords_rule) hits the owner's own k: words.

The reference is the owner's marks in manifests/<source>.json: the subtitle words with emph (68 clips, 135 words of the 7
sources). A clip's sentences are its subtitle words cut at . ! ? …. Three pickers, n words per clip:
  rule        — the rule on the text (what keywords_source: rule does without the intonation map);
  rule+voice  — the rule with the words the voice draws out (keywords_rule_voice), when transcripts/<source>.prosody.json
                is there (the Mac); a subtitle word takes the duration of the intonation word starting within 0.2 s;
  random      — a random content word per clip (20 seeds), the floor.
A hit is the owner's very word (the same subtitle word). Read only.
Run from the project root: .venv/bin/python tools/kw_rule_check.py [--n 2|owner|config]"""
from __future__ import annotations

import argparse
import bisect
import json
import random
import re
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from autoreels.cloud.autocut import _KEY_STOP, _KW_POS, _kw_morph, _kw_norm, keywords_rule, voice_stressed  # noqa: E402

SOURCES = ("disko_beach_p1", "disko_beach_p2", "disko_beach_p3", "day_yoga_p1", "day_yoga_p2",
           "prew_isaev_anna", "prew_isaev_danny")
_END = re.compile(r"[.!?…][»\"')]*$")


def clip_sentences(words: list[dict]) -> list[list[dict]]:
    out, cur = [], []
    for w in words:
        cur.append(w)
        if _END.search(w["word"]):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _dur_lookup(stem: str):
    p = ROOT / "transcripts" / f"{stem}.prosody.json"
    if not p.is_file():
        return None
    words = sorted((float(w["t0"]), w.get("dur")) for w in json.loads(p.read_text(encoding="utf-8")).get("words") or [])
    t0s = [t for t, _ in words]

    def dur_of(word):
        i = bisect.bisect_left(t0s, float(word.t0))
        best = min((j for j in (i - 1, i) if 0 <= j < len(words)), key=lambda j: abs(t0s[j] - word.t0), default=None)
        return words[best][1] if best is not None and abs(t0s[best] - word.t0) <= 0.2 else None
    return dur_of


def _n_for(mode: str, owner: int, sec: float) -> int:
    if mode == "owner":
        return owner
    if mode == "config":
        return min(4, max(1, round(sec / 12)))
    return int(mode)


def _content(word: str) -> bool:
    if sum(c.isalpha() for c in word) < 3 or word in _KEY_STOP or not all(c.isalnum() or c == "-" for c in word):
        return False
    m = _kw_morph()
    return m is None or m.parse(word)[0].tag.POS in _KW_POS


def _hits(sents: list[list[dict]], picks: list[tuple[str, str]]) -> int:
    """Picks are (sentence index as ref, normalized word): a hit is an owner emph word of that sentence and that form."""
    h = 0
    for ref, word in picks:
        se = sents[int(ref)]
        h += any(w.get("emph") and _kw_norm(w["word"]) == word for w in se)
    return h


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", default="2", help="words per clip: a number, owner (as many as the owner marked), config")
    a = ap.parse_args(argv)
    tot = {"rule": [0, 0], "rule+voice": [0, 0], "random": [0.0, 0]}
    owner_words = clips = 0
    voice_sources = []
    for stem in SOURCES:
        mf = ROOT / "manifests" / f"{stem}.json"
        if not mf.is_file():
            print(f"  {stem}: нет манифеста")
            continue
        dur_of = _dur_lookup(stem)
        if dur_of is not None:
            voice_sources.append(stem)
        for reel in json.loads(mf.read_text(encoding="utf-8")).get("reels") or []:
            words = reel.get("subtitles") or []
            own = sum(1 for w in words if w.get("emph"))
            if not own:
                continue
            clips += 1
            owner_words += own
            sents = clip_sentences(words)
            rows = [(str(i), " ".join(w["word"] for w in se)) for i, se in enumerate(sents)]
            n = _n_for(a.n, own, words[-1]["t1"] - words[0]["t0"])
            p = keywords_rule(rows, n=n)
            tot["rule"][0] += _hits(sents, p)
            tot["rule"][1] += len(p)
            if dur_of is not None:
                objs = [[SimpleNamespace(word=w["word"], t0=w["t0"]) for w in se] for se in sents]
                v = [voice_stressed(o, dur_of) for o in objs]
                pv = keywords_rule(rows, n=n, voiced=v)
                tot["rule+voice"][0] += _hits(sents, pv)
                tot["rule+voice"][1] += len(pv)
            pool = [(str(i), _kw_norm(w["word"])) for i, se in enumerate(sents) for w in se if _content(_kw_norm(w["word"]))]
            for seed in range(20):
                pr = random.Random(seed).sample(pool, min(n, len(pool)))
                tot["random"][0] += _hits(sents, pr) / 20
                tot["random"][1] += len(pr) / 20
    print(f"эталон: клипов с k: {clips}, слов владельца {owner_words}; n = {a.n}")
    for k, (h, t) in tot.items():
        if t:
            print(f"  {k:11} выбрано {t:.0f}, попало в слово владельца {h:.0f} — {100 * h / t:.0f} %")
        elif k == "rule+voice":
            print("  rule+voice  нет transcripts/<источник>.prosody.json — замер голоса на этой машине невозможен")
    if voice_sources and len(voice_sources) < len(SOURCES):
        print(f"  голос замерен только для: {', '.join(voice_sources)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
