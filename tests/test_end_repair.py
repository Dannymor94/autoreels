"""Tests for _repair_end_to_complete_sentence and the export …→ marker (Part 2 & 1)."""
import sys
import types
from unittest.mock import MagicMock

import pytest

from autoreels.core.models import Reel, Word


def _w(t0: float, t1: float, word: str) -> Word:
    return Word(word=word, t0=t0, t1=t1)


def _reel(start: float, end: float) -> Reel:
    return Reel(id="r01", start=start, end=end, score=80,
                hook="h", title="t", description="d", reason="r", topic="x")


def _r0_cfg(max_end_search_sec: float = 12.0):
    cfg = MagicMock()
    cfg.max_end_search_sec = max_end_search_sec
    return cfg


# Import the function from __main__ without running the module
def _get_repair():
    import importlib
    import autoreels.__main__ as m
    return m._repair_end_to_complete_sentence


# ---------------------------------------------------------------------------
# extend to next complete sentence
# ---------------------------------------------------------------------------

def test_repair_end_extends_to_next_complete_sentence():
    """Incomplete ending: extend to next complete sentence within search window."""
    words = [
        _w(1.0, 1.5, "Я"), _w(1.6, 2.0, "хочу"),
        _w(2.1, 2.5, "потому"), _w(2.6, 3.0, "что"),   # incomplete sentence [1]
        _w(3.5, 4.0, "это"), _w(4.1, 4.8, "важно."),   # complete sentence [2]
        _w(10.0, 10.5, "далеко"),                        # outside search window
    ]
    repair = _get_repair()
    r = _reel(1.0, 3.0)
    repair(r, words, r0_cfg=_r0_cfg(), explicit_e=False)
    assert r.end == pytest.approx(4.8)
    assert r.end_snap_reason == "repaired_to_sentence"
    assert not r.open_thought


# ---------------------------------------------------------------------------
# back off to previous complete sentence
# ---------------------------------------------------------------------------

def test_repair_end_backs_off_when_no_extension():
    """No complete sentence ahead: back off to last complete sentence in span."""
    words = [
        _w(1.0, 1.5, "Я"), _w(1.6, 2.0, "думаю."),    # complete sentence [1]
        _w(2.1, 2.5, "потому"), _w(2.6, 3.0, "что"),   # incomplete sentence [2]
        _w(20.0, 20.5, "далеко"),                        # outside 12s search window
    ]
    repair = _get_repair()
    r = _reel(1.0, 3.0)
    repair(r, words, r0_cfg=_r0_cfg(), explicit_e=False)
    assert r.end == pytest.approx(2.0)
    assert r.end_snap_reason == "repaired_to_sentence"
    assert not r.open_thought


# ---------------------------------------------------------------------------
# explicit e: → not moved, open_thought + warning
# ---------------------------------------------------------------------------

def test_repair_end_explicit_e_not_moved_sets_open_thought():
    """Explicit e: on incomplete sentence: end stays, open_thought=True, warning added."""
    words = [
        _w(1.0, 1.5, "Я"), _w(1.6, 2.0, "думаю."),
        _w(2.1, 2.5, "потому"), _w(2.6, 3.0, "что"),
    ]
    repair = _get_repair()
    r = _reel(1.0, 3.0)
    repair(r, words, r0_cfg=_r0_cfg(), explicit_e=True)
    assert r.end == pytest.approx(3.0)      # not moved
    assert r.open_thought is True
    assert any("incomplete" in w for w in r.warnings)


# ---------------------------------------------------------------------------
# explicit e: on complete sentence → nothing happens
# ---------------------------------------------------------------------------

def test_repair_end_explicit_e_complete_no_change():
    words = [
        _w(1.0, 1.5, "Я"), _w(1.6, 2.0, "думаю."),
    ]
    repair = _get_repair()
    r = _reel(1.0, 2.0)
    repair(r, words, r0_cfg=_r0_cfg(), explicit_e=True)
    assert r.end == pytest.approx(2.0)
    assert not r.open_thought
    assert r.warnings == []


# ---------------------------------------------------------------------------
# neither direction finds complete → open_thought
# ---------------------------------------------------------------------------

def test_repair_end_open_thought_when_no_complete_found():
    """Single incomplete sentence with nothing before it and nothing ahead → open_thought."""
    words = [
        _w(1.0, 1.5, "потому"), _w(1.6, 2.0, "что"),
    ]
    repair = _get_repair()
    r = _reel(1.0, 2.0)
    repair(r, words, r0_cfg=_r0_cfg(max_end_search_sec=1.0), explicit_e=False)
    assert r.open_thought is True


# ---------------------------------------------------------------------------
# export …→ marker (Part 1)
# ---------------------------------------------------------------------------

def test_numbered_sentences_marks_incomplete():
    """_numbered_sentences adds …→ to incomplete-sentence prefixes."""
    from autoreels.cloud.blocks import _numbered_sentences, CandidateBlock
    words = [
        _w(1.0, 1.5, "Я"), _w(1.6, 2.0, "думаю."),          # sentence 1 — complete
        _w(2.1, 2.5, "потому"), _w(2.6, 3.0, "что"),          # sentence 2 — incomplete
    ]
    block = CandidateBlock(id="b1", start=1.0, end=3.0, text="Я думаю. потому что",
                           boundary_reason="pause", duration=2.0)
    result = _numbered_sentences(block, words)
    assert "[1] Я думаю." in result
    assert "[2]…→ потому что" in result
    assert "[2] потому" not in result  # the plain [2] must not appear


def test_numbered_sentences_complete_no_marker():
    from autoreels.cloud.blocks import _numbered_sentences, CandidateBlock
    words = [
        _w(1.0, 1.5, "Я"), _w(1.6, 2.0, "думаю."),
        _w(2.1, 2.5, "это"), _w(2.6, 3.0, "важно."),
    ]
    block = CandidateBlock(id="b1", start=1.0, end=3.0, text="...", boundary_reason="pause", duration=2.0)
    result = _numbered_sentences(block, words)
    assert "…→" not in result
