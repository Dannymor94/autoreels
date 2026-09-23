"""Pause-gap markers in the compact review export.

1. A sentence followed by a gap >= pause_show_sec shows ⏸N.N; one below the threshold does not.
   A gap >= min_pause_for_phrase_end shows ⏸⏸N.N (natural phrase end marker).
2. The verbose format (export_review) is unchanged — no pause markers there.
"""
from autoreels.cloud.blocks import (
    CandidateBlock, _Line, _numbered_sentences, export_compact_review, export_review,
)
from autoreels.core.models import Word


def _w(word: str, t0: float, t1: float) -> Word:
    return Word(word=word, t0=t0, t1=t1)


def _block(text: str, start: float, end: float) -> CandidateBlock:
    return CandidateBlock(
        id="test", text=text, start=start, end=end,
        duration=end - start, boundary_reason="sentence",
        lines=[_Line(start, end, text)],
        has_internal_speaker_change=False,
    )


# Two sentences:
#   sent1: "Привет." ends at t1=1.0
#   sent2: "Пока." starts at t0=1.9 → gap = 0.9s (shown as ⏸0.9)
# A third scenario: sent1.t1=2.0, sent2.t0=2.1 → gap = 0.1s (hidden below threshold 0.3)
_WORDS_BIG_GAP = [
    _w("Привет.", 0.0, 1.0),   # sentence 1 ends here
    _w("Пока.",  1.9, 2.5),    # sentence 2 starts 0.9s later
]

_WORDS_SMALL_GAP = [
    _w("Привет.", 0.0, 1.0),
    _w("Пока.",  1.1, 1.8),    # gap = 0.1s — below 0.3 threshold
]

_WORDS_STRONG_GAP = [
    _w("Привет.", 0.0, 1.0),
    _w("Пока.",  2.6, 3.2),    # gap = 1.6s — above min_pause_for_phrase_end=1.5
]


def test_gap_shown_when_above_threshold():
    b = _block("Привет. Пока.", 0.0, 2.5)
    result = _numbered_sentences(b, _WORDS_BIG_GAP, pause_show_sec=0.3, pause_strong_sec=1.5)
    assert "⏸0.9" in result, f"expected ⏸0.9 in: {result!r}"
    assert "⏸⏸" not in result  # below strong threshold


def test_gap_hidden_when_below_threshold():
    b = _block("Привет. Пока.", 0.0, 1.8)
    result = _numbered_sentences(b, _WORDS_SMALL_GAP, pause_show_sec=0.3, pause_strong_sec=1.5)
    assert "⏸" not in result, f"unexpected pause marker in: {result!r}"


def test_strong_marker_when_above_phrase_end():
    b = _block("Привет. Пока.", 0.0, 3.2)
    result = _numbered_sentences(b, _WORDS_STRONG_GAP, pause_show_sec=0.3, pause_strong_sec=1.5)
    assert "⏸⏸1.6" in result, f"expected ⏸⏸1.6 in: {result!r}"
    assert result.count("⏸") == 2  # ⏸⏸ is two ⏸ chars


def test_verbose_format_unchanged():
    b = _block("Привет. Пока.", 0.0, 2.5)
    out = export_review([b], source_ref="test.mp4", filter_removed_count=0)
    assert "⏸" not in out
    assert "Привет. Пока." in out
