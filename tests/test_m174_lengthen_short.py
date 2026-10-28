"""M174 (m173: 53 short shots «inside a sentence» — a cut a second after a seam or another cut): a played piece
shorter than short_shot_sec is lengthened with the silence of the neighbouring cut, else that cut is dropped; a piece
of whole sentences only is left to the automatic line check. short_shot_sec 0 = the previous cuts."""
from dataclasses import replace

import pytest

from autoreels.cloud.plan import ManualPlanParams, build_manual_plan
from tests.test_filler_cut import _setup

BASE = ManualPlanParams(filler_cut=True, long_pause_sec=1.5)
ON = replace(BASE, short_shot_sec=2.0)
# «Как вы» … 3.5 s of thinking … «считаете это важно?» «Да, конечно, это важно очень.»
SPEC = [[("Как", 0.0, 0.4), ("вы", 0.5, 0.8), ("считаете", 4.3, 5.0), ("это", 5.1, 5.4), ("важно?", 5.5, 6.0)],
        [("Да,", 6.4, 6.8), ("конечно,", 6.9, 7.5), ("это", 7.6, 7.9), ("важно", 8.0, 8.5), ("очень.", 8.6, 9.2)]]


def _shots(w):
    return [round(b - a, 3) for a, b in w.pieces()]


def test_off_keeps_the_old_cut():
    sents, words, smap, align = _setup(SPEC, [])
    w = build_manual_plan(sents, [1, 2], words=words, smap=smap, params=BASE, align=align).body[0]
    assert len(w.cuts) == 1 and _shots(w)[0] < 1.0                     # «Как вы» alone: under a second


def test_short_piece_inside_a_sentence_takes_silence_from_the_cut():
    sents, words, smap, align = _setup(SPEC, [])
    plan = build_manual_plan(sents, [1, 2], words=words, smap=smap, params=ON, align=align)
    w = plan.body[0]
    assert len(w.cuts) == 1 and _shots(w)[0] == pytest.approx(2.0, abs=0.01)
    assert w.cuts[0][1] < 4.3 and w.cuts[0][1] - w.cuts[0][0] >= ON.min_cut_sec
    assert not [x for x in plan.warnings if x.startswith("short shot")]


def test_no_silence_to_take_drops_the_cut():
    sents, words, smap, align = _setup(SPEC, [[0.9, 4.2]])            # the «pause» is untranscribed sound
    w = build_manual_plan(sents, [1, 2], words=words, smap=smap, params=ON, align=align).body[0]
    assert w.cuts == []


def test_whole_sentence_piece_is_left_to_the_line_check():
    spec = [[("Короче.", 0.0, 0.75)],
            [("Если", 3.05, 3.4), ("так,", 3.5, 4.0), ("то", 4.1, 4.3), ("всё", 4.4, 4.8), ("понятно.", 4.9, 6.5)],
            [("Дальше", 6.9, 7.4), ("будет", 7.5, 8.0), ("проще.", 8.1, 9.0)]]
    sents, words, smap, align = _setup(spec, [])
    plan = build_manual_plan(sents, [1, 2, 3], words=words, smap=smap, params=ON, align=align)
    w = plan.body[0]
    assert len(w.cuts) == 1 and _shots(w)[0] < 1.0
    assert any(x.startswith("short shot") and "whole sentences s1@0.000" in x for x in plan.warnings)
