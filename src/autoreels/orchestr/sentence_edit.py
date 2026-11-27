"""Read-only first sentence-removal proposal through the existing manual planner.

Trusted fixture inputs only. No raw Whisper-gap cutting, file writes, API,
migration or replacement of a manually edited plan. Complex montage/FX,
hooks and partial-word selections are intentionally outside this first slice.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from autoreels.cloud.plan import ManualPlan, ManualPlanParams, build_manual_plan
from autoreels.core.models import Reel, Word


class Unavailable(ValueError):
    """The edit cannot be safely represented by the supported dry-plan slice."""


@dataclass(frozen=True)
class Proposal:
    kept_sentences: tuple[int, ...]
    removed_sentences: tuple[int, ...]
    plan: ManualPlan


def _segments(plan: ManualPlan):
    return [segment for window in plan.body for segment in window.segments()]


def remove_sentences(
    base: Reel,
    *,
    sentences: Sequence[Sequence[Word]],
    words: Sequence[Word],
    smap: dict,
    play: tuple[int, ...],
    selected: tuple[int, ...],
    params: ManualPlanParams,
    source_duration: float,
) -> Proposal:
    """Preview removal of a contiguous range in a simple existing body plan.

    The caller must supply a frozen exact source/transcript/speech-map and
    configuration revision. This function checks reproduced baseline, not
    storage provenance; it neither commits a revision nor accepts media.
    """
    if (not base.planned or base.cold_open is not None or base.reordered
            or base.beat_gap_sec is not None or base.montage or base.fx
            or base.c_close_ranges or base.subtitle_emph_words or base.speed != 1.0
            or params.filler_cut or params.filler_word_cut or params.subs_hide_fillers
            or params.start_preroll_sec or params.max_static_sec or params.emphasis_keys):
        raise Unavailable("complex plan requires the full manual-edit contract")
    if (not play or any(type(n) is not int or not 1 <= n <= len(sentences) for n in play)
            or tuple(sorted(set(play))) != play):
        raise Unavailable("ambiguous body sentence order")
    if (not selected or any(type(n) is not int or n not in play for n in selected)
            or len(selected) >= len(play)):
        raise Unavailable("select a nonempty proper subset of the body")
    start = play.index(selected[0])
    if play[start:start+len(selected)] != selected:
        raise Unavailable("select one contiguous range")
    if not math.isfinite(source_duration) or source_duration <= 0:
        raise Unavailable("source duration required")

    # This first slice refuses incomplete or ambiguous audio evidence rather
    # than falling back to Whisper times. Caller is responsible for binding
    # these inputs to the exact source/transcript revision.
    try:
        by_key = {}
        for record in smap["words"]:
            key = round(float(record["t0"]) * 1000)
            a, b = float(record["audible_start"]), float(record["audible_end"])
            if key in by_key or not (math.isfinite(a) and math.isfinite(b)
                                    and 0 <= a < b <= source_duration):
                raise Unavailable("ambiguous speech map")
            by_key[key] = (a,b)
        tx = {}
        for word in words:
            if not (math.isfinite(word.t0) and math.isfinite(word.t1)):
                raise Unavailable("invalid transcript time")
            key = round(word.t0*1000)
            if key in tx or key not in by_key:
                raise Unavailable("missing or ambiguous speech map")
            tx[key] = word
        used = set()
        for sentence in sentences:
            if not sentence:
                raise Unavailable("empty sentence")
            for word in sentence:
                key = round(word.t0*1000)
                if key in used or tx.get(key) != word:
                    raise Unavailable("ambiguous sentence mapping")
                used.add(key)
    except (KeyError, TypeError, OverflowError) as exc:
        raise Unavailable("invalid speech evidence") from exc

    def build(order):
        plan = build_manual_plan(sentences, order, words=words, smap=smap,
                                 params=params, source_duration=source_duration)
        if plan.errors or plan.cold_open is not None:
            raise Unavailable("manual planner refused the requested body")
        if tuple(n for window in plan.body for n in window.sentences) != order:
            raise Unavailable("manual planner changed sentence selection")
        return plan

    baseline = build(play)
    # Do not silently overwrite accepted windows/subtitles with a different
    # planner result. Only the exact reproducible body slice is supported.
    if (base.start != baseline.start or base.end != baseline.end
            or base.effective_segments() != _segments(baseline)
            or base.subtitles != baseline.subtitles
            or base.tail_last_word_end != baseline.last_audible_end
            or base.tail_next_word_start != baseline.next_onset):
        raise Unavailable("existing body cannot be reproduced")

    kept = tuple(n for n in play if n not in selected)
    proposal = build(kept)
    # Existing manual planner may deliberately play through an overlapping
    # Whisper duplicate. Never report that such a selected phrase was cut.
    removed = [by_key[round(w.t0*1000)] for n in selected for w in sentences[n-1]]
    for seg in _segments(proposal):
        if any(min(seg.end,b)-max(seg.start,a)>1e-6 for a,b in removed):
            raise Unavailable("selected speech is still present in proposed playback")
    expected_text = [w.word for n in kept for w in sentences[n-1]]
    if [w.word for w in proposal.subtitles] != expected_text:
        raise Unavailable("proposed subtitles do not match selected sentences")
    return Proposal(kept, selected, proposal)
