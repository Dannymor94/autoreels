"""Tests for min_score and dedup on the blocks auto path (_stage_select_blocks)."""
import json
import pytest

from autoreels.cloud.select import dedup, filter_by_score
from autoreels.core.models import Reel


def _reel(rid, start, end, score):
    return Reel(id=rid, start=start, end=end, score=score,
                hook="hook", title="", description="")


# ----------------------------------------------------------------- min_score

def test_filter_by_score_drops_below_threshold():
    reels = [_reel("a", 0, 30, 80), _reel("b", 40, 70, 60), _reel("c", 80, 110, 40)]
    kept = filter_by_score(reels, min_score=65)
    assert [r.id for r in kept] == ["a"]  # 60 < 65 and 40 < 65, both dropped


def test_filter_by_score_keeps_all_when_all_above():
    reels = [_reel("a", 0, 30, 90), _reel("b", 40, 70, 70)]
    kept = filter_by_score(reels, min_score=65)
    assert len(kept) == 2


def test_filter_by_score_drops_all_when_all_below():
    reels = [_reel("a", 0, 30, 30), _reel("b", 40, 70, 50)]
    kept = filter_by_score(reels, min_score=65)
    assert kept == []


# ----------------------------------------------------------------- dedup

def test_dedup_keeps_higher_llm_score():
    """Two overlapping reels: higher score wins."""
    hi = _reel("hi", 0.0, 60.0, 90)
    lo = _reel("lo", 5.0, 65.0, 70)
    dropped = []
    kept = dedup([hi, lo], overlap_threshold=0.5, dropped=dropped)
    assert [r.id for r in kept] == ["hi"]
    assert len(dropped) == 1
    assert dropped[0]["id"] == "lo"
    assert "overlap_dedup" in dropped[0]["reason"]


def test_dedup_no_overlap_keeps_both():
    a = _reel("a", 0.0, 30.0, 80)
    b = _reel("b", 60.0, 90.0, 70)
    kept = dedup([a, b], overlap_threshold=0.5)
    assert len(kept) == 2


def test_dedup_exact_threshold_kept():
    """Overlap == threshold: block is NOT dropped (> not >=)."""
    a = _reel("a", 0.0, 60.0, 80)
    b = _reel("b", 30.0, 90.0, 70)  # overlap=30/60=0.5 for b over a
    kept = dedup([a, b], overlap_threshold=0.5)
    assert len(kept) == 2
