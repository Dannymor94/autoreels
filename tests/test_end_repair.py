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


def _r0_cfg(max_end_search_sec: float = 12.0, end_repair_max_extend_sec: float = 6.0):
    cfg = MagicMock()
    cfg.max_end_search_sec = max_end_search_sec
    cfg.end_repair_max_extend_sec = end_repair_max_extend_sec
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
    assert r.end == pytest.approx(4.8 + 0.35)
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
    assert r.end == pytest.approx(2.0 + 0.35)
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
# window-edge: sentence starts inside window but ends outside → back off
# ---------------------------------------------------------------------------

def test_repair_end_backs_off_when_sentence_straddles_window():
    """Next complete sentence's last word ends outside the search window → treat as not found."""
    words = [
        _w(1.0, 1.5, "Я"), _w(1.6, 2.0, "думаю."),      # complete sentence [1]
        _w(2.1, 2.5, "потому"), _w(2.6, 3.0, "что"),      # incomplete sentence [2] — reel ends here
        _w(3.1, 3.5, "это"), _w(3.6, 20.0, "важно."),     # complete sentence [3]: starts inside window (max_search=12),
                                                            # but t1=20.0 OUTSIDE window (end=3.0+12=15.0)
    ]
    repair = _get_repair()
    r = _reel(1.0, 3.0)
    repair(r, words, r0_cfg=_r0_cfg(max_end_search_sec=12.0), explicit_e=False)
    # Should back off to sentence [1] (t1=2.0 + pad), not extend to sentence [3]
    assert r.end == pytest.approx(2.0 + 0.35)
    assert r.end_snap_reason == "repaired_to_sentence"
    assert not r.open_thought


# ---------------------------------------------------------------------------
# max_extend_sec: sentence is within window but exceeds extension limit → back off
# ---------------------------------------------------------------------------

def test_repair_end_backs_off_when_extension_too_long():
    """Next complete sentence is within window but > end_repair_max_extend_sec → back off."""
    words = [
        _w(1.0, 1.5, "Я"), _w(1.6, 2.0, "думаю."),      # complete sentence [1]
        _w(2.1, 2.5, "потому"), _w(2.6, 3.0, "что"),      # incomplete sentence [2] — reel ends here
        _w(4.0, 4.5, "это"), _w(4.6, 9.5, "важно."),      # complete sentence [3]: t1=9.5, extension=9.5-3.0=6.5 > 6.0
    ]
    repair = _get_repair()
    r = _reel(1.0, 3.0)
    repair(r, words, r0_cfg=_r0_cfg(max_end_search_sec=12.0, end_repair_max_extend_sec=6.0), explicit_e=False)
    # Extension would be 9.5-3.0=6.5 > 6.0 → back off to sentence [1] (t1=2.0 + pad)
    assert r.end == pytest.approx(2.0 + 0.35)
    assert not r.open_thought


def test_repair_end_extends_when_within_limit():
    """Next complete sentence is within window AND within extension limit → extend."""
    words = [
        _w(1.0, 1.5, "Я"), _w(1.6, 2.0, "думаю."),      # complete sentence [1]
        _w(2.1, 2.5, "потому"), _w(2.6, 3.0, "что"),      # incomplete sentence [2] — reel ends here
        _w(4.0, 4.5, "это"), _w(4.6, 8.9, "важно."),      # complete sentence [3]: t1=8.9, extension=5.9 < 6.0
    ]
    repair = _get_repair()
    r = _reel(1.0, 3.0)
    repair(r, words, r0_cfg=_r0_cfg(max_end_search_sec=12.0, end_repair_max_extend_sec=6.0), explicit_e=False)
    assert r.end == pytest.approx(8.9 + 0.35)
    assert not r.open_thought


# ---------------------------------------------------------------------------
# subtitle_gate: set to next word's t0 to prevent Whisper overlap contamination
# ---------------------------------------------------------------------------

def test_repair_end_subtitle_gate_is_next_word_t0():
    """When extending, subtitle_gate = next_word.t0, not s[-1].t1."""
    words = [
        _w(1.0, 1.5, "потому"), _w(1.6, 3.0, "что"),     # incomplete — reel ends here
        _w(3.5, 5.0, "это"), _w(4.9, 5.5, "важно."),      # complete next sentence
        _w(5.4, 6.0, "Следующая"),                         # next word: t0=5.4 overlaps with "важно." t1=5.5
    ]
    repair = _get_repair()
    r = _reel(1.0, 3.0)
    repair(r, words, r0_cfg=_r0_cfg(), explicit_e=False)
    assert r.end == pytest.approx(5.5 + 0.35)   # reel.end = t1 of chosen last word + pad
    # subtitle_gate should be next_word.t0 = 5.4, NOT 5.5
    assert r.subtitle_gate == pytest.approx(5.4)


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
