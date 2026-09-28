"""Tests for min_score, dedup, artefact scrubbing, and tag-question dangling starts."""
import json
import pytest

from autoreels.cloud.blocks import CandidateBlock, _Line, _scrub_artefact_lines, filter_blocks
from autoreels.cloud.select import dedup, filter_by_score, filter_dangling_start
from autoreels.core.models import Reel, Word


def _reel(rid, start, end, score):
    return Reel(id=rid, start=start, end=end, score=score,
                hook="hook", title="", description="")


# ----------------------------------------------------------------- min_score

def test_filter_by_score_drops_below_threshold():
    reels = [_reel("a", 0, 30, 80), _reel("b", 40, 70, 60), _reel("c", 80, 110, 40)]
    kept = filter_by_score(reels, min_score=65)
    assert [r.id for r in kept] == ["a"]  # 60 < 65 and 40 < 65, both dropped


def test_filter_by_score_keeps_all_when_all_above():
    reels = [_reel("a", 0, 30, 90), _reel("b", 40, 70, 70)]
    kept = filter_by_score(reels, min_score=65)
    assert len(kept) == 2


def test_filter_by_score_drops_all_when_all_below():
    reels = [_reel("a", 0, 30, 30), _reel("b", 40, 70, 50)]
    kept = filter_by_score(reels, min_score=65)
    assert kept == []


# ----------------------------------------------------------------- dedup

def test_dedup_keeps_higher_llm_score():
    """Two overlapping reels: higher score wins."""
    hi = _reel("hi", 0.0, 60.0, 90)
    lo = _reel("lo", 5.0, 65.0, 70)
    dropped = []
    kept = dedup([hi, lo], overlap_threshold=0.5, dropped=dropped)
    assert [r.id for r in kept] == ["hi"]
    assert len(dropped) == 1
    assert dropped[0]["id"] == "lo"
    assert "overlap_dedup" in dropped[0]["reason"]


def test_dedup_no_overlap_keeps_both():
    a = _reel("a", 0.0, 30.0, 80)
    b = _reel("b", 60.0, 90.0, 70)
    kept = dedup([a, b], overlap_threshold=0.5)
    assert len(kept) == 2


def test_dedup_exact_threshold_kept():
    """Overlap == threshold: block is NOT dropped (> not >=)."""
    a = _reel("a", 0.0, 60.0, 80)
    b = _reel("b", 30.0, 90.0, 70)  # overlap=30/60=0.5 for b over a
    kept = dedup([a, b], overlap_threshold=0.5)
    assert len(kept) == 2


# ----------------------------------------------------------------- artefact scrub

def _block_with_lines(*lines: tuple[float, float, str]) -> CandidateBlock:
    ls = [_Line(t0, t1, text) for t0, t1, text in lines]
    return CandidateBlock(
        id="test", start=ls[0].t0, end=ls[-1].t1,
        duration=ls[-1].t1 - ls[0].t0,
        text=" ".join(l.text for l in ls),
        boundary_reason="sentence",
        lines=ls,
    )


def test_scrub_artefact_drops_block_entirely_credit():
    """Block that is only 'Субтитры делал DimaTorzok' → returns False (drop it)."""
    block = _block_with_lines((1321.0, 1322.5, "Субтитры делал DimaTorzok"))
    result = _scrub_artefact_lines(block, ["субтитры делал"])
    assert result is False, "entirely-credit block should return False"


def test_scrub_artefact_strips_leading_credit_line():
    """Leading 'Субтитры делал …' is stripped; real speech after it survives."""
    block = _block_with_lines(
        (1321.0, 1322.5, "Субтитры делал DimaTorzok"),
        (1322.5, 1360.0, "Холотропное дыхание — глубокая практика."),
    )
    result = _scrub_artefact_lines(block, ["субтитры делал"])
    assert result is True
    assert "DimaTorzok" not in block.text
    assert block.start == 1322.5


def test_filter_blocks_drops_sole_artefact_line_with_new_marker(tmp_path):
    """filter_blocks with 'субтитры делал' in artefact_markers drops the block."""
    credit_line = _Line(1321.0, 1322.5, "Субтитры делал DimaTorzok")
    block = CandidateBlock(
        id="art", start=1321.0, end=1322.5, duration=1.5,
        text="Субтитры делал DimaTorzok", boundary_reason="sentence",
        lines=[credit_line],
    )
    kept, dropped = filter_blocks(
        [block], total_duration=1500.0,
        artefact_markers=["субтитры делал"],
    )
    assert len(kept) == 0
    reasons = [r for _, r in dropped]
    assert "artefact" in reasons


# ----------------------------------------------------------------- tag-question dangling start

def _ws(pairs):
    return [Word(word=w, t0=t0, t1=t1) for w, t0, t1 in pairs]


def _simple_reel(rid, start, end, score=80):
    return Reel(id=rid, start=start, end=end, score=score, hook="h", title="", description="")


TAG_QUESTIONS = ["Ясно?", "Понятно?", "Да?", "Правильно?", "Согласны?"]
TAG_CLEAN    = ["ясно", "понятно", "да", "правильно", "согласны"]


@pytest.mark.parametrize("word,clean", list(zip(TAG_QUESTIONS, TAG_CLEAN)))
def test_tag_question_repaired_via_tag_question_words(word, clean):
    """'Ясно? Но вот…' with tag_question_words=[clean] → start moves to next word."""
    words = _ws([
        (word, 0.0, 0.5),
        ("Но", 0.5, 0.8),
        ("вот", 0.8, 1.2),
        ("это", 1.2, 1.6),
        ("важно.", 1.6, 2.0),
        *[(f"слово{i}.", float(2 + i), float(3 + i)) for i in range(15)],
    ])
    r = _simple_reel("t", start=0.0, end=20.0)
    kept, disc = filter_dangling_start([r], words, tag_question_words=[clean],
                                       min_duration=15.0, max_start_repair_sec=10.0)
    assert len(kept) == 1 and len(disc) == 0
    assert kept[0].start == pytest.approx(0.5), f"{word} not repaired, start={kept[0].start}"


def test_tag_question_not_repaired_without_question_mark():
    """'Понятно, что мы…' — no '?' → NOT treated as tag question, passes unchanged."""
    words = _ws([("Понятно,", 0.0, 0.5), ("что", 0.5, 0.8), ("мы", 0.8, 1.1)] +
                [(f"слово{i}.", float(1 + i), float(2 + i)) for i in range(18)])
    r = _simple_reel("t", start=0.0, end=20.0)
    kept, disc = filter_dangling_start([r], words, tag_question_words=["понятно"],
                                       min_duration=15.0, max_start_repair_sec=10.0)
    assert len(kept) == 1
    assert kept[0].start == pytest.approx(0.0)


def test_da_comma_not_repaired():
    """'Да, это так.' — no '?' → NOT a tag question."""
    words = _ws([("Да,", 0.0, 0.3), ("это", 0.3, 0.6), ("так.", 0.6, 1.0)] +
                [(f"слово{i}.", float(1 + i), float(2 + i)) for i in range(18)])
    r = _simple_reel("t", start=0.0, end=20.0)
    kept, disc = filter_dangling_start([r], words, tag_question_words=["да"],
                                       min_duration=15.0, max_start_repair_sec=10.0)
    assert len(kept) == 1
    assert kept[0].start == pytest.approx(0.0)


def test_pravilno_without_question_not_repaired():
    """'Правильно ли…' — no '?' → NOT a tag question."""
    words = _ws([("Правильно", 0.0, 0.5), ("ли", 0.5, 0.8)] +
                [(f"слово{i}.", float(1 + i), float(2 + i)) for i in range(18)])
    r = _simple_reel("t", start=0.0, end=20.0)
    kept, disc = filter_dangling_start([r], words, tag_question_words=["правильно"],
                                       min_duration=15.0, max_start_repair_sec=10.0)
    assert len(kept) == 1
    assert kept[0].start == pytest.approx(0.0)
