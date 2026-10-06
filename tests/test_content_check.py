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


def test_explicit_e_overlapping_timestamps_excluded():
    """explicit_e with overlapping Whisper timestamps: next-sentence word must be rejected.

    Sentence 11 last word «душе.» t0=378.483; sentence 12 first word «Понятно?» t0=378.143
    (BEFORE «душе.» due to Whisper timestamp overlap). Gate=379.143 includes both by t0.
    Without fix: _check_last_subtitle_word would compute expected_last=«Понятно?» and pass.
    With fix: _blk_sents_full[:11] scopes to sentences 1..11 → expected_last=«душе.».
    The intruder «Понятно?» with t0=378.143 is NOT in _incl_t0s and is caught by the
    post-filter in _blocks_do_apply; _check_last_subtitle_word verifies the cleaned state.
    """
    from autoreels.cloud.edit import split_sentences

    # Sentence 11: ends with «душе.» t0=378.483
    sent11 = [
        _w(376.0, 376.5, "по"),
        _w(376.6, 377.0, "душе"),
        _w(377.1, 377.5, "или"),
        _w(377.6, 378.0, "не"),
        _w(378.1, 378.483, "по"),
        _w(378.483, 378.883, "душе."),
    ]
    # Sentence 12: «Понятно?» — Whisper gives t0=378.143, BEFORE «душе.» t0=378.483.
    sent12 = [_w(378.143, 379.163, "Понятно?")]

    all_words = sent11 + sent12  # transcript word list (flattened)

    # _blk_sents_full: full block sentences (index 0=sent1 … index 10=sent11 … index 11=sent12)
    # We simulate with two sentences at indices 10 and 11; e:11 → include [:11] → sent11 only.
    blk_sents_full = [sent11, sent12]  # simplified: pretend only these two sentences exist
    _e_val = 1  # e:1 means include sentence 1 (sent11) only; [:1] = [sent11]

    gate = 379.143
    r = _reel(
        subtitles=sent11,  # correct: only sent11 words (post-filter already removed «Понятно?»)
        subtitle_gate=gate,
    )
    r = r.model_copy(update={"end": 379.143})
    r._explicit_e_val = _e_val
    r._blk_sents_full = blk_sents_full

    # After explicit-e post-filter, subtitles contain only sent11 words → check must pass.
    m._check_last_subtitle_word(r, all_words)  # must not raise

    # Now verify that the post-filter itself catches the intruder: subtitles still contain
    # «Понятно?» (before post-filter ran) → check must detect and raise [CONTENT].
    r_dirty = _reel(
        subtitles=sent11 + sent12,  # intruder present
        subtitle_gate=gate,
    )
    r_dirty = r_dirty.model_copy(update={"end": 379.143})
    r_dirty._explicit_e_val = _e_val
    r_dirty._blk_sents_full = blk_sents_full
    # _check_last_subtitle_word uses _blk_sents_full[:1] → expected_last = «душе.»
    # actual_last = «Понятно?» with t0=378.143 < «душе.» t1=378.883 (within eps=0.05) → raises.
    with pytest.raises(ValueError, match=r"\[CONTENT\]"):
        m._check_last_subtitle_word(r_dirty, all_words)


# ---------------------------------------------------------------------------
# _check_first_subtitle_word
# ---------------------------------------------------------------------------

def _reel_first(subtitles: list[Word]) -> Reel:
    r = Reel(id="r01", start=subtitles[0].t0 if subtitles else 0.0, end=10.0,
             score=80, hook="h", title="t", description="d", reason="r", topic="x")
    return r.model_copy(update={"subtitles": subtitles})


_TX_FIRST = [
    _w(0.5, 1.0, "предыдущая."),   # sentence end
    _w(1.0, 1.5, "Когда"),          # sentence start (uppercase, follows sentence end)
    _w(1.6, 2.0, "у"),              # mid-sentence (lowercase, follows non-sentence-end)
    _w(2.1, 2.5, "вас"),
]


def test_first_word_at_sentence_start_ok():
    """First subtitle starts at sentence start — no error."""
    r = _reel_first([_TX_FIRST[1]])   # «Когда»
    m._check_first_subtitle_word(r, _TX_FIRST)  # must not raise


def test_first_word_mid_sentence_lowercase_raises():
    """First subtitle is mid-sentence and starts lowercase → [ERROR] starts mid-sentence.

    r04 regression: old manifest started with «у вас не стимул» after «Когда» was skipped.
    """
    r = _reel_first([_TX_FIRST[2]])   # «у» follows «Когда» (non-sentence-end)
    with pytest.raises(ValueError, match=r"\[ERROR\].*starts mid-sentence"):
        m._check_first_subtitle_word(r, _TX_FIRST)


def test_first_word_uppercase_after_non_sentence_end_ok():
    """Uppercase first word after a non-sentence-end predecessor is allowed.

    Could be a proper noun mid-sentence or snap picking it deliberately.
    """
    tx = [_w(0.5, 1.0, "слово"), _w(1.0, 1.5, "Алексей")]  # comma-separated, not sentence end
    r = _reel_first([tx[1]])
    m._check_first_subtitle_word(r, tx)  # uppercase → no raise


def test_first_word_no_predecessor_ok():
    """First word of the transcript has no predecessor — no error."""
    tx = [_w(0.0, 0.5, "когда")]   # lowercase, but no preceding word
    r = _reel_first([tx[0]])
    m._check_first_subtitle_word(r, tx)  # must not raise
