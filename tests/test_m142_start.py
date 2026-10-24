"""M142 (owner on IMG_6848 m126): «часто не слышно первой буквы слова» — a clip's first sound keeps start_pad_sec of
air (0 = the inner seam pad, as before), never reaching into the speech before it; the scenarist's tone line."""
from __future__ import annotations

from autoreels.cloud.plan import ManualPlanParams, build_manual_plan
from autoreels.cloud.scenario import tone_rule
from autoreels.core.config import AutocutConfig
from tests.test_filler_cut import _setup

SPEC = [[("Раз", 0.0, 0.4), ("два.", 0.5, 0.9)],            # s1: speech before the clip
        [("Сначала", 2.0, 2.6), ("так.", 2.7, 3.1)],        # s2: the clip starts here (1.1 s of silence before)
        [("Потом", 3.15, 3.6), ("вот.", 3.7, 4.0)],         # s3: right after s2 (0.05 s)
        [("Конец.", 6.0, 6.5)]]


def test_off_by_default_is_the_seam_pad():
    sents, words, smap, align = _setup(SPEC, [])
    w = build_manual_plan(sents, [2, 3], words=words, smap=smap, params=ManualPlanParams(), align=align).body[0]
    assert abs(w.start - (2.0 - 0.04)) < 1e-6


def test_first_sound_keeps_start_pad_inner_seams_do_not():
    sents, words, smap, align = _setup(SPEC, [])
    p = ManualPlanParams(start_pad_sec=0.15)
    plan = build_manual_plan(sents, [2, 4], words=words, smap=smap, params=p, align=align)
    first, second = plan.body[0], plan.body[1]
    assert abs(first.start - (2.0 - 0.15)) < 1e-6           # the clip's first word: 0.15 s of air
    assert abs(second.start - (6.0 - 0.04)) < 1e-6          # an inner seam keeps the seam pad


def test_start_pad_never_reaches_into_the_speech_before():
    spec = [[("Раз", 0.0, 0.4), ("два.", 0.5, 1.9)], [("Сначала", 2.0, 2.6), ("так.", 2.7, 3.1)]]
    sents, words, smap, align = _setup(spec, [])
    w = build_manual_plan(sents, [2], words=words, smap=smap, params=ManualPlanParams(start_pad_sec=0.3),
                          align=align).body[0]
    assert w.start >= 1.95 - 1e-6                           # the middle of the 0.1 s silence, not 1.7


def test_cold_open_keeps_start_pad():
    sents, words, smap, align = _setup(SPEC, [])
    plan = build_manual_plan(sents, [2, 3], words=words, smap=smap, params=ManualPlanParams(start_pad_sec=0.15),
                             align=align, hook=4, hook_mode="-")
    assert plan.cold_open is not None and abs(plan.cold_open.start - (6.0 - 0.15)) < 1e-6
    assert abs(plan.windows[1].start - (2.0 - 0.15)) < 1e-6   # the body after the teaser starts the same way


def test_tone_rule():
    assert tone_rule("") == "" and tone_rule("   ") == ""
    assert "«фановый»" in tone_rule("фановый")
    assert AutocutConfig().scenario_tone == ""
