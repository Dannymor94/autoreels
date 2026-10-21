"""M123: a real answer of the scenarist (Claude Sonnet on IMG_6848, recorded by the agent in m123) parses — every reel
line gives sentences in the talk's numbering; no reel line is lost to the format (the last one may be cut off when the
answer hits max_tokens)."""
from __future__ import annotations

from pathlib import Path

from autoreels.cloud.scenario import REEL_LINE, expand_refs, parse_scenarios

FIX = Path(__file__).parent / "fixtures" / "scenario_raw_IMG_6848.txt"


def test_recorded_scenarist_answer_parses():
    raw = FIX.read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if REEL_LINE.match(ln)]
    assert lines, "the recorded answer has no reel lines"
    known = {r for ln in lines for r in (expand_refs(ln.split("|")[1]) or [])}
    scens, bad = parse_scenarios(raw, known)
    assert len(scens) + len(bad) == len(lines)
    assert len(bad) <= 1 + sum(1 for b in bad if "повторяется" in b)
    assert all(s["title"] and s["why"] for s in scens[:-1])
