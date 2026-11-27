"""One user-facing cut scenario via the existing manual planner, no media."""
import copy

import pytest

from autoreels.cloud.plan import ManualPlanParams, build_manual_plan
from autoreels.core.models import Reel, Word
from autoreels.orchestr import sentence_edit as edit


def fixture():
    words = [Word(word=text,t0=float(i),t1=i+0.9)
             for i,text in enumerate(("Начало.", "Убираем.", "Продолжаем.", "Конец."))]
    sents = [[w] for w in words]
    smap = {"words":[{"idx":i,"t0":w.t0,"t1":w.t1,
                      "audible_start":i+0.2,"audible_end":i+0.8}
                     for i,w in enumerate(words)], "boundaries":[]}
    params = ManualPlanParams()
    order = (1,2,3,4)
    baseline = build_manual_plan(sents, order, words=words, smap=smap,
                                 params=params, source_duration=4.0)
    base = Reel(id="r01",start=baseline.start,end=baseline.end,score=80,hook="",
                title="fixture",description="fixture",planned=True,
                segments=[s for w in baseline.body for s in w.segments()],
                subtitles=baseline.subtitles, tail_last_word_end=baseline.last_audible_end,
                tail_next_word_start=baseline.next_onset)
    return base, dict(sentences=sents,words=words,smap=smap,play=order,
                      params=params,source_duration=4.0)


def test_removal_preview_uses_audio_map_and_keeps_source_plan():
    base, args = fixture()
    before = base.model_dump_json()
    proposal = edit.remove_sentences(base, selected=(2,), **args)
    assert proposal.kept_sentences == (1,3,4)
    assert proposal.removed_sentences == (2,)
    assert [w.word for w in proposal.plan.subtitles] == ["Начало.","Продолжаем.","Конец."]
    assert len(proposal.plan.body) == 2
    assert proposal.plan.body[0].end < 1.2
    assert proposal.plan.body[1].start > 1.8
    assert base.model_dump_json() == before
    assert edit.remove_sentences(base, selected=(2,), **args).plan.describe(args["sentences"]) == proposal.plan.describe(args["sentences"])


def test_stale_plan_ambiguous_evidence_and_empty_selection_rejected():
    base, args = fixture()
    with pytest.raises(edit.Unavailable,match="cannot be reproduced"):
        edit.remove_sentences(base.model_copy(update={"end":base.end+0.01}), selected=(2,), **args)
    for selected in ((),(1,2,3,4),(1,3),(5,)):
        with pytest.raises(edit.Unavailable):
            edit.remove_sentences(base,selected=selected,**args)
    missing = copy.deepcopy(args["smap"])
    missing["words"].pop(1)
    with pytest.raises(edit.Unavailable,match="speech map"):
        edit.remove_sentences(base,selected=(2,),**{**args,"smap":missing})
    with pytest.raises(edit.Unavailable,match="complex plan"):
        edit.remove_sentences(base.model_copy(update={"speed":2.0}),selected=(2,),**args)


def test_does_not_claim_cut_when_removed_sound_is_still_played():
    base, args = fixture()
    # Removed sentence shares actual sound with the next kept one. Rebuild the
    # baseline from this evidence so only the removal guard can reject it.
    smap = copy.deepcopy(args["smap"])
    smap["words"][1]["audible_end"] = 2.45
    args["smap"] = smap
    baseline = build_manual_plan(args["sentences"], args["play"],words=args["words"],
        smap=smap,params=args["params"],source_duration=args["source_duration"])
    base = base.model_copy(update={"start":baseline.start,"end":baseline.end,
        "segments":[s for w in baseline.body for s in w.segments()],
        "subtitles":baseline.subtitles,"tail_last_word_end":baseline.last_audible_end,
        "tail_next_word_start":baseline.next_onset})
    with pytest.raises(edit.Unavailable):
        edit.remove_sentences(base, selected=(2,), **args)
