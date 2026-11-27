"""Synthetic sentence permutations; no media or real project writes."""
from itertools import permutations

import pytest

from autoreels.cloud.plan import ManualPlanParams, build_manual_plan
from autoreels.core.models import Reel, Word
from autoreels.orchestrator.sentence_edit import Unavailable, reorder_sentences


def fixture(play=(1, 2, 3)):
    words = [Word(word=text, t0=float(i), t1=i + 0.9)
             for i, text in enumerate(("Начало.", "Середина.", "Конец."))]
    args = dict(sentences=[[w] for w in words], words=words,
                smap={"words": [{"idx": i, "t0": w.t0, "t1": w.t1,
                                 "audible_start": i + 0.2, "audible_end": i + 0.8}
                                for i, w in enumerate(words)], "boundaries": []},
                params=ManualPlanParams(), source_duration=3.0)
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
    base, args = fixture()
    original = base.model_dump_json()
    result = reorder_sentences(base, play=(1, 2, 3), order=order, **args)
    assert base.model_dump_json() == original
    assert [w.word for w in result.subtitles] == [args["words"][n-1].word for n in order]
    assert result.reordered == (order != (1, 2, 3))
    result.check_segments()
    assert result.playback_duration() > 0
    restored = reorder_sentences(result, play=order, order=(1, 2, 3), **args)
    assert restored.model_dump_json() == original


@pytest.mark.parametrize("order", [(1, 1, 3), (1, 2), (1, 2, 4), (True, 2, 3), ()])
def test_invalid_order(order):
    base, args = fixture()
    with pytest.raises(Unavailable):
        reorder_sentences(base, play=(1, 2, 3), order=order, **args)


def test_preserves_previous_cut():
    base, args = fixture((1, 3))
    result = reorder_sentences(base, play=(1, 3), order=(3, 1), **args)
    assert [w.word for w in result.subtitles] == ["Конец.", "Начало."]
    assert all(min(s.end, 1.8) - max(s.start, 1.2) <= 1e-6
               for s in result.effective_segments())


def test_stale_or_ambiguous_evidence_is_rejected():
    base, args = fixture()
    with pytest.raises(Unavailable):
        reorder_sentences(base.model_copy(update={"end": base.end + .1}),
                          play=(1, 2, 3), order=(3, 1, 2), **args)
    args["smap"]["words"].pop()
    with pytest.raises(Unavailable):
        reorder_sentences(base, play=(1, 2, 3), order=(3, 1, 2), **args)
