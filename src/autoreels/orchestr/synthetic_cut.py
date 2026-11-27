"""Fixed synthetic cut preview using the existing audio-aware planner.

No project files, media reads, storage, or commits. The speech map here is
generated evidence for a silent fixture, not an actual transcription.
"""
from fastapi import HTTPException
from pydantic import BaseModel

from autoreels.cloud.plan import ManualPlanParams, build_manual_plan
from autoreels.core.models import Reel, Word

from . import sentence_edit


class CutSentence(BaseModel):
    number: int
    text: str
    start: float
    end: float


class CutWindow(BaseModel):
    source_start: float
    source_end: float
    output_start: float
    output_end: float


class CutPreview(BaseModel):
    removed: list[int]
    duration: float
    windows: list[CutWindow]


class CutDemoView(BaseModel):
    enabled: bool
    source_duration: float
    sentences: list[CutSentence]
    plans: list[CutPreview]


def _projection(plan, removed):
    windows = []
    offset = 0.0
    for body in plan.body:
        for seg in body.segments():
            end = offset + seg.end - seg.start
            windows.append(CutWindow(source_start=seg.start, source_end=seg.end,
                                     output_start=offset, output_end=end))
            offset = end
    return CutPreview(removed=list(removed), duration=offset, windows=windows)


def view(enabled: bool) -> CutDemoView:
    if not enabled:
        return CutDemoView(enabled=False, source_duration=0, sentences=[], plans=[])
    duration = 3.0
    words = [Word(word=text, t0=float(i), t1=i+0.9)
             for i, text in enumerate(("Начало.", "Лишнее.", "Продолжение."))]
    sentences = [[w] for w in words]
    smap = {"words":[{"idx":i,"t0":w.t0,"t1":w.t1,"audible_start":i+0.2,
                      "audible_end":i+0.8} for i,w in enumerate(words)], "boundaries":[]}
    params = ManualPlanParams()
    order = (1,2,3)
    args = dict(sentences=sentences, words=words, smap=smap,
                params=params, source_duration=duration)
    baseline = build_manual_plan(**args, play=order)
    if baseline.errors:
        raise HTTPException(503, "synthetic cut fixture unavailable")
    base = Reel(id="r01",start=baseline.start,end=baseline.end,score=80,hook="",
                title="fixture",description="fixture",planned=True,
                segments=[s for w in baseline.body for s in w.segments()],
                subtitles=baseline.subtitles, tail_last_word_end=baseline.last_audible_end,
                tail_next_word_start=baseline.next_onset)
    plans = [_projection(baseline, ())]
    for first in order:
        for last in range(first, len(order)+1):
            selected = tuple(range(first,last+1))
            if selected == order:
                continue
            try:
                proposal = sentence_edit.remove_sentences(base, play=order, selected=selected, **args)
            except sentence_edit.Unavailable:
                continue
            plans.append(_projection(proposal.plan, selected))
    return CutDemoView(enabled=True,source_duration=duration,
        sentences=[CutSentence(number=i+1,text=w.word,start=i+0.2,end=i+0.8)
                   for i,w in enumerate(words)],plans=plans)
