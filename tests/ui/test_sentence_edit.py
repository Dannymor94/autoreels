"""One user-facing cut scenario via the existing manual planner, no media."""
import copy
from itertools import permutations

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


def reorder_fixture(play=(1, 2, 3), params=None):
    words = [Word(word=text, t0=float(i), t1=i + 0.9)
             for i, text in enumerate(("Начало.", "Середина.", "Конец."))]
    args = dict(sentences=[[w] for w in words], words=words,
                smap={"words": [{"idx": i, "t0": w.t0, "t1": w.t1,
                                 "audible_start": i + 0.2, "audible_end": i + 0.8}
                                for i, w in enumerate(words)], "boundaries": []},
                params=params or ManualPlanParams(), source_duration=3.0)
    plan = build_manual_plan(**args, play=play)
    assert not plan.errors
    reel = Reel(id="r01", start=plan.start, end=plan.end, score=80, hook="",
                title="fixture", description="fixture", planned=True,
                segments=[s for w in plan.body for s in w.segments()],
                subtitles=plan.subtitles, tail_last_word_end=plan.last_audible_end,
                tail_next_word_start=plan.next_onset,
                reordered=tuple(sorted(play)) != play)
    return reel, args


@pytest.mark.parametrize("order", list(permutations((1, 2, 3))))
def test_permutation_and_restore(order):
    base, args = reorder_fixture()
    original = base.model_dump_json()
    result = edit.reorder_sentences(base, play=(1, 2, 3), order=order, **args)
    assert base.model_dump_json() == original
    assert [w.word for w in result.subtitles] == [args["words"][n-1].word for n in order]
    assert result.reordered == (order != (1, 2, 3))
    result.check_segments()
    assert result.playback_duration() > 0
    restored = edit.reorder_sentences(result, play=order, order=(1, 2, 3), **args)
    assert restored.model_dump_json() == original


@pytest.mark.parametrize("order", [(1, 1, 3), (1, 2), (1, 2, 4), (True, 2, 3), ()])
def test_invalid_order(order):
    base, args = reorder_fixture()
    with pytest.raises(edit.Unavailable):
        edit.reorder_sentences(base, play=(1, 2, 3), order=order, **args)


def test_preserves_previous_cut():
    base, args = reorder_fixture((1, 3))
    result = edit.reorder_sentences(base, play=(1, 3), order=(3, 1), **args)
    assert [w.word for w in result.subtitles] == ["Конец.", "Начало."]
    assert all(min(s.end, 1.8) - max(s.start, 1.2) <= 1e-6
               for s in result.effective_segments())


def test_stale_or_ambiguous_evidence_is_rejected():
    base, args = reorder_fixture()
    with pytest.raises(edit.Unavailable):
        edit.reorder_sentences(base.model_copy(update={"end": base.end + .1}),
                          play=(1, 2, 3), order=(3, 1, 2), **args)
    args["smap"]["words"].pop()
    with pytest.raises(edit.Unavailable):
        edit.reorder_sentences(base, play=(1, 2, 3), order=(3, 1, 2), **args)


@pytest.mark.parametrize("play", [(1,3), (3,1)])
def test_trim_silence_preserves_cut_and_play_order(play):
    # The default planner leaves only 40 ms at internal seams, already
    # below the demo's 50 ms trim guard. Use an explicit wider-air fixture.
    base,args=reorder_fixture(play, ManualPlanParams(seam_pad_sec=0.15))
    before=base.model_dump_json()
    old=base.effective_segments()[0]
    a,b=play[0]-1+0.2,play[0]-1+0.8
    start=max(old.start,a-0.075)
    end=min(old.end,b+0.075)
    assert start>old.start or end<old.end
    trimmed=edit.trim_silence(base,play=play,segment_index=0,start=start,end=end,**args)
    assert base.model_dump_json()==before
    assert trimmed.reordered==base.reordered
    assert trimmed.start==start and trimmed.end==base.end
    assert trimmed.effective_segments()[1:]==base.effective_segments()[1:]
    assert trimmed.playback_duration()==pytest.approx(
        base.playback_duration()-(start-old.start)-(old.end-end))
    assert [w.word for w in trimmed.subtitles]==[w.word for w in base.subtitles]
    assert start<trimmed.subtitles[0].t0<=a and trimmed.subtitles[0].t1<=end
    assert trimmed.subtitles[1:]==base.subtitles[1:]
    trimmed.check_segments()
    assert all(min(s.end,1.8)-max(s.start,1.2)<=1e-6
               for s in trimmed.effective_segments())


def test_trim_silence_refuses_speech_expansion_stale_and_invalid_bounds():
    play=(1,3)
    base,args=reorder_fixture(play)
    old=base.effective_segments()[0]
    for index,start,end in [(0,0.18,old.end),(0,old.start,0.81),
                            (0,old.start-0.01,old.end),(0,old.start,old.end),
                            (0,float("nan"),old.end),(True,0.1,old.end),
                            (99,0.1,old.end)]:
        with pytest.raises(edit.Unavailable):
            edit.trim_silence(base,play=play,segment_index=index,start=start,end=end,**args)
    with pytest.raises(edit.Unavailable):
        edit.trim_silence(base.model_copy(update={"end":base.end+0.01}),
                          play=play,segment_index=0,start=0.1,end=old.end,**args)


def test_longform_repeat_candidates_are_review_only_and_local():
    from autoreels.cloud.repeat_candidates import RepeatCandidate, find_repeat_candidates

    texts = [
        "Мы сегодня обсуждаем внутреннюю силу.",
        "МЫ сегодня обсуждаем внутреннюю силу!",
        "Я хочу вам рассказать...",
        "Я хочу вам рассказать одну историю.",
        "Я не хочу вам рассказывать одну историю.",
        "Мы сегодня обсуждаем внутреннюю силу.",
        "Добрый день.",
        "Добрый день.",
    ]
    # Transcript timing is intentionally not an input to text matching.
    sentences = [[Word(word=word,t0=0.0,t1=0.0) for word in text.split()] for text in texts]
    before = [[w.model_dump_json() for w in sentence] for sentence in sentences]
    expected = (
        RepeatCandidate(1,2,"exact_text",5),
        RepeatCandidate(3,4,"possible_restart",4),
    )
    assert find_repeat_candidates(sentences) == expected
    assert find_repeat_candidates(sentences) == expected
    assert [[w.model_dump_json() for w in sentence] for sentence in sentences] == before


def test_longform_completed_prefix_is_not_a_restart():
    from autoreels.cloud.repeat_candidates import find_repeat_candidates

    texts = ["Мы сегодня обсуждаем внутреннюю силу.",
             "Мы сегодня обсуждаем внутреннюю силу человека.",
             "Мы сегодня не обсуждаем внутреннюю силу."]
    sentences = [[Word(word=word,t0=0.0,t1=0.0) for word in text.split()] for text in texts]
    assert find_repeat_candidates(sentences) == ()


def test_whole_source_preserves_edges_and_only_confirmed_interior_cuts():
    from autoreels.orchestr.longform_review import build_review
    from autoreels.orchestr.whole_source import propose_whole_source
    texts=("Начало.","Дубль.","Продолжаем.","Повтор.","Мысль.","Конец.")
    words=[Word(word=text,t0=i+1.0,t1=i+1.9) for i,text in enumerate(texts)]
    sentences=[[w] for w in words]
    smap={"words":[{"idx":i,"t0":w.t0,"t1":w.t1,
                    "audible_start":w.t0+0.2,"audible_end":w.t0+0.8}
                   for i,w in enumerate(words)],"boundaries":[]}
    review=build_review(sentences,8000)
    args=dict(words=words,smap=smap,source_duration_ms=8000,review_sha256=review.review_sha256)
    uncut=propose_whole_source(sentences,confirmed=(),**args)
    assert uncut.reel.playback_duration()==8.0
    assert len(uncut.reel.segments)==1
    cut=propose_whole_source(sentences,confirmed=(2,4),**args)
    assert cut==propose_whole_source(sentences,confirmed=(2,4),**args)
    assert cut.reel.start==0 and cut.reel.end==8
    assert len(cut.reel.segments)==3
    assert cut.reel.playback_duration()<8
    assert [w.word for w in cut.reel.subtitles]==[texts[i] for i in (0,2,4,5)]
    for i,w in enumerate(words,1):
        a,b=w.t0+0.2,w.t0+0.8
        played=sum(max(0,min(s.end,b)-max(s.start,a)) for s in cut.reel.segments)
        assert played==pytest.approx(0 if i in (2,4) else b-a)
    for confirmed in ((1,),(6,),(2,2),(4,2),(True,)):
        with pytest.raises(edit.Unavailable):
            propose_whole_source(sentences,confirmed=confirmed,**args)
    with pytest.raises(edit.Unavailable,match="review changed"):
        propose_whole_source(sentences,confirmed=(2,),**{**args,"review_sha256":"0"*64})
    ambiguous=copy.deepcopy(smap)
    ambiguous["words"][1]["audible_end"]=3.4
    with pytest.raises(edit.Unavailable):
        propose_whole_source(sentences,confirmed=(2,),**{**args,"smap":ambiguous})
