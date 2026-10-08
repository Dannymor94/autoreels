"""Tests for build_manual_plan (REEL_SPEC §1–§4).

Compares the plan produced from the installed IMG_6848 manifest against
benchmarks/golden/img6848_plan.yaml.  The words fixture at
benchmarks/fixtures/img6848_words.json is derived from the same transcript
and committed alongside the golden.

Sentence counts per window/shot are verified; exact 1-based plan indices are
not compared because the golden uses review-export numbering while plan.py
uses plan-internal numbering (they differ by the s: offset).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

REPO = Path(__file__).parent.parent
GOLDEN = REPO / "benchmarks" / "golden" / "img6848_plan.yaml"
MANIFEST = REPO / "manifests" / "IMG_6848.json"
WORDS_FIXTURE = REPO / "benchmarks" / "fixtures" / "img6848_words.json"


def _load_words():
    from autoreels.core.models import Word
    data = json.loads(WORDS_FIXTURE.read_text(encoding="utf-8"))
    return [Word(word=d["word"], t0=d["t0"], t1=d["t1"], emph=d.get("emph", False))
            for d in data]


def _cfg():
    ap = SimpleNamespace(end_air_sec=0.30, end_video_fade_sec=0.25)
    return SimpleNamespace(audio_processing=ap)


@pytest.mark.parametrize("reel_id", ["r01", "r02", "r03", "r04", "r05", "r06", "r07", "r08"])
def test_img6848_plan(reel_id):
    """build_manual_plan for IMG_6848 reel matches golden window+shot structure."""
    from autoreels.core.models import Manifest
    from autoreels.core.plan import build_manual_plan

    golden_data = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    expected = next(r for r in golden_data["reels"] if r["id"] == reel_id)

    manifest = Manifest.model_validate_json(MANIFEST.read_text(encoding="utf-8"))
    reel = next(r for r in manifest.reels if r.id == reel_id)
    words = _load_words()

    plan = build_manual_plan(reel, words, None, _cfg())

    exp_windows = expected["body_windows"]
    assert len(plan.body_windows) == len(exp_windows), (
        f"{reel_id}: expected {len(exp_windows)} body windows, "
        f"got {len(plan.body_windows)}: {[list(bw.sentence_indices) for bw in plan.body_windows]}"
    )
    for wi, (pbw, ebw) in enumerate(zip(plan.body_windows, exp_windows)):
        assert len(pbw.sentence_indices) == len(ebw), (
            f"{reel_id} window[{wi}]: expected {len(ebw)} sentences, "
            f"got {len(pbw.sentence_indices)}"
        )

    exp_shots = expected["shots"]
    assert len(plan.shots) == len(exp_shots), (
        f"{reel_id}: expected {len(exp_shots)} shot spans, "
        f"got {len(plan.shots)}: {[(s.shot, s.sentence_indices, s.reason) for s in plan.shots]}"
    )
    for si, (ps, es) in enumerate(zip(plan.shots, exp_shots)):
        assert ps.shot == es["shot"], (
            f"{reel_id} shot[{si}]: expected {es['shot']!r}, got {ps.shot!r}"
        )
        assert ps.reason == es["reason"], (
            f"{reel_id} shot[{si}]: expected reason {es['reason']!r}, got {ps.reason!r}"
        )
        assert len(ps.sentence_indices) == len(es["sentences"]), (
            f"{reel_id} shot[{si}] ({ps.shot}/{ps.reason}): "
            f"expected {len(es['sentences'])} sentences, got {len(ps.sentence_indices)}"
        )

    if expected["cold_open"] is None:
        assert plan.cold_open_source is None, f"{reel_id}: expected no cold_open"
    else:
        assert plan.cold_open_source is not None, f"{reel_id}: expected cold_open present"
        assert plan.replayed_in_body == expected["cold_open"]["replayed_in_body"], (
            f"{reel_id}: replayed_in_body expected {expected['cold_open']['replayed_in_body']}, "
            f"got {plan.replayed_in_body}"
        )
