"""Tests for candidate block segmentation (M1.6 stage 1 + 2 + 3).

All tests are fixture-only — no network, no LLM, no ffmpeg.
"""
import argparse
import random

import pytest

from autoreels.cloud.blocks import (
    CandidateBlock, _Line, candidate_blocks, filter_blocks, score_block, topk_filter,
)
from autoreels.core.config import BlockScoringConfig

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
_SIGNOFF_PHRASES = ["спасибо, что были", "спасибо за внимание", "до встречи", "всем пока",
                    "на этом всё", "до новых встреч", "здравствуйте", "добрый день"]
_HOST_AFFIRMATIONS = ["здорово", "отлично", "хорошо"]

_FILTER_DEFAULTS = dict(
    total_duration=600.0,
    head_skip_sec=30.0,
    tail_skip_sec=30.0,
    speech_density_min=0.4,
    repetition_unique_ratio_min=0.3,
    artefact_markers=_ARTEFACT_MARKERS,
    promo_keywords=_PROMO_KEYWORDS,
    signoff_phrases=_SIGNOFF_PHRASES,
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


def test_artefact_in_tail_stripped_block_kept():
    """A multi-line block whose last line contains artefact text is kept with the artefact stripped.

    Regression for blocks 5 and 64 from PXL transcript: real speech followed by
    a Whisper credit line was being dropped as artefact; it should be kept.
    """
    real = _Line(100.0, 115.0, "то ты приходишь к тому, что надо быть ближе")
    art = _Line(115.0, 118.0, "Субтитры создавал DimaTorzok и другое.")
    b = _make_block("", lines=[real, art])
    kept, dropped = filter_blocks([b], **_FILTER_DEFAULTS)
    assert len(kept) == 1
    assert len(dropped) == 0
    assert "Субтитры создавал" not in kept[0].text
    assert "приходишь" in kept[0].text


def test_artefact_in_first_line_stripped_block_kept():
    """A block whose FIRST line is a credit is kept with the leading credit stripped (Part C).

    Blocks 3/35/63 in the PXL export opened with a Whisper credit but carried 40-55 s of real
    speech after it. A leading credit is scrubbed the same way a trailing one is; only a block that
    is entirely credit is dropped. The kept block starts at the first real line.
    """
    art = _Line(100.0, 103.0, "Субтитры создавал DimaTorzok")
    real = _Line(103.0, 122.0, "Чем-то вы, возможно, передавлены сейчас")
    b = _make_block("", lines=[art, real])
    kept, dropped = filter_blocks([b], **_FILTER_DEFAULTS)
    assert len(kept) == 1
    assert len(dropped) == 0
    assert "Субтитры создавал" not in kept[0].text
    assert "передавлены" in kept[0].text
    assert abs(kept[0].start - 103.0) < 1e-6           # start moved past the credit


def test_artefact_only_block_dropped():
    """A block that is nothing BUT credit lines is still dropped (nothing real to keep)."""
    a1 = _Line(100.0, 103.0, "Субтитры создавал DimaTorzok")
    a2 = _Line(103.0, 106.0, "Субтитры сделал кто-то ещё")
    b = _make_block("", lines=[a1, a2])
    kept, dropped = filter_blocks([b], **_FILTER_DEFAULTS)
    assert len(kept) == 0
    assert dropped[0][1] == "artefact"


def test_promo_keyword_not_matched_as_word_prefix():
    """A promo keyword that is a prefix of a longer Russian word is not matched.

    'перерыв' is a strict substring of its genitive 'перерывов'; bare 'in' matching
    would false-positive. Word-boundary regex must not fire on inflected forms.
    """
    b = _make_block("Работали перерывов не было совсем, весь день подряд очень много")
    kept, dropped = filter_blocks(
        [b], **{**_FILTER_DEFAULTS, "promo_keywords": ["перерыв"]},
    )
    assert len(kept) == 1
    assert len(dropped) == 0


_MIN_SEC = 18.0
_MAX_SEC = 90.0
_SIZING_DEFAULTS = {**_FILTER_DEFAULTS, "min_sec": _MIN_SEC, "max_sec": _MAX_SEC,
                    "total_duration": 300.0}


def test_scrub_below_floor_merges_with_next():
    """After artefact tail is stripped, a too-short block merges with the following block.

    Block A: 100-117s raw; last line is artefact; after scrub 100-112s = 12s < 18s floor.
    Block B: 117-160s = 43s.  Combined 60s ≤ 90s max → merged, both in kept.
    """
    real_a = _Line(100.0, 112.0, "Действительно интересная мысль была здесь давно")
    art_a  = _Line(112.0, 117.0, "Субтитры создавал DimaTorzok")
    block_a = _make_block("", lines=[real_a, art_a])

    real_b = _Line(117.0, 160.0, "Следующая очень длинная мысль о важном и интересном")
    block_b = _make_block("", lines=[real_b])

    kept, dropped = filter_blocks([block_a, block_b], **_SIZING_DEFAULTS)
    assert len(kept) == 1
    assert len(dropped) == 0
    assert "интересная мысль" in kept[0].text
    assert "длинная мысль" in kept[0].text


def test_scrub_below_floor_dropped_when_merge_exceeds_max():
    """After artefact scrub, a too-short block is dropped when merging would exceed max_sec.

    Block A: after scrub 100-112s = 12s < 18s.  Block B: 117-210s = 93s.
    Combined 110s > 90s max → A dropped as too_short_after_scrub, B kept normally.
    """
    real_a = _Line(100.0, 112.0, "Действительно интересная мысль была здесь давно")
    art_a  = _Line(112.0, 117.0, "Субтитры создавал DimaTorzok")
    block_a = _make_block("", lines=[real_a, art_a])

    real_b = _Line(117.0, 210.0, "Очень длинный блок который значительно превышает максимум")
    block_b = _make_block("", lines=[real_b])

    kept, dropped = filter_blocks([block_a, block_b], **_SIZING_DEFAULTS)
    assert len(kept) == 1
    assert len(dropped) == 1
    assert dropped[0][1] == "too_short_after_scrub"
    assert "длинный блок" in kept[0].text


def test_scrub_above_floor_block_untouched():
    """A block that still exceeds min_sec after artefact strip passes through unchanged.

    Three lines: two real-speech lines (28s) + artefact tail.  After scrub 28s > 18s.
    """
    s1  = _Line(100.0, 115.0, "Первая мысль очень длинная и важная для понимания")
    s2  = _Line(115.0, 128.0, "Вторая мысль тоже важная и нужная нам сейчас здесь")
    art = _Line(128.0, 130.0, "Субтитры создавал DimaTorzok")
    b = _make_block("", lines=[s1, s2, art])

    kept, dropped = filter_blocks([b], **_SIZING_DEFAULTS)
    assert len(kept) == 1
    assert len(dropped) == 0
    assert "Субтитры создавал" not in kept[0].text
    assert kept[0].duration == pytest.approx(28.0)


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
    # total_duration=600, tail=30 → tail zone starts at 570s; mid=[578+600]/2=589 > 570
    b = _make_block("До свидания надеюсь увидеть вас снова в следующий раз",
                    start=578.0, end=600.0)
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
    # Position block_artefact in the safe middle zone (not head/tail with new 30s defaults)
    b_artefact = _make_block("Субтитры создавал DimaTorzok некий текст здесь",
                             start=200.0, end=222.0)
    b_normal = _make_block("Это нормальный блок с интересным содержанием речи",
                           start=250.0, end=272.0)
    kept, dropped = filter_blocks([b_artefact, b_normal], **_FILTER_DEFAULTS)

    assert len(dropped) == 1
    drop_block, drop_reason = dropped[0]
    assert drop_block.id == b_artefact.id
    assert drop_reason == "artefact"
    # first 8 words are accessible from drop_block.text
    first_8 = " ".join(drop_block.text.split()[:8])
    assert "субтитры" in first_8.lower() or "DimaTorzok" in first_8


# ---------------------------------------------------------------------------
# Stage 2 fixes: position-independent sign-off/greeting detection (M1.6 s2 v2)
# ---------------------------------------------------------------------------

def test_signoff_phrase_opening_block_dropped_regardless_of_position():
    """A block that opens with a sign-off phrase is dropped as 'signoff' even if mid-recording."""
    # Block is firmly in the middle of the recording — not near head or tail
    b = _make_block("Спасибо, что были с нами сегодня на нашей лекции",
                    start=280.0, end=302.0)
    kept, dropped = filter_blocks([b], **_FILTER_DEFAULTS)
    assert len(dropped) == 1
    assert dropped[0][1] == "signoff"


def test_signoff_phrase_mid_sentence_not_dropped():
    """A block that only mentions a sign-off phrase mid-sentence is kept."""
    # "спасибо" appears after "он сказал" — not at a sentence opening
    b = _make_block(
        "Он произнёс спасибо за внимание и продолжил рассуждать о смысле жизни",
        start=280.0, end=302.0,
    )
    kept, dropped = filter_blocks([b], **_FILTER_DEFAULTS)
    assert len(kept) == 1
    assert not any(r == "signoff" for _, r in dropped)


# ---------------------------------------------------------------------------
# Stage 3: heuristic scoring (M1.6 stage 3)
# ---------------------------------------------------------------------------

_SCORING_CFG = BlockScoringConfig()  # default weights


def test_score_ends_sentence_bonus():
    """Block ending on '.' scores higher than identical block without terminal punctuation."""
    b_with = _make_block(
        "Это важная мысль, которая завершается точкой.", start=200.0, end=242.0
    )
    b_without = _make_block(
        "Это важная мысль, которая не завершается точкой", start=200.0, end=242.0
    )
    s_with, _ = score_block(b_with, _SCORING_CFG)
    s_without, _ = score_block(b_without, _SCORING_CFG)
    assert s_with > s_without, f"expected ends-sentence bonus: {s_with:.1f} vs {s_without:.1f}"


def test_score_opener_penalty():
    """Block opening with 'поэтому' (dangling conjunction) scores lower than a clean opener."""
    b_clean = _make_block(
        "Нам важно понять, что происходит здесь и сейчас в нашей жизни.",
        start=200.0, end=242.0,
    )
    b_dangling = _make_block(
        "Поэтому нам важно понять, что происходит здесь и сейчас.",
        start=200.0, end=242.0,
    )
    s_clean, _ = score_block(b_clean, _SCORING_CFG)
    s_dangling, _ = score_block(b_dangling, _SCORING_CFG)
    assert s_clean > s_dangling, f"clean opener should score higher: {s_clean:.1f} vs {s_dangling:.1f}"


def test_score_speaker_change_penalty():
    """Block flagged with has_internal_speaker_change scores materially lower."""
    lines_no_sc = [_Line(200.0, 220.0, "Первый говорит что-то важное"), _Line(220.5, 242.0, "И продолжает мысль")]
    lines_sc = [_Line(200.0, 220.0, "Первый говорит что-то важное"), _Line(220.5, 242.0, "— Второй отвечает")]
    b_no_sc = _make_block("Первый говорит что-то важное И продолжает мысль", lines=lines_no_sc)
    b_sc = _make_block("Первый говорит что-то важное — Второй отвечает", lines=lines_sc)
    b_sc.has_internal_speaker_change = True
    s_no_sc, _ = score_block(b_no_sc, _SCORING_CFG)
    s_sc, _ = score_block(b_sc, _SCORING_CFG)
    min_gap = _SCORING_CFG.w_speaker_change / (
        _SCORING_CFG.w_duration + _SCORING_CFG.w_ends_sentence + _SCORING_CFG.w_opens_sentence
        + _SCORING_CFG.w_question + _SCORING_CFG.w_contrarian + _SCORING_CFG.w_lexical
    ) * 100
    assert s_no_sc - s_sc >= min_gap * 0.9, (
        f"SC penalty not reflected: {s_no_sc:.1f} vs {s_sc:.1f}, expected gap ≥{min_gap:.1f}"
    )


def test_score_duration_sweet_spot():
    """Score peaks inside the sweet spot and falls off on both sides."""
    cfg = BlockScoringConfig(sweet_spot_min=30.0, sweet_spot_max=60.0, min_sec=18.0)
    text = "Нейтральный текст без особенностей для теста длительности здесь."

    def make_b(dur: float) -> CandidateBlock:
        return _make_block(text, start=200.0, end=200.0 + dur)

    s_short, _ = score_block(make_b(20.0), cfg)   # below sweet spot
    s_sweet, _ = score_block(make_b(45.0), cfg)   # in sweet spot (peak)
    s_long, _ = score_block(make_b(82.0), cfg)    # above sweet spot

    assert s_sweet > s_short, f"sweet spot should beat too-short: {s_sweet:.1f} vs {s_short:.1f}"
    assert s_sweet > s_long, f"sweet spot should beat too-long: {s_sweet:.1f} vs {s_long:.1f}"


def test_topk_per_chunk_applies_per_window():
    """Top-K is applied per time window, not globally — a lone block in its window always survives."""
    cfg = BlockScoringConfig(chunk_window_sec=300.0, top_k_per_chunk=8)
    # 9 blocks in window 0 ([0-300s]), 1 block in window 1 ([300-600s])
    blocks_w0 = [
        _make_block(f"Блок {i} первого окна с уникальным текстом номер {i}",
                    start=20.0 * i, end=20.0 * i + 18.0)
        for i in range(9)
    ]
    block_w1 = _make_block("Блок второго окна с уникальным текстом", start=310.0, end=340.0)
    all_blocks_s3 = blocks_w0 + [block_w1]
    for b in all_blocks_s3:
        b.heuristic_score, b.score_breakdown = score_block(b, cfg)

    kept_s3, cut_s3 = topk_filter(all_blocks_s3, chunk_window_sec=cfg.chunk_window_sec, top_k=cfg.top_k_per_chunk)

    assert len(kept_s3) == 9, f"expected 8 (w0) + 1 (w1) = 9 kept; got {len(kept_s3)}"
    assert len(cut_s3) == 1, f"expected 1 cut from w0; got {len(cut_s3)}"
    assert any(b.start == 310.0 for b in kept_s3), "lone block in window 1 must always be kept"


def test_score_reproducible():
    """Same input always produces the same score."""
    b = _make_block(
        "Это детерминированный блок текста для проверки стабильности скоринга.",
        start=200.0, end=235.0,
    )
    s1, bd1 = score_block(b, _SCORING_CFG)
    s2, bd2 = score_block(b, _SCORING_CFG)
    assert s1 == s2
    assert bd1 == bd2


def test_block_64s_from_end_without_signoff_phrase_is_kept():
    """Regression: a block 64s before the end with no sign-off phrase must survive tail=30s.

    This is the direct regression test for PXL block 116 ('Если вы здесь находитесь…').
    """
    total = 2846.0
    # mid = total - 64 = 2782s; tail zone with 30s = mid > 2816s → this is NOT in the tail zone
    b = _make_block(
        "Если вы здесь находитесь и такие как вы вы уникальны ваша жизнь важна",
        start=total - 93.0,   # start=2753s
        end=total - 64.0,     # end=2782s  →  mid=2767.5s < 2816s
    )
    kept, dropped = filter_blocks([b], total_duration=total,
                                  head_skip_sec=30.0, tail_skip_sec=30.0,
                                  speech_density_min=0.4,
                                  repetition_unique_ratio_min=0.3,
                                  artefact_markers=[],
                                  promo_keywords=[],
                                  signoff_phrases=[],
                                  host_affirmations=[])
    assert len(kept) == 1, f"block 64s from end should be kept; got dropped={dropped}"


# ---------------------------------------------------------------------------
# Stage 4-alt: manual review export / import (M1.6 stage 4-alt)
# ---------------------------------------------------------------------------

from autoreels.cloud.blocks import (
    export_review, parse_review, _make_merged_block, make_dataset_row,
)


def test_export_one_entry_per_kept_block_chronological():
    """Export produces one entry per kept block in chronological order with full text."""
    import re as _re
    b1 = _make_block("Первый блок содержит полный текст без обрезки.", start=10.0, end=45.0)
    b2 = _make_block("Второй блок тоже содержит полный текст длинной фразы.", start=50.0, end=80.0)
    # Give them stable ids so regex match is deterministic
    b1.id = "aaa111bbb222ccc3"
    b2.id = "ddd444eee555fff6"
    out = export_review([b1, b2], source_ref="manifests/test.json", filter_removed_count=5)

    headers = _re.findall(r"^\[\s*\d+\s*\]", out, _re.MULTILINE)
    assert len(headers) == 2, f"expected 2 block headers, got {len(headers)}"
    assert out.index("[ 1 ]") < out.index("[ 2 ]"), "blocks must be in chronological (seq) order"
    assert "Первый блок содержит полный текст без обрезки." in out
    assert "Второй блок тоже содержит полный текст длинной фразы." in out
    assert "filter_removed: 5" in out


def test_export_no_heuristic_score():
    """Export must NOT contain the heuristic score anywhere — reviewer must not be anchored."""
    b = _make_block("Текст блока для проверки отсутствия скора.")
    b.id = "aaa111bbb222ccc3"
    b.heuristic_score = 98.765          # distinctive value
    b.score_breakdown = {"duration": 18.0, "ends_sentence": 10.0}
    out = export_review([b], source_ref="test.json", filter_removed_count=0)
    assert "98.765" not in out, "heuristic_score value must not appear in review file"
    assert "98.7" not in out
    # score placeholder is present but not filled
    assert "score: __" in out


def test_import_selects_only_numeric_scores():
    """Only blocks with a numeric score are selected; empty/__ fields are skipped."""
    content = "\n".join([
        "# source: manifests/test.json",
        "# blocks: 3  |  filter_removed: 0",
        "",
        "[ 1 ]  30.0s  id=aaa111  score: 85",
        "Текст первого блока.",
        "",
        "[ 2 ]  25.0s  id=bbb222  score: __",
        "Текст второго блока.",
        "",
        "[ 3 ]  35.0s  id=ccc333  score: ",
        "Текст третьего блока.",
    ])
    source, entries, errors = parse_review(content)
    selected = [e for e in entries if e.score is not None]
    assert source == "manifests/test.json"
    assert len(selected) == 1
    assert selected[0].block_id == "aaa111"
    assert selected[0].score == 85
    assert len(errors) == 0


def test_import_merge_plus_and_make_merged_block():
    """'+' in score parses as merge_fwd=1; _make_merged_block combines two blocks."""
    content = "\n".join([
        "# source: test.json",
        "[ 1 ]  30.0s  id=aaa111  score: 82+",
        "[ 2 ]  25.0s  id=bbb222  score: __",
    ])
    source, entries, errors = parse_review(content)
    assert entries[0].merge_fwd == 1
    assert entries[0].merge_back is False
    assert entries[0].score == 82
    assert entries[1].merge_fwd == 0
    assert len(errors) == 0

    # _make_merged_block combines text and extends time range
    b1 = _make_block("Первый блок.", start=10.0, end=40.0)
    b2 = _make_block("Второй блок.", start=41.0, end=66.0)
    merged = _make_merged_block(b1, b2)
    assert merged.start == pytest.approx(10.0)
    assert merged.end == pytest.approx(66.0)
    assert merged.duration == pytest.approx(56.0)
    assert "Первый блок." in merged.text
    assert "Второй блок." in merged.text


def test_import_malformed_line_reported_rest_applies():
    """A malformed score is reported with its line number; other entries still parse."""
    content = "\n".join([
        "# source: test.json",
        "[ 1 ]  30.0s  id=aaa111  score: пять",
        "[ 2 ]  25.0s  id=bbb222  score: 75",
    ])
    source, entries, errors = parse_review(content)
    assert len(errors) == 1
    assert errors[0][0] == 2, f"error should be on line 2, got line {errors[0][0]}"
    assert "пять" in errors[0][1]
    selected = [e for e in entries if e.score is not None]
    assert len(selected) == 1
    assert selected[0].score == 75


def test_manifest_selection_source_field():
    """Manifest.selection_source defaults to '' and distinguishes human from LLM selections."""
    from autoreels.core.models import Manifest
    fields = Manifest.model_fields
    assert "selection_source" in fields, "Manifest must have selection_source field"
    assert fields["selection_source"].default == "", "default must be '' (LLM/auto path)"


def test_dataset_row_records_both_scores():
    """make_dataset_row includes human_score, heuristic_score, and all features."""
    b = _make_block("Тестовый текст блока для датасета из нескольких слов.")
    b.id = "abc123def456789a"
    b.heuristic_score = 73.5
    b.score_breakdown = {"duration": 15.0, "ends_sentence": 10.0, "opens_sentence": 10.0}
    row = make_dataset_row(b, human_score=85, source_stem="test_video")
    assert row["human_score"] == 85
    assert row["heuristic_score"] == pytest.approx(73.5)
    assert "features" in row
    assert row["features"]["duration"] == 15.0
    assert row["text"] == b.text
    assert row["source"] == "test_video"
    assert row["block_id"] == b.id


# ---------------------------------------------------------------------------
# reviews/ routing: --review and --apply
# ---------------------------------------------------------------------------

def _r0_cfg_stub():
    from types import SimpleNamespace
    bf = SimpleNamespace(
        head_skip_sec=30.0, tail_skip_sec=30.0, speech_density_min=0.4,
        repetition_unique_ratio_min=0.3, artefact_markers=[], promo_keywords=[],
        signoff_phrases=[],
    )
    return SimpleNamespace(
        sentence_pause_sec=1.0, max_sentence_sec=100.0,
        min_meaningful_sec=18.0, max_duration=90, min_pause_for_phrase_end=1.5,
        blocks_filter=bf, source_kind="lecture", host_affirmations=[],
        max_reels=None, min_clip_duration=8.0,
    )


def test_review_writes_to_reviews_dir(tmp_path, monkeypatch):
    """--review writes to reviews/<stem>.review.md regardless of cwd."""
    import autoreels.cloud.blocks as _b
    import autoreels.cloud.compress as _c
    from autoreels import __main__ as cli
    from autoreels.core.models import Transcript, Word

    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)

    tx_file = tmp_path / "lecture.transcript.json"
    tx = Transcript(language="ru", words=[Word(word="Тест", t0=30.0, t1=30.5)])
    tx_file.write_text(tx.model_dump_json())

    fake = _make_block("Текст блока достаточно длинный для review файла.")
    fake.has_internal_speaker_change = False

    monkeypatch.setattr(cli, "load_r0_config", lambda p: _r0_cfg_stub())
    monkeypatch.setattr(_c, "compress_transcript", lambda *a, **k: "compressed")
    monkeypatch.setattr(_b, "candidate_blocks", lambda *a, **k: [fake])
    monkeypatch.setattr(_b, "filter_blocks", lambda *a, **k: ([fake], []))
    monkeypatch.setattr(_b, "export_review", lambda *a, **k: "# REVIEW CONTENT")

    rc = cli.cmd_blocks(str(tx_file), root=str(tmp_path), review=True, out=None)

    assert rc == 0
    # stem of "lecture.transcript.json" → "lecture.transcript"
    out = tmp_path / "reviews" / "lecture.transcript.review.md"
    assert out.exists(), f"expected file at {out}"
    assert out.read_text() == "# REVIEW CONTENT"
    assert not list(other.glob("*.review.md")), "must not write to cwd"


def test_review_explicit_out_wins(tmp_path, monkeypatch):
    """--review --out <path> writes to the given path, not reviews/."""
    import autoreels.cloud.blocks as _b
    import autoreels.cloud.compress as _c
    from autoreels import __main__ as cli
    from autoreels.core.models import Transcript, Word

    tx_file = tmp_path / "x.transcript.json"
    tx = Transcript(language="ru", words=[Word(word="X", t0=30.0, t1=30.5)])
    tx_file.write_text(tx.model_dump_json())
    custom_out = tmp_path / "custom" / "my_review.md"

    fake = _make_block("Текст достаточно длинный.")
    fake.has_internal_speaker_change = False

    monkeypatch.setattr(cli, "load_r0_config", lambda p: _r0_cfg_stub())
    monkeypatch.setattr(_c, "compress_transcript", lambda *a, **k: "compressed")
    monkeypatch.setattr(_b, "candidate_blocks", lambda *a, **k: [fake])
    monkeypatch.setattr(_b, "filter_blocks", lambda *a, **k: ([fake], []))
    monkeypatch.setattr(_b, "export_review", lambda *a, **k: "EXPLICIT")

    custom_out.parent.mkdir(parents=True, exist_ok=True)
    rc = cli.cmd_blocks(str(tx_file), root=str(tmp_path), review=True, out=str(custom_out))

    assert rc == 0
    assert custom_out.read_text() == "EXPLICIT"
    assert not (tmp_path / "reviews").exists(), "reviews/ must not be created when --out given"


def test_apply_reads_bare_filename_from_reviews_dir(tmp_path, monkeypatch):
    """_blocks_do_apply with a bare filename resolves against reviews/, not cwd."""
    from autoreels import __main__ as cli

    reviews = tmp_path / "reviews"
    reviews.mkdir()
    (reviews / "video.review.md").write_text("# source: manifests/video.json\n")

    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)

    # Should read from reviews/ (not cwd/other). Fails on missing manifest, not on review read.
    rc = cli._blocks_do_apply("video.review.md", root=str(tmp_path))
    assert rc == 1  # fails: manifest not found — not FileNotFoundError on the review file
    # Verify: if the review file were NOT in reviews/, it would raise FileNotFoundError.
    (reviews / "video.review.md").unlink()
    import pytest
    with pytest.raises(FileNotFoundError):
        cli._blocks_do_apply("video.review.md", root=str(tmp_path))


def test_apply_accepts_explicit_absolute_path(tmp_path, monkeypatch):
    """_blocks_do_apply with an explicit absolute path reads from that path."""
    from autoreels import __main__ as cli

    custom = tmp_path / "custom" / "review.md"
    custom.parent.mkdir()
    custom.write_text("# source: manifests/video.json\n")

    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)

    rc = cli._blocks_do_apply(str(custom), root=str(tmp_path))
    assert rc == 1  # manifest not found — not review-file-not-found


# ---------------------------------------------------------------------------
# --install / --render / scored-review warning
# ---------------------------------------------------------------------------

def _r0_cfg_full_stub():
    """r0 config stub with all attributes needed by _blocks_do_apply pipeline."""
    from types import SimpleNamespace
    bf = SimpleNamespace(
        head_skip_sec=30.0, tail_skip_sec=30.0, speech_density_min=0.4,
        repetition_unique_ratio_min=0.3, artefact_markers=[], promo_keywords=[],
        signoff_phrases=[],
    )
    return SimpleNamespace(
        sentence_pause_sec=1.0, max_sentence_sec=100.0,
        min_meaningful_sec=18.0, max_duration=90.0, min_pause_for_phrase_end=1.5,
        blocks_filter=bf, source_kind="lecture", host_affirmations=[],
        max_reels=None, min_clip_duration=8.0,
        block_scoring=BlockScoringConfig(),
        dangling_words=[], hanging_end_words=[], hanging_start_words=[],
        tail_sec=0.5, snap_window_sec=3.0, max_micro_pause=0.3,
        max_end_search_sec=5.0, tail_pad_sec=0.7, lead_pad_sec=0.2,
        too_long_policy="keep", min_duration=8.0,
    )


def _setup_apply_env(tmp_path, monkeypatch):
    """Minimal filesystem + monkeypatches for _blocks_do_apply with no scored entries.

    Returns (manifest_path, review_path). The pipeline runs on empty reels (review has
    no scored entries). After completion, the reviews/<stem>.review.json is written.
    """
    import autoreels.cloud.blocks as _b
    import autoreels.cloud.compress as _c
    from autoreels import __main__ as cli
    from autoreels.core import state as _state
    from autoreels.core.models import Manifest, Transcript, Word

    (tmp_path / "manifests").mkdir()
    (tmp_path / "reviews").mkdir()
    (tmp_path / "data" / "cache").mkdir(parents=True)

    sha = "a" * 64
    from autoreels.core.models import Crop, SetupProfile
    setup = SetupProfile(
        setup_id="test", crop=Crop(x=0, y=0, w=720, h=1280),
        scale=[720, 1280], frame=[1920, 1080],
    )
    auto = Manifest(
        source="vid.mp4", source_sha256=sha, source_hash_scheme="sha256",
        duration_preset="default", setup=setup, run_key="testkey", reels=[],
    )
    manifest_path = tmp_path / "manifests" / "vid.json"
    manifest_path.write_text(auto.model_dump_json())

    tx = Transcript(language="ru", words=[Word(word="Тест", t0=10.0, t1=10.5)])
    ahash = "fakehash"
    (tmp_path / "data" / "cache" / f"{ahash}.transcript.json").write_text(tx.model_dump_json())
    (tmp_path / "data" / "cache" / f"{sha}.mp3").write_bytes(b"FAKE")

    # No scored entries → reels=[] after pipeline
    review_path = tmp_path / "reviews" / "vid.review.md"
    review_path.write_text(
        "# source: manifests/vid.json\n"
        "# blocks: 1\n\n"
        "[ 1 ]  30.0s  id=aaa111  score: __\n"
        "Текст блока.\n"
    )

    monkeypatch.setattr(cli, "load_r0_config", lambda p: _r0_cfg_full_stub())
    monkeypatch.setattr(_state, "audio_hash", lambda p: ahash)
    monkeypatch.setattr(_c, "compress_transcript", lambda *a, **k: "")
    monkeypatch.setattr(_b, "candidate_blocks", lambda *a, **k: [])
    monkeypatch.setattr(_b, "filter_blocks", lambda *a, **k: ([], []))

    return manifest_path, review_path


def test_install_copies_to_manifests_dir(tmp_path, monkeypatch):
    """--install overwrites manifests/<stem>.json with the human-selection manifest."""
    from autoreels import __main__ as cli
    from autoreels.core.models import Manifest

    manifest_path, _ = _setup_apply_env(tmp_path, monkeypatch)
    orig = manifest_path.read_text()

    rc = cli._blocks_do_apply("vid.review.md", root=str(tmp_path), install=True)
    assert rc == 0
    new_text = manifest_path.read_text()
    assert new_text != orig, "installed manifest must differ from the auto manifest"
    assert Manifest.model_validate_json(new_text).selection_source == "human"


def test_no_install_leaves_manifest_untouched(tmp_path, monkeypatch):
    """Without --install, manifests/<stem>.json is not changed."""
    from autoreels import __main__ as cli

    manifest_path, _ = _setup_apply_env(tmp_path, monkeypatch)
    orig = manifest_path.read_text()

    rc = cli._blocks_do_apply("vid.review.md", root=str(tmp_path), install=False)
    assert rc == 0
    assert manifest_path.read_text() == orig, "manifest must not change without --install"


def test_render_flag_installs_and_calls_cmd_render_with_manifests_path(tmp_path, monkeypatch):
    """--render installs the manifest and calls cmd_render with the installed (manifests/) path."""
    from types import SimpleNamespace
    from autoreels import __main__ as cli

    _setup_apply_env(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "load_render_config",
                        lambda p: SimpleNamespace(role="both", encoder=SimpleNamespace()))
    rendered = []
    monkeypatch.setattr(cli, "cmd_render", lambda **kw: rendered.append(kw) or [])

    rc = cli._blocks_do_apply("vid.review.md", root=str(tmp_path), render=True)
    assert rc == 0
    assert len(rendered) == 1, "cmd_render must be called once"
    paths = rendered[0].get("_manifest_paths", [])
    assert len(paths) == 1
    assert "reviews" not in str(paths[0]), "render must use installed manifest, not reviews/ path"
    assert "manifests" in str(paths[0]), "render must use installed manifest in manifests/"


def test_review_warns_when_existing_file_has_scores(tmp_path, monkeypatch, capsys):
    """--review warns when the target review file already contains scores."""
    import autoreels.cloud.blocks as _b
    import autoreels.cloud.compress as _c
    from autoreels import __main__ as cli
    from autoreels.core.models import Transcript, Word

    tx_file = tmp_path / "vid.transcript.json"
    tx = Transcript(language="ru", words=[Word(word="Тест", t0=30.0, t1=30.5)])
    tx_file.write_text(tx.model_dump_json())

    fake = _make_block("Текст блока достаточно длинный для файла ревью чтобы пройти фильтр.")
    fake.has_internal_speaker_change = False

    reviews_dir = tmp_path / "reviews"
    reviews_dir.mkdir()
    existing = reviews_dir / "vid.transcript.review.md"
    existing.write_text(
        "# source: manifests/vid.json\n"
        "[ 1 ]  30.0s  id=aaa111  score: 85\n"
        "Текст блока.\n"
    )

    monkeypatch.setattr(cli, "load_r0_config", lambda p: _r0_cfg_stub())
    monkeypatch.setattr(_c, "compress_transcript", lambda *a, **k: "")
    monkeypatch.setattr(_b, "candidate_blocks", lambda *a, **k: [fake])
    monkeypatch.setattr(_b, "filter_blocks", lambda *a, **k: ([fake], []))
    monkeypatch.setattr(_b, "export_review", lambda *a, **k: "CONTENT")

    rc = cli.cmd_blocks(str(tx_file), root=str(tmp_path), review=True, out=None)
    assert rc == 0
    err = capsys.readouterr().err
    assert "ВНИМАНИЕ" in err
    assert "оцен" in err


# ---------------------------------------------------------------------------
# Compact export + compact answer import
# ---------------------------------------------------------------------------

def _make_blocks_for_compact():
    """Two kept blocks with multi-word text (no newlines, no empty lines)."""
    b1 = _make_block(
        "Первая мысль, которая звучит убедительно и должна пройти в клип.",
        start=10.0, end=36.0,
    )
    b2 = _make_block(
        "Вторая мысль — отдельная тема, не связана с первой.",
        start=40.0, end=62.0,
    )
    b1.has_internal_speaker_change = False
    b2.has_internal_speaker_change = False
    return [b1, b2]


def test_compact_export_one_line_per_block():
    """export_compact_review produces exactly one data line per block with collapsed text."""
    from autoreels.cloud.blocks import export_compact_review

    blocks = _make_blocks_for_compact()
    out = export_compact_review(blocks, source_ref="manifests/vid.json", filter_removed_count=3)

    data_lines = [ln for ln in out.splitlines() if ln and not ln.startswith("#")]
    assert len(data_lines) == len(blocks), "one data line per block"

    # Each data line: N | Xs | text
    import re
    for i, (line, b) in enumerate(zip(data_lines, blocks), 1):
        assert line.startswith(f"{i} | "), f"line {i} must start with seq number"
        assert "|" in line
        # Text must be present and must not contain newlines
        parts = line.split(" | ", 2)
        assert len(parts) == 3
        text_part = parts[2]
        assert "\n" not in text_part
        assert text_part == " ".join(b.text.split()), "text must match collapsed block text"


def test_compact_export_has_embedded_prompt():
    """export_compact_review includes the scoring rubric in the header."""
    from autoreels.cloud.blocks import export_compact_review

    blocks = _make_blocks_for_compact()
    out = export_compact_review(blocks, source_ref="manifests/vid.json", filter_removed_count=0)

    assert "# source:" in out
    assert "# format: compact" in out
    assert "80-100" in out, "rubric must be present"
    assert "60-79" in out
    assert "Reply with ONLY" in out or "reply with ONLY" in out.lower()


def test_apply_compact_answer_bare_scores(tmp_path, monkeypatch, capsys):
    """A bare 'number score' answer is applied correctly, including merges."""
    import autoreels.cloud.blocks as _b
    import autoreels.cloud.compress as _c
    from autoreels import __main__ as cli
    from autoreels.core import state as _state
    from autoreels.core.models import Manifest, Transcript, Word, Crop, SetupProfile

    (tmp_path / "manifests").mkdir()
    (tmp_path / "reviews").mkdir()
    (tmp_path / "data" / "cache").mkdir(parents=True)

    sha = "b" * 64
    setup = SetupProfile(
        setup_id="s", crop=Crop(x=0, y=0, w=720, h=1280),
        scale=[720, 1280], frame=[1920, 1080],
    )
    m = Manifest(
        source="v.mp4", source_sha256=sha, source_hash_scheme="sha256",
        duration_preset="default", setup=setup, run_key="k", reels=[],
    )
    (tmp_path / "manifests" / "v.json").write_text(m.model_dump_json())

    # Transcript with enough words to form blocks
    words = [Word(word=f"слово{i}", t0=float(i * 2), t1=float(i * 2 + 1)) for i in range(60)]
    tx = Transcript(language="ru", words=words)
    ahash = "txhash"
    (tmp_path / "data" / "cache" / f"{ahash}.transcript.json").write_text(tx.model_dump_json())
    (tmp_path / "data" / "cache" / f"{sha}.mp3").write_bytes(b"FAKE")

    # Two fake kept blocks
    from autoreels.cloud.blocks import CandidateBlock, _Line
    b1 = CandidateBlock(
        id="id1111", start=10.0, end=40.0, duration=30.0,
        text="Текст первого блока здесь",
        boundary_reason="pause", lines=[_Line(10.0, 40.0, "Текст первого блока здесь")],
    )
    b2 = CandidateBlock(
        id="id2222", start=42.0, end=72.0, duration=30.0,
        text="Текст второго блока здесь",
        boundary_reason="pause", lines=[_Line(42.0, 72.0, "Текст второго блока здесь")],
    )

    # Bare answer: score block 1 with merge, block 2 alone (prose around)
    answer = (
        "# source: manifests/v.json\n"
        "1 85+\n"
        "2 70\n"
    )
    answer_path = tmp_path / "reviews" / "v.answer.txt"
    answer_path.write_text(answer)

    monkeypatch.setattr(cli, "load_r0_config", lambda p: _r0_cfg_full_stub())
    monkeypatch.setattr(_state, "audio_hash", lambda p: ahash)
    monkeypatch.setattr(_c, "compress_transcript", lambda *a, **k: "")
    monkeypatch.setattr(_b, "candidate_blocks", lambda *a, **k: [b1, b2])
    monkeypatch.setattr(_b, "filter_blocks", lambda *a, **k: ([b1, b2], []))

    rc = cli._blocks_do_apply(str(answer_path), root=str(tmp_path))
    assert rc == 0
    out_text = capsys.readouterr().out
    # 1+2 merged → should report "merged blocks 1+2" or just "2 blocks selected"
    assert "block" in out_text.lower() or "выбрано" in out_text.lower() or "merged" in out_text.lower()
    # manifest written
    assert (tmp_path / "reviews" / "v.review.json").exists()


def test_apply_compact_answer_ignores_prose(tmp_path, monkeypatch, capsys):
    """A compact answer wrapped in model commentary: ignored lines are counted and reported."""
    import autoreels.cloud.blocks as _b
    import autoreels.cloud.compress as _c
    from autoreels import __main__ as cli
    from autoreels.core import state as _state
    from autoreels.core.models import Manifest, Transcript, Word, Crop, SetupProfile
    from autoreels.cloud.blocks import CandidateBlock, _Line

    (tmp_path / "manifests").mkdir()
    (tmp_path / "reviews").mkdir()
    (tmp_path / "data" / "cache").mkdir(parents=True)

    sha = "c" * 64
    setup = SetupProfile(
        setup_id="s", crop=Crop(x=0, y=0, w=720, h=1280),
        scale=[720, 1280], frame=[1920, 1080],
    )
    m = Manifest(
        source="w.mp4", source_sha256=sha, source_hash_scheme="sha256",
        duration_preset="default", setup=setup, run_key="k", reels=[],
    )
    (tmp_path / "manifests" / "w.json").write_text(m.model_dump_json())

    words = [Word(word=f"word{i}", t0=float(i * 2), t1=float(i * 2 + 1)) for i in range(30)]
    tx = Transcript(language="ru", words=words)
    ahash = "txhash2"
    (tmp_path / "data" / "cache" / f"{ahash}.transcript.json").write_text(tx.model_dump_json())
    (tmp_path / "data" / "cache" / f"{sha}.mp3").write_bytes(b"FAKE")

    b1 = CandidateBlock(
        id="idAA", start=10.0, end=40.0, duration=30.0,
        text="Блок один",
        boundary_reason="pause", lines=[_Line(10.0, 40.0, "Блок один")],
    )

    answer = (
        "# source: manifests/w.json\n"
        "Here are the blocks I found suitable:\n"
        "1 80\n"
        "Let me know if you need more.\n"
    )
    answer_path = tmp_path / "reviews" / "w.answer.txt"
    answer_path.write_text(answer)

    monkeypatch.setattr(cli, "load_r0_config", lambda p: _r0_cfg_full_stub())
    monkeypatch.setattr(_state, "audio_hash", lambda p: ahash)
    monkeypatch.setattr(_c, "compress_transcript", lambda *a, **k: "")
    monkeypatch.setattr(_b, "candidate_blocks", lambda *a, **k: [b1])
    monkeypatch.setattr(_b, "filter_blocks", lambda *a, **k: ([b1], []))

    rc = cli._blocks_do_apply(str(answer_path), root=str(tmp_path))
    assert rc == 0
    out = capsys.readouterr().out
    # Ignored-line count must be reported (2 prose lines)
    assert "2" in out and "skip" in out.lower(), f"expected ignored-count in output, got: {out!r}"


def test_apply_compact_answer_out_of_range_refused(tmp_path, monkeypatch, capsys):
    """Compact answer referencing blocks beyond the manifest range is refused."""
    import autoreels.cloud.blocks as _b
    import autoreels.cloud.compress as _c
    from autoreels import __main__ as cli
    from autoreels.core import state as _state
    from autoreels.core.models import Manifest, Transcript, Word, Crop, SetupProfile
    from autoreels.cloud.blocks import CandidateBlock, _Line

    (tmp_path / "manifests").mkdir()
    (tmp_path / "reviews").mkdir()
    (tmp_path / "data" / "cache").mkdir(parents=True)

    sha = "d" * 64
    setup = SetupProfile(
        setup_id="s", crop=Crop(x=0, y=0, w=720, h=1280),
        scale=[720, 1280], frame=[1920, 1080],
    )
    m = Manifest(
        source="x.mp4", source_sha256=sha, source_hash_scheme="sha256",
        duration_preset="default", setup=setup, run_key="k", reels=[],
    )
    (tmp_path / "manifests" / "x.json").write_text(m.model_dump_json())

    words = [Word(word=f"w{i}", t0=float(i), t1=float(i + 0.5)) for i in range(10)]
    tx = Transcript(language="ru", words=words)
    ahash = "txhash3"
    (tmp_path / "data" / "cache" / f"{ahash}.transcript.json").write_text(tx.model_dump_json())
    (tmp_path / "data" / "cache" / f"{sha}.mp3").write_bytes(b"FAKE")

    b1 = CandidateBlock(
        id="idBB", start=0.0, end=20.0, duration=20.0,
        text="Единственный блок",
        boundary_reason="pause", lines=[_Line(0.0, 20.0, "Единственный блок")],
    )

    # Answer references block 99, but manifest only has 1 block
    answer = "# source: manifests/x.json\n99 85\n"
    answer_path = tmp_path / "reviews" / "x.answer.txt"
    answer_path.write_text(answer)

    monkeypatch.setattr(cli, "load_r0_config", lambda p: _r0_cfg_full_stub())
    monkeypatch.setattr(_state, "audio_hash", lambda p: ahash)
    monkeypatch.setattr(_c, "compress_transcript", lambda *a, **k: "")
    monkeypatch.setattr(_b, "candidate_blocks", lambda *a, **k: [b1])
    monkeypatch.setattr(_b, "filter_blocks", lambda *a, **k: ([b1], []))

    rc = cli._blocks_do_apply(str(answer_path), root=str(tmp_path))
    assert rc == 1
    err = capsys.readouterr().err
    assert "out of range" in err or "not in this manifest" in err


# --------------------------------------------------------------------------- Fix 2: merge markers

def test_resolve_merge_groups_multi_backward_and_dedup():
    """(4) '++' joins three; '-' joins backward; forward+backward on the same pair → one merge."""
    from autoreels.cloud.blocks import resolve_merge_groups, merge_blocks, _ReviewEntry
    blocks = {i: _make_block(f"b{i}.", start=(i - 1) * 20.0, end=(i - 1) * 20.0 + 15.0)
              for i in range(1, 6)}   # 1:[0,15] 2:[20,35] 3:[40,55] 4:[60,75] 5:[80,95]

    # '++' on block 1 → join 1+2+3; '-' on block 5 → join 4+5 (run-up 4 is unscored)
    entries = [_ReviewEntry(1, "", 80, 2, False), _ReviewEntry(5, "", 70, 0, True)]
    groups, over = resolve_merge_groups(entries, blocks, max_duration=90)
    assert groups == [[1, 2, 3], [4, 5]]
    assert over == []

    # forward '+' on 1 and backward '-' on 2 name the SAME edge (1,2) → one merge, not two
    entries2 = [_ReviewEntry(1, "", 80, 1, False), _ReviewEntry(2, "", 60, 0, True)]
    groups2, _ = resolve_merge_groups(entries2, {1: blocks[1], 2: blocks[2]}, max_duration=90)
    assert groups2 == [[1, 2]]

    # merge_blocks folds three adjacent blocks into one spanning 1..3
    merged = merge_blocks([blocks[1], blocks[2], blocks[3]])
    assert merged.start == pytest.approx(0.0)
    assert merged.end == pytest.approx(55.0)


def test_resolve_merge_over_max_reported_and_split():
    """(5) a merge whose span exceeds max_duration is reported (over_max) and split, not trimmed."""
    from autoreels.cloud.blocks import resolve_merge_groups, _ReviewEntry
    blocks = {1: _make_block("a.", start=0.0, end=80.0), 2: _make_block("b.", start=81.0, end=140.0)}
    entries = [_ReviewEntry(1, "", 80, 1, False)]   # '+' would join 1+2 → span 140s > 90
    groups, over = resolve_merge_groups(entries, blocks, max_duration=90)
    assert over == [[1, 2]]            # reported by block number
    assert groups == [[1], [2]]        # split back to singletons — span not trimmed


def test_compact_export_prompt_documents_merge_markers():
    """(6) the compact export's embedded prompt documents ++ and the backward '-' marker."""
    from autoreels.cloud.blocks import export_compact_review
    out = export_compact_review([_make_block("hi", start=0.0, end=20.0)],
                                source_ref="m.json", filter_removed_count=0)
    assert "++" in out
    assert "next TWO" in out                       # ++ = join the next two
    assert "PRECEDING" in out                       # '-' = join with the preceding block


def test_parse_score_markers_backward_and_double_forward():
    """Score-field parser: '-NN' → backward, 'NN++' → merge_fwd=2, bare '-'/'__' → skip."""
    from autoreels.cloud.blocks import _parse_score_markers
    assert _parse_score_markers("85") == (85, 0, False, None, None)
    assert _parse_score_markers("85+") == (85, 1, False, None, None)
    assert _parse_score_markers("85++") == (85, 2, False, None, None)
    assert _parse_score_markers("-90") == (90, 0, True, None, None)
    assert _parse_score_markers("-90+") == (90, 1, True, None, None)
    assert _parse_score_markers("__")[0] is None
    assert _parse_score_markers("-")[0] is None      # bare dash still means skip
    assert _parse_score_markers("++")[4] is not None  # marker without a score → error


# --------------------------------------------------------------------------- block_target_sec (M1.6)
# "Let a block run to the length of a thought, not to the first full stop." A soft boundary
# (sentence end, no pause) holds the block open until block_target_sec; hard boundaries always close.

def test_soft_boundary_below_target_does_not_close():
    """(1) a sentence end with no pause does NOT close a block below the target length."""
    # Two 15s sentences, gap 0.3s (< min_pause) → soft boundary between them. target=40 → one block.
    compressed = _compressed(
        _line(0, 15, "Первая короткая законченная мысль спикера."),
        _line(15.3, 30.3, "Он тут же продолжил второй короткой мыслью."),
    )
    blocks = candidate_blocks(compressed, min_sec=MIN_SEC, max_sec=MAX_SEC,
                              min_pause_for_phrase_end=MIN_PAUSE, block_target_sec=40.0)
    assert len(blocks) == 1
    assert blocks[0].duration == pytest.approx(30.3)


def test_soft_boundary_above_target_closes():
    """(2) a sentence end past the target length DOES close the block."""
    # First sentence already 42s (> target 40); soft boundary after it closes the block.
    compressed = _compressed(
        _line(0, 42, "Очень длинная но грамматически законченная мысль на сорок две секунды."),
        _line(42.3, 62.3, "Следующая мысль после точки без паузы."),
    )
    blocks = candidate_blocks(compressed, min_sec=MIN_SEC, max_sec=MAX_SEC,
                              min_pause_for_phrase_end=MIN_PAUSE, block_target_sec=40.0)
    assert len(blocks) == 2
    assert blocks[0].duration == pytest.approx(42.0)


def test_hard_pause_closes_regardless_of_length():
    """(3) a pause above the threshold closes a block regardless of length (even below target)."""
    # Two 20s lines (each >= min_sec so neither is merged away), gap 2.0s (> min_pause) → hard
    # pause boundary closes the first block at 20s, well below the 40s target.
    compressed = _compressed(
        _line(0, 20, "Первая мысль всего двадцать секунд."),
        _line(22.0, 42.0, "Вторая мысль после реальной паузы в две секунды."),
    )
    blocks = candidate_blocks(compressed, min_sec=MIN_SEC, max_sec=MAX_SEC,
                              min_pause_for_phrase_end=MIN_PAUSE, block_target_sec=40.0)
    assert len(blocks) == 2
    assert blocks[0].duration == pytest.approx(20.0)   # closed below target by the hard pause
    assert blocks[1].boundary_reason == "pause"


def test_target_corpus_still_within_bounds():
    """(4) duration bounds still hold across a generated corpus with the target-length policy."""
    rng = random.Random(7)
    t = 0.0
    lines = []
    for _ in range(80):
        dur = rng.uniform(3.0, 24.0)
        gap = rng.uniform(0.05, 2.5)
        words = ["слово"] * rng.randint(3, 12)
        if rng.random() > 0.4:
            words[-1] += "."                    # ~60% end on a full stop → soft boundaries
        lines.append(_line(t, t + dur, " ".join(words)))
        t += dur + gap
    blocks = candidate_blocks(_compressed(*lines), min_sec=MIN_SEC, max_sec=MAX_SEC,
                              min_pause_for_phrase_end=MIN_PAUSE, block_target_sec=40.0)
    violations = [f"[{b.start:.1f}-{b.end:.1f}] {b.duration:.1f}s" for b in blocks
                  if not (MIN_SEC <= b.duration <= MAX_SEC)]
    assert not violations, f"blocks out of [{MIN_SEC},{MAX_SEC}]: {violations}"


def test_soft_accumulation_cannot_exceed_max():
    """(5) a block cannot exceed max_duration by continuing through soft boundaries."""
    # target=40, max=50, sentences of 30s each with no pause (soft boundaries).
    # After the first 30s sentence (< target) continuing to the next boundary would reach 60s > 50,
    # so the block must close at 30s rather than overrun the ceiling.
    lines = [_line(i * 30.3, i * 30.3 + 30, f"Законченная мысль номер {i} на тридцать секунд.")
             for i in range(4)]
    blocks = candidate_blocks(_compressed(*lines), min_sec=MIN_SEC, max_sec=50.0,
                              min_pause_for_phrase_end=MIN_PAUSE, block_target_sec=40.0)
    assert blocks, "expected at least one block"
    for b in blocks:
        assert b.duration <= 50.0, f"block exceeded max: {b.duration:.1f}s"
