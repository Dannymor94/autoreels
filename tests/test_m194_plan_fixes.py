"""M194 (m191 → m192: plan and render faults found on the assistant's reference labelling).
(a) a montage cold open from outside the body (h:37.2 after the body) — its words were sorted after the body's, the
last subtitle was the hook's word and --apply refused."""
from __future__ import annotations


def test_m194_hook_outside_the_body_plays_first_in_the_subtitles_too():
    """m191 (prew_isaev_danny M6, h:37.2 after the body): the cold open's words came last in the subtitles."""
    from autoreels.cloud.plan import ManualPlanParams, build_manual_plan
    from tests.test_filler_cut import _setup
    s1 = [("Самое", 0.0, 0.4), ("частое", 0.45, 0.9), ("заблуждение,", 0.95, 1.6), ("что", 1.7, 1.9),
          ("человек", 1.95, 2.4), ("не", 2.45, 2.6), ("такой.", 2.65, 3.2)]
    s2 = [("Человек", 4.0, 4.5), ("понимает,", 4.55, 5.2), ("куда", 5.3, 5.6), ("идти.", 5.65, 6.3)]
    s3 = [("Ты", 20.0, 20.2), ("не", 20.25, 20.4), ("поломан,", 20.45, 21.0), ("ты", 21.3, 21.4),
          ("забыл", 21.45, 21.8), ("свою", 21.85, 22.1), ("силу.", 22.15, 22.8)]
    sents, words, smap, align = _setup([s1, s2, s3], [])
    plan = build_manual_plan(sents, [1, 2], words=words, smap=smap, params=ManualPlanParams(), hook=3,
                             hook_mode=None, align=align)
    shown = [w.word for w in plan.subtitles]
    assert shown[:7] == ["Ты", "не", "поломан,", "ты", "забыл", "свою", "силу."]     # heard first, shown first
    assert shown[-1] == "идти." and plan.last_word.word == "идти."                   # the last subtitle = last heard
    s0 = [("Сначала", 10.0, 10.5), ("было", 10.55, 10.9), ("трудно.", 10.95, 11.6)]
    sents, words, smap, align = _setup([s1, s0], [])                                # a teaser inside the body: as before
    plan = build_manual_plan(sents, [1, 2], words=words, smap=smap, params=ManualPlanParams(), hook=2,
                             hook_mode="!", align=align)
    assert [w.word for w in plan.subtitles][0] == "Самое"
