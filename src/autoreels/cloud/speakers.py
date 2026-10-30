"""M165: who speaks when — the speaker map of a source (transcripts/<stem>.speakers.json) and what it says about
sentences. The main speaker is the one with the most talk; everyone else is «the interviewer» (host, audience).

The map is made by pyannote speaker diarization (tools/diarize.py, its own environment — torch is not a project
dependency) or imported from an existing diarization (m141). It is a layer like the speech map: the code only reads it.
config/r0.yaml autocut.interviewer decides what the automatic path does with the interviewer's sentences:
  ""    — nothing (the map is not read; as before M165);
  "off" — a clip never contains them;
  "on"  — they may stay when they give context (a question that opens the clip) or a real exchange (a joke, a laugh);
          the speaker must carry the clip (more than half of its time).
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

SPEAKERS_VERSION = 1


def main_speaker(turns) -> str | None:
    talk: dict[str, float] = defaultdict(float)
    for a, b, s in turns:
        talk[str(s)] += max(0.0, float(b) - float(a))
    return max(talk, key=talk.get) if talk else None


def build(turns, source_sha256: str, origin: str = "") -> dict:
    t = [[round(float(a), 3), round(float(b), 3), str(s)] for a, b, s in turns if float(b) > float(a)]
    t.sort()
    return {"version": SPEAKERS_VERSION, "source_sha256": source_sha256, "main": main_speaker(t), "turns": t,
            "origin": origin}


def write(path: Path, data: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def load(path: Path, source_sha256: str) -> dict | None:
    """The map when it is this source's and of this version; None otherwise."""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if d.get("version") != SPEAKERS_VERSION or d.get("source_sha256") != source_sha256 or not d.get("turns"):
        return None
    return d


def span_speaker(a: float, b: float, sp: dict) -> str | None:
    """«main» | «other» for the stretch a…b (who covers more of it); None when the map is silent there."""
    main, cov_main, cov_other = sp.get("main"), 0.0, 0.0
    for ta, tb, s in sp["turns"]:
        if tb <= a:
            continue
        if ta >= b:
            break
        o = min(b, tb) - max(a, ta)
        if o > 0:
            if s == main:
                cov_main += o
            else:
                cov_other += o
    if cov_main + cov_other <= 0:
        return None
    return "other" if cov_other > cov_main else "main"


def other_refs(sent_spans: dict, sp: dict) -> set:
    """{ref: (t0, t1)} → refs of the sentences the interviewer says."""
    return {r for r, (a, b) in sent_spans.items() if span_speaker(float(a), float(b), sp) == "other"}


def interviewer_rule(mode: str) -> str:
    """The scenarist's extra rule for sentences marked «[ведущий]»."""
    if mode == "off":
        return (" Sentences marked «[ведущий]» are the interviewer: never use them — no reel contains one.")
    if mode == "on":
        return (" Sentences marked «[ведущий]» are the interviewer. Use one only when it gives the reel context (a "
                "question that opens it and the speaker answers) or a real exchange (a joke, a laugh, a warm reaction) "
                "that makes the reel better; the speaker must carry the reel — most of its time is his.")
    return ""
