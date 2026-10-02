"""Tests for _check_last_subtitle_word."""
import pytest

from autoreels.core.models import Reel, Word
import autoreels.__main__ as m


def _w(t0: float, t1: float, word: str) -> Word:
    return Word(word=word, t0=t0, t1=t1)


def _reel(subtitles: list[Word], subtitle_gate: float) -> Reel:
    r = Reel(id="r01", start=1.0, end=subtitle_gate + 1.0,
             score=80, hook="h", title="t", description="d", reason="r", topic="x")
    r = r.model_copy(update={"subtitles": subtitles, "subtitle_gate": subtitle_gate})
    return r


# words in transcript that form two sentences:
#   sent1: "Это важно." (t0=1.0..2.0)
#   sent2: "Понятно." (t0=3.0..3.8) — after gate
_TX = [
    _w(1.0, 1.5, "Это"), _w(1.6, 2.0, "важно."),    # sentence 1 (complete)
    _w(3.0, 3.8, "Понятно."),                          # sentence 2 (complete, after gate)
]
# gate = 2.0 → subtitle_gate covers sent1 only, expected_last = "важно."


def test_exact_ok():
    """Last subtitle == last word of final sentence → no error."""
    r = _reel(subtitles=[_w(1.0, 1.5, "Это"), _w(1.6, 2.0, "важно.")],
              subtitle_gate=2.0)
    m._check_last_subtitle_word(r, _TX)  # must not raise


def test_extra_word_raises():
    """Extra word beyond gate → ValueError."""
    r = _reel(subtitles=[_w(1.0, 1.5, "Это"), _w(1.6, 2.0, "важно."), _w(3.0, 3.8, "Понятно.")],
              subtitle_gate=2.0)
    with pytest.raises(ValueError, match=r"\[CONTENT\]"):
        m._check_last_subtitle_word(r, _TX)


def test_missing_last_word_raises():
    """Subtitle list ends before the last word of the final sentence → ValueError."""
    r = _reel(subtitles=[_w(1.0, 1.5, "Это")],  # "важно." missing
              subtitle_gate=2.0)
    with pytest.raises(ValueError, match=r"\[CONTENT\]"):
        m._check_last_subtitle_word(r, _TX)


def test_duplicate_word_ok():
    """Subtitle ends on earlier occurrence of a word that appears twice in the gate span.

    Transcript has «делаю.» at t0=5.0 and t0=7.0 within the gate.
    Subtitle correctly ends at t0=5.0 (explicit e: chose it); expected_last resolves
    to the later t0=7.0. Same word text → no error (PXL r09 regression).
    """
    tx = [
        _w(1.0, 1.5, "Природа"), _w(1.6, 2.0, "делает"),
        _w(2.1, 3.0, "90%"), _w(3.1, 4.0, "того"),
        _w(4.1, 5.0, "что"), _w(5.1, 5.8, "делаю."),   # first occurrence
        _w(6.0, 6.5, "Да"), _w(6.6, 7.0, "делаю."),    # duplicate
    ]
    # gate covers both occurrences; subtitle ends on first
    r = _reel(
        subtitles=[_w(1.0, 1.5, "Природа"), _w(1.6, 2.0, "делает"),
                   _w(2.1, 3.0, "90%"), _w(3.1, 4.0, "того"),
                   _w(4.1, 5.0, "что"), _w(5.1, 5.8, "делаю.")],
        subtitle_gate=8.0,
    )
    r = r.model_copy(update={"end": 8.0})
    m._check_last_subtitle_word(r, tx)  # must not raise
