"""Tests for candidate block segmentation (M1.6 stage 1 + 2).

All tests are fixture-only — no network, no LLM, no ffmpeg.
"""
import argparse
import random

import pytest

from autoreels.cloud.blocks import CandidateBlock, _Line, candidate_blocks, filter_blocks

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


# ---------------------------------------------------------------------------
# Stage 2 filter tests — fixture-only, no network
# ---------------------------------------------------------------------------

_ARTEFACT_MARKERS = ["субтитры создавал", "субтитры сделал", "続きは", "字幕"]
_PROMO_KEYWORDS = ["приходите на", "подписывайтесь", "включите звук"]
_HOST_AFFIRMATIONS = ["здорово", "отлично", "хорошо"]

_FILTER_DEFAULTS = dict(
    total_duration=600.0,
    head_skip_sec=60.0,
    tail_skip_sec=120.0,
    speech_density_min=0.4,
    repetition_unique_ratio_min=0.3,
    artefact_markers=_ARTEFACT_MARKERS,
    promo_keywords=_PROMO_KEYWORDS,
    host_affirmations=_HOST_AFFIRMATIONS,
)


def _make_block(text: str, start: float = 100.0, end: float = 122.0,
                lines: list | None = None) -> CandidateBlock:
    """Convenience: CandidateBlock with explicit or auto-generated lines."""
    if lines is None:
        lines = [_Line(start, end, text)]
    return CandidateBlock(
        id="test",
        start=lines[0].t0,
        end=lines[-1].t1,
        duration=lines[-1].t1 - lines[0].t0,
        text=" ".join(ln.text for ln in lines),
        boundary_reason="sentence",
        lines=lines,
    )


# ---------------------------------------------------------------------------
# Filter 1: transcription artefacts
# ---------------------------------------------------------------------------

def test_artefact_marker_drops_block():
    """A block containing an artefact marker string is dropped."""
    b = _make_block("Субтитры создавал DimaTorzok дальше идёт содержание")
    kept, dropped = filter_blocks([b], **_FILTER_DEFAULTS)
    assert len(kept) == 0
    assert len(dropped) == 1
    assert dropped[0][1] == "artefact"


def test_artefact_match_is_case_insensitive():
    """Artefact markers match regardless of capitalisation."""
    b = _make_block("СУБТИТРЫ СОЗДАВАЛ кто-то здесь ещё несколько слов")
    kept, dropped = filter_blocks([b], **_FILTER_DEFAULTS)
    assert any(reason == "artefact" for _, reason in dropped)


# ---------------------------------------------------------------------------
# Filter 2: promotional / organisational
# ---------------------------------------------------------------------------

def test_price_block_dropped_as_promo():
    """A block containing a price ('N рублей') is dropped as promo."""
    b = _make_block("Так она стоит 1000 рублей но сегодня по акции")
    kept, dropped = filter_blocks([b], **_FILTER_DEFAULTS)
    assert len(dropped) == 1
    assert dropped[0][1] == "promo"


def test_plain_number_block_not_dropped():
    """A block that mentions a year or count but no price is kept."""
    b = _make_block("В 2023 году всё изменилось для меня навсегда очень сильно")
    kept, dropped = filter_blocks([b], **_FILTER_DEFAULTS)
    assert len(kept) == 1
    assert len(dropped) == 0


def test_promo_keyword_drops_block():
    """A block containing a promo keyword is dropped as promo."""
    b = _make_block("Приходите на Фурмановскую улицу в субботу ждём вас")
    kept, dropped = filter_blocks([b], **_FILTER_DEFAULTS)
    assert len(dropped) == 1
    assert dropped[0][1] == "promo"


# ---------------------------------------------------------------------------
# Filter 3: head / tail skip
# ---------------------------------------------------------------------------

def test_head_block_dropped():
    """A block whose midpoint falls inside the first head_skip_sec is dropped as 'head'."""
    b = _make_block("Привет всем добро пожаловать на нашу лекцию сегодня", start=0.0, end=20.0)
    kept, dropped = filter_blocks([b], **_FILTER_DEFAULTS)
    assert len(dropped) == 1
    assert dropped[0][1] == "head"


def test_same_text_in_middle_is_kept():
    """The same text block in the middle of the recording survives the head/tail filter."""
    b = _make_block("Привет всем добро пожаловать на нашу лекцию сегодня",
                    start=300.0, end=320.0)
    kept, dropped = filter_blocks([b], **_FILTER_DEFAULTS)
    assert len(kept) == 1
    assert len(dropped) == 0


def test_tail_block_dropped():
    """A block whose midpoint is in the last tail_skip_sec is dropped as 'tail'."""
    # total_duration=600, tail=120 → tail zone starts at 480s
    b = _make_block("До свидания спасибо что были с нами сегодня всем пока",
                    start=500.0, end=522.0)
    kept, dropped = filter_blocks([b], **_FILTER_DEFAULTS)
    assert len(dropped) == 1
    assert dropped[0][1] == "tail"


# ---------------------------------------------------------------------------
# Filter 4: speech density
# ---------------------------------------------------------------------------

def test_low_density_block_dropped():
    """A block with sparse speech (guided-practice silences) is dropped."""
    # Three lines of 2s speech, spaced 14s apart → density = 6/30 = 0.2 < 0.4
    lines = [
        _Line(300.0, 302.0, "Закройте глаза"),
        _Line(314.0, 316.0, "Дышите"),
        _Line(328.0, 330.0, "Откройте глаза"),
    ]
    b = _make_block("Закройте глаза Дышите Откройте глаза", start=300.0, end=330.0, lines=lines)
    kept, dropped = filter_blocks([b], **_FILTER_DEFAULTS)
    assert len(dropped) == 1
    assert dropped[0][1] == "low_density"


def test_normal_density_block_kept():
    """A block with continuous speech is not dropped for density."""
    lines = [
        _Line(100.0, 109.0, "Первая половина фразы продолжается здесь"),
        _Line(109.2, 120.0, "Вторая половина фразы завершается тут"),
    ]
    b = _make_block("...", lines=lines)
    kept, dropped = filter_blocks([b], **_FILTER_DEFAULTS)
    assert len(kept) == 1
    assert not any(r == "low_density" for _, r in dropped)


# ---------------------------------------------------------------------------
# Filter 5: repetition (Whisper loop)
# ---------------------------------------------------------------------------

def test_looping_block_dropped():
    """A Whisper-loop block (very low unique-word ratio) is dropped."""
    looping = " ".join(["то что я заметил"] * 8)   # 4 unique / 32 total = 0.125 < 0.3
    b = _make_block(looping)
    kept, dropped = filter_blocks([b], **_FILTER_DEFAULTS)
    assert len(dropped) == 1
    assert dropped[0][1] == "repetition"


def test_natural_repetition_kept():
    """Emphatic natural repetition ('ещё больше, ещё больше') is kept (ratio ≥ 0.3)."""
    text = "ещё больше ещё больше это очень важно понять всем нам сегодня"
    # unique/total = 8/12 ≈ 0.67 → kept
    b = _make_block(text)
    kept, dropped = filter_blocks([b], **_FILTER_DEFAULTS)
    assert len(kept) == 1
    assert not any(r == "repetition" for _, r in dropped)


# ---------------------------------------------------------------------------
# Filter 6: internal speaker change — FLAG, do not drop
# ---------------------------------------------------------------------------

def test_internal_speaker_change_flagged_not_dropped():
    """A block with an internal dash line is KEPT but flagged has_internal_speaker_change."""
    lines = [
        _Line(100.0, 120.0, "Гость заканчивает свою мысль о природе вещей"),
        _Line(120.5, 142.0, "— Вопрос ведущего к гостю о смысле жизни"),
    ]
    b = _make_block("...", lines=lines)
    kept, dropped = filter_blocks([b], **_FILTER_DEFAULTS)
    assert len(kept) == 1
    assert len(dropped) == 0
    assert kept[0].has_internal_speaker_change is True


def test_normal_block_not_flagged():
    """A block without speaker-change signals is not flagged."""
    lines = [
        _Line(100.0, 110.0, "Говорит один человек без остановки"),
        _Line(110.3, 122.0, "И продолжает свою мысль дальше"),
    ]
    b = _make_block("...", lines=lines)
    kept, dropped = filter_blocks([b], **_FILTER_DEFAULTS)
    assert len(kept) == 1
    assert kept[0].has_internal_speaker_change is False


# ---------------------------------------------------------------------------
# Filter 7: sidecar data — dropped blocks carry id, reason, and first_words
# ---------------------------------------------------------------------------

def test_dropped_blocks_carry_sidecar_fields():
    """filter_blocks returns dropped tuples with block.id, reason, and block.text."""
    b_artefact = _make_block("Субтитры создавал DimaTorzok некий текст здесь")
    b_normal = _make_block("Это нормальный блок с интересным содержанием речи",
                           start=200.0, end=222.0)
    kept, dropped = filter_blocks([b_artefact, b_normal], **_FILTER_DEFAULTS)

    assert len(dropped) == 1
    drop_block, drop_reason = dropped[0]
    assert drop_block.id == b_artefact.id
    assert drop_reason == "artefact"
    # first 8 words are accessible from drop_block.text
    first_8 = " ".join(drop_block.text.split()[:8])
    assert "субтитры" in first_8.lower() or "DimaTorzok" in first_8
