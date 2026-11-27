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


def _speech_evidence(
    sentences: Sequence[Sequence[Word]], words: Sequence[Word],
    smap: dict, source_duration: float,
) -> dict[int, tuple[float, float]]:
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

    return by_key


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
    by_key = _speech_evidence(sentences, words, smap, source_duration)

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


def reorder_sentences(
    base: Reel,
    *,
    sentences: Sequence[Sequence[Word]],
    words: Sequence[Word],
    smap: dict,
    play: tuple[int, ...],
    order: tuple[int, ...],
    params: ManualPlanParams,
    source_duration: float,
) -> Reel:
    """Read-only permutation of an exactly reproducible simple body.

    Uses the existing audio planner and Reel.reordered contract. Source
    evidence must be frozen by the caller. No persistence or media access.
    """
    if (not base.planned or base.cold_open is not None
            or base.beat_gap_sec is not None or base.montage or base.fx
            or base.c_close_ranges or base.subtitle_emph_words or base.speed != 1.0
            or base.zoom_source_t0 is not None or base.head_first_word_start is not None
            or base.subtitle_gate is not None or base.marks
            or params.filler_cut or params.filler_word_cut or params.subs_hide_fillers
            or params.start_preroll_sec or params.max_static_sec or params.emphasis_keys):
        raise Unavailable("complex plan requires the full manual-edit contract")
    if (not play or any(type(n) is not int or not 1 <= n <= len(sentences) for n in play)
            or len(set(play)) != len(play)
            or any(type(n) is not int for n in order)
            or len(order) != len(play) or set(order) != set(play)):
        raise Unavailable("order must be a permutation of the current body")
    if base.reordered != (tuple(sorted(play)) != play):
        raise Unavailable("existing reorder flag does not match body")
    by_key = _speech_evidence(sentences, words, smap, source_duration)

    def build(sequence: tuple[int, ...]) -> ManualPlan:
        plan = build_manual_plan(sentences, sequence, words=words, smap=smap,
                                 params=params, source_duration=source_duration)
        if plan.errors or plan.cold_open is not None:
            raise Unavailable("manual planner refused the requested body")
        if tuple(n for window in plan.body for n in window.sentences) != sequence:
            raise Unavailable("manual planner changed sentence selection")
        return plan

    baseline = build(play)
    if (base.start != baseline.start or base.end != baseline.end
            or base.effective_segments() != _segments(baseline)
            or base.subtitles != baseline.subtitles
            or base.tail_last_word_end != baseline.last_audible_end
            or base.tail_next_word_start != baseline.next_onset):
        raise Unavailable("existing body cannot be reproduced")

    proposal = build(order)
    segments = _segments(proposal)
    expected = [round(w.t0 * 1000) for n in order for w in sentences[n - 1]]
    # Inspect audible spans, not just planner sentence labels: refuse any
    # foreign speech, partial word, duplicated word or unexpected play order.
    # A visual shot change is allowed to split an audible span, so measure
    # coverage across adjacent source segments in playback order.
    actual: list[int] = []
    coverage: dict[int, float] = {}
    for seg in segments:
        if not (math.isfinite(seg.start) and math.isfinite(seg.end)
                and 0 <= seg.start < seg.end <= source_duration):
            raise Unavailable("invalid proposed segment")
        overlaps = sorted((max(seg.start, a), key, min(seg.end, b) - max(seg.start, a))
                          for key, (a, b) in by_key.items()
                          if min(seg.end, b) - max(seg.start, a) > 1e-6)
        for _, key, length in overlaps:
            coverage[key] = coverage.get(key, 0.0) + length
            if not actual or actual[-1] != key:
                actual.append(key)
    if actual != expected or any(
        abs(coverage.get(key, 0.0) - (by_key[key][1] - by_key[key][0])) > 1e-6
        for key in expected
    ):
        raise Unavailable("proposed playback does not preserve exact speech order")
    if [w.word for w in proposal.subtitles] != [
        w.word for n in order for w in sentences[n - 1]
    ]:
        raise Unavailable("proposed subtitles do not match playback")
    reel = base.model_copy(update={
        "start": proposal.start, "end": proposal.end, "segments": segments,
        "subtitles": proposal.subtitles, "tail_last_word_end": proposal.last_audible_end,
        "tail_next_word_start": proposal.next_onset,
        "reordered": tuple(sorted(order)) != order,
    })
    reel.check_segments()
    return Reel.model_validate_json(reel.model_dump_json())


# Fixed synthetic slice: leave a conservative 50 ms source-time margin
# around speech when moving a boundary inward. A later renderer-specific
# contract can derive a margin from its actual frame/sample grid.
_TRIM_SPEECH_MARGIN = 0.05


def trim_silence(
    base: Reel,
    *,
    sentences: Sequence[Sequence[Word]],
    words: Sequence[Word],
    smap: dict,
    play: tuple[int, ...],
    segment_index: int,
    start: float,
    end: float,
    params: ManualPlanParams,
    source_duration: float,
) -> Reel:
    """Preview one inward trim of an exactly reproducible simple body.

    Index is in playback order, times are source seconds. No speech deletion,
    extrapolation, persistence, arbitrary effect edits or second planner.
    The caller binds the exact source, transcript and speech map.
    """
    # Reuse the existing planner's exact baseline and audible coverage
    # verification, including nonchronological bodies and previous cuts.
    reorder_sentences(base, sentences=sentences, words=words, smap=smap,
                      play=play, order=play, params=params,
                      source_duration=source_duration)
    segments = base.effective_segments()
    if type(segment_index) is not int or not 0 <= segment_index < len(segments):
        raise Unavailable("invalid segment index")
    if (type(start) not in (int, float) or type(end) not in (int, float)
            or not math.isfinite(start) or not math.isfinite(end)):
        raise Unavailable("invalid trim bounds")
    old = segments[segment_index]
    if not old.start <= start < end <= old.end or (start == old.start and end == old.end):
        raise Unavailable("trim must shorten one existing window")
    if old.close_intervals or old.window_cut or old.prerolled:
        raise Unavailable("complex window requires the full manual-edit contract")
    evidence = _speech_evidence(sentences, words, smap, source_duration)
    retained = []
    for a, b in evidence.values():
        if min(old.end, b) - max(old.start, a) <= 1e-6:
            continue
        if not old.start <= a < b <= old.end:
            raise Unavailable("speech spans a window boundary")
        retained.append((a, b))
        if (start > old.start and start > a - _TRIM_SPEECH_MARGIN + 1e-6
                or end < old.end and end < b + _TRIM_SPEECH_MARGIN - 1e-6):
            raise Unavailable("trim would enter speech guard")
    if not retained:
        raise Unavailable("window has no verified speech")

    # The planner stores subtitle timestamps in source time; preserve all
    # tokens and their output order. Only cues in the shortened window can
    # require clamping. Refuse ambiguous window ownership.
    subtitles = []
    for word in base.subtitles:
        owners = [i for i, seg in enumerate(segments) if seg.start <= word.t0 < seg.end]
        if len(owners) != 1:
            raise Unavailable("ambiguous subtitle window")
        if owners[0] == segment_index:
            margin = min(_TRIM_SPEECH_MARGIN, (end - start) / 2)
            t0 = min(max(word.t0, start + margin), end - margin)
            t1 = min(max(word.t1, t0), end)
            word = word.model_copy(update={"t0": t0, "t1": t1})
        subtitles.append(word)
    segments[segment_index] = old.model_copy(update={"start": start, "end": end})
    reel = base.model_copy(update={
        "start": segments[0].start, "end": segments[-1].end,
        "segments": segments, "subtitles": subtitles,
    })
    reel.check_segments()
    return Reel.model_validate_json(reel.model_dump_json())
