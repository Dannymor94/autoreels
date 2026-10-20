"""M123: a real answer of the scenarist (Claude Sonnet on IMG_6848, recorded by the agent in m123) parses in the format
the prompt asks — every reel line gives sentences in the talk's numbering; no reel line is lost to the format."""
from __future__ import annotations

import re
from pathlib import Path

from autoreels.cloud.scenario import expand_refs, parse_scenarios

FIX = Path(__file__).parent / "fixtures" / "scenario_raw_IMG_6848.txt"


def test_recorded_scenarist_answer_parses():
    raw = FIX.read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if re.match(r"^\s*`*M\d*\s*\|", ln)]
    assert lines, "the recorded answer has no reel lines"
    known = {r for ln in lines for r in (expand_refs(ln.split("|")[1]) or [])}
    scens, bad = parse_scenarios(raw, known)
    assert not [b for b in bad if b.startswith("не разобрать")]
    assert len(scens) + sum(1 for b in bad if "повторяется" in b) == len(lines)
    assert all(s["title"] and s["why"] for s in scens)
