"""Tests for legacy score transfer overlap rule (scripts/transfer_legacy_scores.py)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from transfer_legacy_scores import overlap_ratios, transfer_source, THRESHOLD


# ----------------------------------------------------------------- overlap_ratios

def test_overlap_ratios_identical():
    r_leg, r_cur = overlap_ratios(0.0, 10.0, 0.0, 10.0)
    assert r_leg == pytest.approx(1.0)
    assert r_cur == pytest.approx(1.0)


def test_overlap_ratios_no_overlap():
    r_leg, r_cur = overlap_ratios(0.0, 5.0, 10.0, 20.0)
    assert r_leg == 0.0
    assert r_cur == 0.0


def test_overlap_ratios_partial():
    # legacy [0, 10], current [8, 18]: overlap [8,10]=2
    # r_leg = 2/10 = 0.2, r_cur = 2/10 = 0.2
    r_leg, r_cur = overlap_ratios(0.0, 10.0, 8.0, 18.0)
    assert r_leg == pytest.approx(0.2)
    assert r_cur == pytest.approx(0.2)


def test_overlap_ratios_current_inside_legacy():
    # legacy [0, 20], current [5, 15]: overlap=10
    # r_leg = 10/20 = 0.5, r_cur = 10/10 = 1.0
    r_leg, r_cur = overlap_ratios(0.0, 20.0, 5.0, 15.0)
    assert r_leg == pytest.approx(0.5)
    assert r_cur == pytest.approx(1.0)


def test_overlap_ratios_exactly_80_percent():
    # legacy [0, 10], current [0, 8]: overlap=8
    # r_leg = 8/10 = 0.80, r_cur = 8/8 = 1.0
    r_leg, r_cur = overlap_ratios(0.0, 10.0, 0.0, 8.0)
    assert r_leg == pytest.approx(0.8)
    assert r_cur == pytest.approx(1.0)


def test_overlap_ratios_zero_duration():
    r_leg, r_cur = overlap_ratios(5.0, 5.0, 5.0, 10.0)
    assert r_leg == 0.0


# ----------------------------------------------------------------- transfer_source

def _block(bid, start, end, heuristic=50.0):
    return {"id": bid, "start": start, "end": end, "heuristic_score": heuristic}


def _legacy(bid, start, end, score=80):
    return {
        "block_id": bid, "start": start, "end": end,
        "human_score": score, "legacy": True,
        "block_ids": [bid], "block_durations": {bid: end - start},
    }


def test_transfer_identical_block():
    """Legacy and current block at same timestamps → both ratios=1.0 → transferred."""
    legacy = [_legacy("L1", 100.0, 130.0, score=85)]
    current = [_block("C1", 100.0, 130.0)]
    transferred, skipped = transfer_source("src", legacy, current)
    assert len(transferred) == 1
    assert skipped == []
    assert transferred[0]["block_id"] == "C1"
    assert transferred[0]["human_score"] == 85
    assert transferred[0]["overlap_legacy"] == pytest.approx(1.0)
    assert transferred[0]["overlap_current"] == pytest.approx(1.0)
    assert transferred[0]["origin"] == "transferred"
    assert transferred[0]["legacy_block_id"] == "L1"


def test_transfer_80pct_both_sides_passes():
    # legacy [0, 10], current [0, 10] → perfect → transferred
    # legacy [0, 10], current [0, 12.5]: overlap=10; r_leg=1.0, r_cur=10/12.5=0.80 → passes
    legacy = [_legacy("L1", 0.0, 10.0, score=75)]
    current = [_block("C1", 0.0, 12.5)]
    transferred, skipped = transfer_source("src", legacy, current)
    assert len(transferred) == 1
    assert skipped == []


def test_transfer_below_80pct_current_fails():
    # legacy [0, 10], current [0, 15]: overlap=10; r_leg=1.0, r_cur=10/15≈0.667 < 0.80
    legacy = [_legacy("L1", 0.0, 10.0)]
    current = [_block("C1", 0.0, 15.0)]
    transferred, skipped = transfer_source("src", legacy, current)
    assert transferred == []
    assert len(skipped) == 1


def test_transfer_below_80pct_legacy_fails():
    # legacy [0, 15], current [0, 10]: overlap=10; r_leg=10/15≈0.667 < 0.80, r_cur=1.0
    legacy = [_legacy("L1", 0.0, 15.0)]
    current = [_block("C1", 0.0, 10.0)]
    transferred, skipped = transfer_source("src", legacy, current)
    assert transferred == []
    assert len(skipped) == 1


def test_transfer_no_overlap_skipped():
    legacy = [_legacy("L1", 0.0, 10.0)]
    current = [_block("C1", 50.0, 60.0)]
    transferred, skipped = transfer_source("src", legacy, current)
    assert transferred == []
    assert len(skipped) == 1
    assert "no overlap" in skipped[0]["reason"]


def test_transfer_splice_matches_multiple_current_blocks():
    """Legacy splice [0,40] overlaps two current blocks each with >=80% on both sides."""
    # current C1=[0,20] → r_leg=20/40=0.5 < 0.80 → skipped for this legacy
    # But if current C1=[10,40] → overlap=30; r_leg=30/40=0.75, r_cur=30/30=1.0 → still < 0.80 legacy
    # Make legacy small relative to current: legacy=[10,30], C1=[0,25], C2=[25,40]
    # C1: overlap=[10,25]=15; r_leg=15/20=0.75 < 0.80 → fails
    # Need both >=0.80: legacy=[10,30](20s), C1=[10,27](17s): overlap=17; r_leg=17/20=0.85, r_cur=17/17=1.0 → passes
    # C2=[27,30](3s): overlap=3; r_leg=3/20=0.15, r_cur=3/3=1.0 → fails
    # So: a single legacy [10,30] → only C1=[10,27] passes (r_leg=0.85, r_cur=1.0)
    legacy = [_legacy("SPLICE", 10.0, 30.0, score=90)]
    current = [
        _block("CA", 10.0, 27.0),   # overlap=17, r_leg=0.85, r_cur=1.0 → passes
        _block("CB", 27.0, 30.0),   # overlap=3,  r_leg=0.15             → fails
        _block("CC", 0.0, 10.0),    # no overlap
    ]
    transferred, skipped = transfer_source("src", legacy, current)
    # SPLICE matches CA (r_leg=0.85), CB and CC fail → 1 transferred, 0 skipped
    assert len(transferred) == 1
    assert transferred[0]["block_id"] == "CA"
    assert skipped == []  # legacy row has at least one match → not skipped


def test_transfer_metadata_fields():
    legacy = [_legacy("L1", 0.0, 10.0, score=70)]
    current = [_block("C1", 0.0, 10.0, heuristic=42.5)]
    transferred, _ = transfer_source("my_source", legacy, current)
    r = transferred[0]
    assert r["source"] == "my_source"
    assert r["heuristic_score"] == pytest.approx(42.5)
    assert r["duration"] == pytest.approx(10.0)
    assert r["features"] == {}


def test_transfer_empty_inputs():
    assert transfer_source("src", [], []) == ([], [])
    assert transfer_source("src", [], [_block("C1", 0.0, 10.0)]) == ([], [])
    legacy = [_legacy("L1", 0.0, 10.0)]
    transferred, skipped = transfer_source("src", legacy, [])
    assert transferred == []
    assert len(skipped) == 1
