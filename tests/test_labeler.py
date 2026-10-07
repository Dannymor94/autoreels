"""Tests for --labeler owner|assistant attribution in blocks --apply."""
import json
from pathlib import Path

import pytest

from autoreels.cloud.blocks import CandidateBlock, make_dataset_row


def _block(bid: str = "abc123") -> CandidateBlock:
    b = CandidateBlock(id=bid, start=0.0, end=10.0, duration=10.0,
                       text="Тест.", boundary_reason="sentence")
    b.heuristic_score = 0.5
    b.score_breakdown = {}
    return b


# ---------------------------------------------------------------------------
# Unit tests for make_dataset_row
# ---------------------------------------------------------------------------

def test_make_dataset_row_default_is_owner():
    """Default labeler must be 'owner', not 'assistant'."""
    row = make_dataset_row(_block(), 80, "stem")
    assert row["labeler"] == "owner"


def test_make_dataset_row_explicit_owner():
    row = make_dataset_row(_block(), 80, "stem", labeler="owner")
    assert row["labeler"] == "owner"


def test_make_dataset_row_assistant():
    row = make_dataset_row(_block(), 80, "stem", labeler="assistant")
    assert row["labeler"] == "assistant"


def test_make_dataset_row_no_hardcoded_assistant():
    """Ensure 'assistant' is not hard-coded — two calls with different labeler differ."""
    r1 = make_dataset_row(_block(), 80, "stem", labeler="owner")
    r2 = make_dataset_row(_block(), 80, "stem", labeler="assistant")
    assert r1["labeler"] != r2["labeler"]
