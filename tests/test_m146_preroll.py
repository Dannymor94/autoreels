"""M146 (owner: «давай» — the editor's pre-roll, an exception to invariant 10 by his decision): a clip's first word glued
to the word before starts start_preroll_sec earlier, and the render fades the sound in."""
from __future__ import annotations

from autoreels.cloud.plan import ManualPlanParams, build_manual_plan
from autoreels.core.config import AudioProcessing, R0Config
from autoreels.local.render import _start_fade_in
from tests.test_filler_cut import _setup

GLUED = [[("Раз", 0.0, 0.4), ("два.", 0.5, 1.98)], [("Сначала", 2.0, 2.6), ("так.", 2.7, 3.1)], [("Конец.", 4.0, 4.5)]]
APART = [[("Раз", 0.0, 0.4), ("два.", 0.5, 1.2)], [("Сначала", 2.0, 2.6), ("так.", 2.7, 3.1)], [("Конец.", 4.0, 4.5)]]


def _start(spec, **kw):
    s, w, sm, al = _setup(spec, [])
    return build_manual_plan(s, [2, 3], words=w, smap=sm, params=ManualPlanParams(**kw), align=al).windows[0].start


def test_off_by_default():
    assert ManualPlanParams().start_preroll_sec == 0.0
    assert R0Config.model_fields["start_preroll_sec"].default == 0.0
    assert AudioProcessing.model_fields["start_fade_in_sec"].default == 0.0
    assert abs(_start(GLUED) - 1.99) < 1e-6                    # the middle of the 0.02 s gap, as before


def test_a_glued_first_word_starts_in_the_tail_of_the_word_before():
    assert abs(_start(GLUED, start_preroll_sec=0.06) - 1.94) < 1e-6


def test_a_first_word_after_a_pause_is_not_moved():
    assert abs(_start(APART, start_preroll_sec=0.06) - _start(APART)) < 1e-6


def test_prerolled_flag_set_on_glued_start_segment():
    """prerolled=True on the first Segment so _check_seam_inside_word skips its start."""
    s, w, sm, al = _setup(GLUED, [])
    plan = build_manual_plan(s, [2, 3], words=w, smap=sm, params=ManualPlanParams(start_preroll_sec=0.06), align=al)
    assert plan.windows[0].prerolled is True
    assert plan.windows[0].segment().prerolled is True


def test_prerolled_flag_not_set_when_off_or_paused():
    s, w, sm, al = _setup(GLUED, [])
    plan_off = build_manual_plan(s, [2, 3], words=w, smap=sm, params=ManualPlanParams(), align=al)
    assert plan_off.windows[0].prerolled is False
    s, w, sm, al = _setup(APART, [])
    plan_apart = build_manual_plan(s, [2, 3], words=w, smap=sm, params=ManualPlanParams(start_preroll_sec=0.06), align=al)
    assert plan_apart.windows[0].prerolled is False


def test_render_fade_in_only_when_on_and_planned():
    class _AP:
        start_fade_in_sec = 0.03
    assert _start_fade_in(_AP(), True) == "afade=t=in:st=0:d=0.03"
    assert _start_fade_in(_AP(), False) == ""
    class _Off:
        start_fade_in_sec = 0.0
    assert _start_fade_in(_Off(), True) == ""
