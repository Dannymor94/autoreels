"""Tests for candidate block segmentation (M1.6 stage 1).

All tests are fixture-only — no network, no LLM, no ffmpeg.
"""
import argparse
import random

import pytest

from autoreels.cloud.blocks import CandidateBlock, candidate_blocks

MIN_SEC = 18.0
MAX_SEC = 90.0
MIN_PAUSE = 1.5


def _line(t0, t1, text):
    """Build one compressed-transcript line."""
    return f"[{t0:06.1f}-{t1:06.1f}] {text}"


def _compressed(*lines):
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Test 1: pause threshold opens / does not open a block
# ---------------------------------------------------------------------------

def test_pause_above_threshold_opens_new_block():
    """A gap > min_pause_for_phrase_end between two lines opens a 'pause' boundary."""
    compressed = _compressed(
        _line(0, 20, "Первая длинная мысль, которая занимает целых двадцать секунд"),
        _line(22, 42, "Вторая длинная мысль после паузы более полутора секунд"),
    )
    blocks = candidate_blocks(compressed, min_sec=MIN_SEC, max_sec=MAX_SEC,
                              min_pause_for_phrase_end=MIN_PAUSE)
    assert len(blocks) == 2
    assert blocks[1].boundary_reason == "pause"


def test_pause_below_threshold_does_not_split():
    """A gap ≤ threshold does not open a pause boundary; lines stay in one block."""
    # gap = 0.4s < 1.5s; no terminal punct → no sentence boundary either
    compressed = _compressed(
        _line(0, 18, "Первый отрезок без терминального знака"),
        _line(18.4, 36.4, "Второй отрезок без терминального знака"),
    )
    blocks = candidate_blocks(compressed, min_sec=MIN_SEC, max_sec=MAX_SEC,
                              min_pause_for_phrase_end=MIN_PAUSE)
    assert len(blocks) == 1


# ---------------------------------------------------------------------------
# Test 2: dash-marked speaker turn
# ---------------------------------------------------------------------------

def test_em_dash_opens_speaker_turn_block():
    """A line starting with em-dash opens a 'speaker_turn' boundary."""
    compressed = _compressed(
        _line(0, 20, "Хозяин задаёт вопрос гостю студии"),
        _line(20.4, 40.4, "— Вот именно об этом я и хотел рассказать вам сегодня"),
    )
    blocks = candidate_blocks(compressed, min_sec=MIN_SEC, max_sec=MAX_SEC,
                              min_pause_for_phrase_end=MIN_PAUSE)
    assert len(blocks) == 2
    assert blocks[1].boundary_reason == "speaker_turn"


def test_en_dash_opens_speaker_turn_block():
    """En-dash is also recognized as a speaker-turn marker (reuses _DASH_CHARS from select.py)."""
    compressed = _compressed(
        _line(0, 20, "Реплика ведущего без завершения"),
        _line(20.4, 40.4, "– Ответ гостя на вопрос ведущего"),
    )
    blocks = candidate_blocks(compressed, min_sec=MIN_SEC, max_sec=MAX_SEC,
                              min_pause_for_phrase_end=MIN_PAUSE)
    assert len(blocks) == 2
    assert blocks[1].boundary_reason == "speaker_turn"


# ---------------------------------------------------------------------------
# Test 3: two short adjacent blocks merge into one satisfying min_sec
# ---------------------------------------------------------------------------

def test_short_adjacent_blocks_merge():
    """Two blocks each < min_sec merge into one block >= min_sec."""
    # Each line is 10s (< 18s), no terminal punct, small gap
    compressed = _compressed(
        _line(0, 10, "Первый короткий отрезок без точки"),
        _line(10.2, 20.2, "Второй короткий отрезок без точки"),
    )
    blocks = candidate_blocks(compressed, min_sec=MIN_SEC, max_sec=MAX_SEC,
                              min_pause_for_phrase_end=MIN_PAUSE)
    assert len(blocks) == 1
    assert blocks[0].duration >= MIN_SEC


def test_short_block_dropped_when_merge_exceeds_max():
    """A short block that can't be merged (would exceed max_sec) is dropped."""
    # Long block (85s) + short tail (5s); merge would be 90+5 > 90s → short is dropped
    compressed = _compressed(
        _line(0, 85, "Длинный блок почти на пределе"),
        _line(86, 91, "Короткий хвост"),  # 5s < min_sec; merge → 91s > max_sec → drop
    )
    blocks = candidate_blocks(compressed, min_sec=MIN_SEC, max_sec=MAX_SEC,
                              min_pause_for_phrase_end=MIN_PAUSE)
    # Only the long 85s block survives; the 5s tail is dropped
    assert len(blocks) == 1
    assert blocks[0].duration == pytest.approx(85.0)


# ---------------------------------------------------------------------------
# Test 4: block over max_duration splits at its longest internal pause
# ---------------------------------------------------------------------------

def test_long_block_splits_at_longest_pause():
    """A block > max_sec splits at its longest internal gap; both halves are in bounds."""
    # 5 lines with equal small gaps → no boundary signals → one big block of ~110s
    # Split is at midpoint (all equal gaps); both halves well within [18, 90]
    lines = [
        _line(0, 22, "Первый фрагмент без точки"),
        _line(22.3, 44.3, "Второй фрагмент без точки"),
        _line(44.6, 66.6, "Третий фрагмент без точки"),
        _line(66.9, 88.9, "Четвёртый фрагмент без точки"),
        _line(89.2, 111.2, "Пятый фрагмент без точки"),
    ]
    compressed = _compressed(*lines)
    blocks = candidate_blocks(compressed, min_sec=MIN_SEC, max_sec=MAX_SEC,
                              min_pause_for_phrase_end=MIN_PAUSE)
    assert len(blocks) == 2
    for b in blocks:
        assert b.duration >= MIN_SEC, f"block too short: {b.duration:.1f}s"
        assert b.duration <= MAX_SEC, f"block too long: {b.duration:.1f}s"


def test_split_prefers_longest_pause_not_midpoint():
    """When pauses are unequal, split happens at the longest gap, not the middle."""
    # 3 lines: [0-30, 30.1-60, 62-96]  →  longest pause at 60-62 (1.9s vs 0.1s)
    # Gap 60-62 is 2s > 1.5s → this is a pause BOUNDARY too, so actually two blocks form early.
    # To test split-at-longest-pause, we need no boundary triggers:
    # Use 3 lines with all pauses < 1.5 but one clearly bigger than others
    lines = [
        _line(0, 35, "Первый кусок без точки"),       # 35s
        _line(36.2, 50, "Второй кусок без точки"),    # 13.8s, gap=1.2s (biggest but < 1.5)
        _line(50.1, 96, "Третий кусок без точки"),    # 45.9s, gap=0.1s
    ]
    # Total = 96s > 90; no pause boundary (all gaps < 1.5)
    # Gaps: 1.2s (between L0-L1) and 0.1s (between L1-L2)
    # Split at k=1 (biggest gap 1.2s between L0 and L1)
    compressed = _compressed(*lines)
    blocks = candidate_blocks(compressed, min_sec=MIN_SEC, max_sec=MAX_SEC,
                              min_pause_for_phrase_end=MIN_PAUSE)
    assert len(blocks) == 2
    # Left block: lines[0] = [0-35] = 35s; right block: lines[1]+lines[2] = [36.2-96] = 59.8s
    assert blocks[0].duration == pytest.approx(35.0)
    assert blocks[1].duration == pytest.approx(96.0 - 36.2)


# ---------------------------------------------------------------------------
# Test 5: block id is stable across runs and content-based
# ---------------------------------------------------------------------------

def test_block_id_stable_and_content_based():
    """Same text → same id regardless of timestamps; different text → different id."""
    text_a = "Уникальный текст для первого тестового блока"
    text_b = "Совершенно другой текст для второго тестового блока"

    # Same text, different timestamps → same id
    c_a1 = _compressed(_line(0, 20, text_a))
    c_a2 = _compressed(_line(100, 120, text_a))
    # Different text → different id
    c_b = _compressed(_line(0, 20, text_b))

    b_a1 = candidate_blocks(c_a1, min_sec=MIN_SEC, max_sec=MAX_SEC, min_pause_for_phrase_end=MIN_PAUSE)
    b_a2 = candidate_blocks(c_a2, min_sec=MIN_SEC, max_sec=MAX_SEC, min_pause_for_phrase_end=MIN_PAUSE)
    b_b = candidate_blocks(c_b, min_sec=MIN_SEC, max_sec=MAX_SEC, min_pause_for_phrase_end=MIN_PAUSE)

    assert b_a1[0].id == b_a2[0].id, "same text at different timestamps must have same id"
    assert b_a1[0].id != b_b[0].id, "different texts must have different ids"

    # Verify stability (deterministic): run again
    b_a1_again = candidate_blocks(c_a1, min_sec=MIN_SEC, max_sec=MAX_SEC,
                                  min_pause_for_phrase_end=MIN_PAUSE)
    assert b_a1[0].id == b_a1_again[0].id


# ---------------------------------------------------------------------------
# Test 6: every returned block is within [min_sec, max_sec] — corpus invariant
# ---------------------------------------------------------------------------

def test_all_blocks_within_duration_bounds():
    """Generated corpus of random lines → every returned block in [min_sec, max_sec]."""
    rng = random.Random(42)
    t = 0.0
    lines = []
    for _ in range(60):
        dur = rng.uniform(3.0, 24.0)       # keep below max_sec to avoid unsplittable single lines
        gap = rng.uniform(0.05, 2.5)
        text_words = ["слово"] * rng.randint(3, 12)
        if rng.random() > 0.4:
            text_words[-1] += "."           # ~60 % of lines end with terminal punct
        lines.append(_line(t, t + dur, " ".join(text_words)))
        t += dur + gap

    compressed = _compressed(*lines)
    blocks = candidate_blocks(compressed, min_sec=MIN_SEC, max_sec=MAX_SEC,
                              min_pause_for_phrase_end=MIN_PAUSE)

    violations = [
        f"[{b.start:.1f}-{b.end:.1f}] dur={b.duration:.1f}s"
        for b in blocks
        if b.duration < MIN_SEC or b.duration > MAX_SEC
    ]
    assert not violations, "blocks out of bounds:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# Test 7: 'blocks' subcommand is registered in argparse (drift check)
# ---------------------------------------------------------------------------

def test_blocks_command_registered_in_argparse():
    """The 'blocks' CLI subcommand exists in the argparse dispatcher."""
    import autoreels.__main__ as cli
    parser = cli._build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    assert "blocks" in sub.choices, "'blocks' command not registered in _build_parser()"
