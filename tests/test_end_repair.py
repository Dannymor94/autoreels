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

def test_repair_end_explicit_e_stump_sets_gate_not_open_thought():
    """Explicit e: with prev complete sentence: gate set before stump, no open_thought."""
    words = [
        _w(1.0, 1.5, "Я"), _w(1.6, 2.0, "думаю."),
        _w(2.1, 2.5, "потому"), _w(2.6, 3.0, "что"),
    ]
    repair = _get_repair()
    r = _reel(1.0, 3.0)
    repair(r, words, r0_cfg=_r0_cfg(), explicit_e=True)
    assert r.end == pytest.approx(3.0)           # not moved
    assert r.subtitle_gate == pytest.approx(2.1) # gate before stump
    assert not r.open_thought


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


# ---------------------------------------------------------------------------
# smap-based end: use acoustic tail, not inflated Whisper t1 (Part 2)
# ---------------------------------------------------------------------------

def _minimal_smap(words_spec):
    """Build a minimal smap dict for testing.

    words_spec: list of (t0, audible_start, audible_end).
    boundaries: one entry per word (no untranscribed_speech).
    """
    smap_words = [
        {"t0": t0, "audible_start": a_start, "audible_end": a_end}
        for t0, a_start, a_end in words_spec
    ]
    boundaries = [{} for _ in smap_words]
    return {"words": smap_words, "boundaries": boundaries}


def test_repair_smap_extension_uses_acoustic_end():
    """With smap, extension end = acoustic tail, NOT inflated Whisper t1 + 0.35."""
    # Sentence 1: incomplete (reel ends here at t=3.0)
    # Sentence 2: complete, last word "важно." t0=4.5, t1=8.0 (inflated +2s from 6.0)
    # Acoustic: audible_end=4.95; next word at t0=6.0, audible_start=6.5
    # gap = 6.5 - 4.95 = 1.55 >= 0.35 → silence case: tail = 4.95 + 0.10 = 5.05
    words = [
        _w(1.0, 1.5, "Я"), _w(1.6, 3.0, "думаю"),        # incomplete sentence [1]
        _w(3.5, 4.5, "это"), _w(4.5, 8.0, "важно."),      # complete sentence [2], t1 inflated
        _w(6.0, 6.5, "Следующая"),                          # next word after sentence [2]
    ]
    smap = _minimal_smap([
        (1.0, 0.9, 1.4), (1.6, 1.55, 2.9),
        (3.5, 3.4, 4.4), (4.5, 4.45, 4.95),                # "важно.": ae=4.95
        (6.0, 6.5, 7.0),                                    # next word: audible_start=6.5
    ])
    repair = _get_repair()
    r = _reel(1.0, 3.0)
    repair(r, words, r0_cfg=_r0_cfg(), explicit_e=False, smap=smap)
    assert r.end_snap_reason == "repaired_to_sentence"
    # With smap: end = 4.95 + 0.10 = 5.05 (acoustic tail, NOT 8.0 + 0.35 = 8.35)
    assert r.end == pytest.approx(5.05, abs=0.01)
    assert r.end < 8.0  # must NOT be inflated-t1-based
    # subtitle_gate = audible_start of next word = 6.5
    assert r.subtitle_gate == pytest.approx(6.5)


def test_repair_smap_backoff_uses_acoustic_end():
    """With smap, back-off end = acoustic tail of last complete sentence, not inflated t1."""
    # Sentence 1: complete, last word "думаю." t0=1.6, t1=5.0 (inflated), ae=1.9
    # Sentence 2: incomplete, reel ends here
    # Next word after sentence [1]: t0=2.1, audible_start=2.0
    # gap = 2.0 - 1.9 = 0.1 < 0.35 → speech-next: tail = 2.0 - 0.10 = 1.9, max(1.9, 1.9+0.04)=1.94
    words = [
        _w(1.0, 1.5, "Я"), _w(1.6, 5.0, "думаю."),        # complete, t1 inflated
        _w(2.1, 2.5, "потому"), _w(2.6, 3.0, "что"),        # incomplete — reel ends here
    ]
    smap = _minimal_smap([
        (1.0, 0.9, 1.4), (1.6, 1.55, 1.9),                 # "думаю.": ae=1.9
        (2.1, 2.0, 2.4), (2.6, 2.55, 2.95),                 # "потому": audible_start=2.0
    ])
    repair = _get_repair()
    r = _reel(1.0, 3.0)
    repair(r, words, r0_cfg=_r0_cfg(), explicit_e=False, smap=smap)
    assert r.end_snap_reason == "repaired_to_sentence"
    # speech-next: tail = 2.0 - 0.10 = 1.90, max(1.90, 1.9+0.04=1.94) → 1.94
    assert r.end == pytest.approx(1.94, abs=0.02)
    assert r.end < 5.0  # must NOT be inflated-t1-based (5.0 + 0.35 = 5.35)


def test_repair_smap_fallback_when_word_not_in_smap():
    """When chosen word is absent from smap, falls back to Whisper t1 + _REPAIR_END_PAD."""
    words = [
        _w(1.0, 1.5, "Я"), _w(1.6, 3.0, "думаю"),
        _w(3.5, 4.5, "это"), _w(4.5, 5.0, "важно."),
        _w(6.0, 6.5, "Следующая"),
    ]
    # smap has no entry for "важно." (t0=4.5)
    smap = _minimal_smap([
        (1.0, 0.9, 1.4), (1.6, 1.55, 2.9),
        (3.5, 3.4, 4.4),
        # 4.5 intentionally absent
        (6.0, 6.5, 7.0),
    ])
    repair = _get_repair()
    r = _reel(1.0, 3.0)
    repair(r, words, r0_cfg=_r0_cfg(), explicit_e=False, smap=smap)
    assert r.end_snap_reason == "repaired_to_sentence"
    # Falls back to Whisper t1 + 0.35
    assert r.end == pytest.approx(5.0 + 0.35)


# ---------------------------------------------------------------------------
# explicit e: genuine open_thought (no prev complete sentence)
# ---------------------------------------------------------------------------

def test_repair_explicit_e_no_prev_complete_open_thought():
    """Explicit e: with NO previous complete sentence → open_thought=True."""
    words = [
        _w(1.0, 1.5, "потому"), _w(1.6, 2.0, "что"),
    ]
    repair = _get_repair()
    r = _reel(1.0, 2.0)
    repair(r, words, r0_cfg=_r0_cfg(), explicit_e=True)
    assert r.open_thought is True
    assert any("incomplete" in w for w in r.warnings)
    assert r.subtitle_gate is None


# ---------------------------------------------------------------------------
# _check_last_subtitle_word stump detection
# ---------------------------------------------------------------------------

def _get_check():
    import autoreels.__main__ as m
    return m._check_last_subtitle_word


def _reel_with_subs(start, end, gate, last_sub_t0, last_sub_word):
    from autoreels.core.models import Word
    r = _reel(start, end)
    r.subtitle_gate = gate
    r.subtitles = [Word(word=last_sub_word, t0=last_sub_t0, t1=last_sub_t0 + 0.3)]
    return r


def test_check_stump_fires():
    """Stump word after expected_last within gate raises [CONTENT]."""
    # Sentence: "думаю." at t0=1.6 (expected_last)
    # Stump: "потому" at t0=2.1
    # gate=3.0 (reel.end — repair not yet run), stump.t0=2.1 < gate
    tx_words = [
        _w(1.0, 1.5, "Я"), _w(1.6, 2.0, "думаю."),
        _w(2.1, 2.5, "потому"), _w(2.6, 3.0, "что"),
    ]
    r = _reel_with_subs(1.0, 3.0, gate=3.0, last_sub_t0=1.6, last_sub_word="думаю.")
    check = _get_check()
    with pytest.raises(ValueError, match=r"\[CONTENT\].*stump"):
        check(r, tx_words)


def test_check_no_stump_when_gate_before_stump():
    """After repair (gate = stump.t0), stump excluded from span → check passes."""
    tx_words = [
        _w(1.0, 1.5, "Я"), _w(1.6, 2.0, "думаю."),
        _w(2.1, 2.5, "потому"), _w(2.6, 3.0, "что"),
    ]
    # gate = stump.t0 = 2.1 → stump word has t0=2.1, condition t0 < 2.1 is False
    r = _reel_with_subs(1.0, 3.0, gate=2.1, last_sub_t0=1.6, last_sub_word="думаю.")
    check = _get_check()
    check(r, tx_words)  # must not raise
