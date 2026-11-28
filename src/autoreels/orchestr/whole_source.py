"""Read-only, whole-source plan for explicitly confirmed interior removals.

Use the existing audio-aware manual planner for seam boundaries. Preserve
source opening/ending and all unselected speech. No LLM, media reads or writes,
automatic repeat selection, or implicit production/export activation.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from itertools import groupby
from typing import Sequence

from autoreels.cloud.plan import ManualPlanParams, build_manual_plan
from autoreels.core.models import Reel, Segment, Word
from .longform_review import build_review
from .sentence_edit import Unavailable, _speech_evidence


@dataclass(frozen=True)
class WholeSourceProposal:
    review_sha256: str
    removed_sentences: tuple[int, ...]
    reel: Reel


def propose_whole_source(
    sentences: Sequence[Sequence[Word]], *, words: Sequence[Word],
    smap: dict, source_duration_ms: int, review_sha256: str,
    confirmed: tuple[int, ...],
) -> WholeSourceProposal:
    """A trusted caller binds transcript/map to the same source revision.

    Only interior sentence removals in a chronological transcript are enabled.
    Source edges are retained, even when they contain silence. Exact zero
    removals retain the entire source. All selected sound must disappear and
    all retained sound must remain; ambiguous audio evidence is refused.
    """
    review = build_review(sentences,source_duration_ms)
    if review.review_sha256 != review_sha256:
        raise Unavailable("whole-source review changed")
    n = len(sentences)
    if (not n or any(type(i) is not int or not 1<i<n for i in confirmed)
            or tuple(sorted(set(confirmed))) != confirmed):
        raise Unavailable("select distinct interior sentences only")
    duration = source_duration_ms/1000
    evidence = _speech_evidence(sentences,words,smap,duration)
    flattened = [w for sentence in sentences for w in sentence]
    if list(words) != flattened or set(evidence) != {round(w.t0*1000) for w in flattened}:
        raise Unavailable("whole-source transcript evidence incomplete")
    removed = set(confirmed)
    kept = tuple(i for i in range(1,n+1) if i not in removed)
    plan = build_manual_plan(sentences,kept,words=words,smap=smap,
                             params=ManualPlanParams(),source_duration=duration)
    expected_runs = [tuple(i for _,i in run) for _,run in
                     groupby(enumerate(kept),key=lambda p:p[1]-p[0])]
    if (plan.errors or plan.cold_open is not None
            or [tuple(w.sentences) for w in plan.body] != expected_runs
            or any(w.cuts or w.prerolled for w in plan.body)):
        raise Unavailable("whole-source planner cannot represent confirmed cuts")
    segments = [Segment(start=w.start,end=w.end) for w in plan.body]
    segments[0] = segments[0].model_copy(update={"start":0.0})
    segments[-1] = segments[-1].model_copy(update={"end":duration})
    if any(not 0<=s.start<s.end<=duration for s in segments) or any(
        left.end>=right.start for left,right in zip(segments,segments[1:])
    ):
        raise Unavailable("whole-source cut intervals overlap or have no gap")
    ends = [s.end for s in segments]
    for i,sentence in enumerate(sentences,1):
        for word in sentence:
            a,b = evidence[round(word.t0*1000)]
            k = bisect_right(ends,a)
            if i in removed:
                if k<len(segments) and segments[k].start<b-1e-6:
                    raise Unavailable("selected speech is still present")
            elif k==len(segments) or segments[k].start>a+1e-6 or segments[k].end<b-1e-6:
                raise Unavailable("retained speech would be cut")
    if [w.word for w in plan.subtitles] != [w.word for i in kept for w in sentences[i-1]]:
        raise Unavailable("whole-source subtitle mismatch")
    reel = Reel(id="r01",start=0.0,end=duration,score=0,hook="",
                title="Whole source",description="Confirmed interior cuts",
                planned=True,segments=segments,subtitles=plan.subtitles,
                tail_last_word_end=plan.last_audible_end,tail_next_word_start=plan.next_onset)
    reel.check_segments()
    return WholeSourceProposal(review_sha256,confirmed,Reel.model_validate_json(reel.model_dump_json()))
