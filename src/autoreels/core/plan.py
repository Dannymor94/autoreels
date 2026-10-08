"""RenderPlan: shot and timing plan for a manual-path reel (REEL_SPEC §1–§4).

Pure data — no ffmpeg, no side effects.  The plan drives both the CLI preview
and the renderer for selection_source=human clips.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from autoreels.core.config import RenderConfig
    from autoreels.core.models import Reel

_TERM = ".?!…"
_LEAKED_TERM_WINDOW = 0.5  # seconds: max word-duration for a leaked excluded sentence


def _is_terminal(word) -> bool:
    tok = word.word.rstrip("»\"')]")
    return bool(tok) and tok[-1] in _TERM


def _is_x_seam_boundary(prev, nxt, words: list) -> bool:
    """True iff the gap prev→nxt is an x: exclusion (window boundary), not filler removal.

    Non-zero gap: x: cut leaves at least one terminal word in the gap.
    Zero gap: x: cut leaks its excluded sentence's terminal last word into prev's span
      (_refine_seams moves prev.end past that word); filler cuts leave no terminal nearby.
    """
    if nxt.start > prev.end + 1e-5:
        return any(
            _is_terminal(w) for w in words
            if prev.end - 0.001 < w.t0 < nxt.start
        )
    # Zero-gap path
    return any(
        _is_terminal(w) for w in words
        if prev.end - _LEAKED_TERM_WINDOW <= w.t0 < prev.end + 1e-4
    )


def _pop_leaked_sentence(seg_sents: list, seg, next_seg, words: list) -> None:
    """Remove the last sentence from seg_sents if it is a leaked excluded sentence.

    _refine_seams shifts the segment boundary past the excluded sentence's last word,
    so that word (and possibly the whole one-word sentence) appears in words_in_span.
    Non-zero gap: leaked word's t0 falls in the gap range.
    Zero-gap: leaked word's t0 falls within _LEAKED_TERM_WINDOW of seg.end.
    """
    if not seg_sents:
        return
    last_word = seg_sents[-1][-1]
    if next_seg.start > seg.end + 1e-5:
        if seg.end - 0.001 < last_word.t0 < next_seg.start:
            seg_sents.pop()
    else:
        # Zero-gap: leaked word has t0 near seg.end AND t1 ≤ seg.end
        # (a legitimate word extends past seg.end into the next segment's audio).
        if (last_word.t0 >= seg.end - _LEAKED_TERM_WINDOW
                and last_word.t1 <= seg.end + 0.1):
            seg_sents.pop()


class ShotSpan(NamedTuple):
    shot: str                     # "wide" | "close"
    sentence_indices: list[int]   # 1-indexed within plan.sentences
    reason: str                   # "start" | "cold-open seam" | "x: seam" | "cold open" | "c:"


class BodyWindow(NamedTuple):
    source_start: float
    source_end: float
    sentence_indices: list[int]   # 1-indexed within plan.sentences


class RenderPlan(NamedTuple):
    """Complete shot + timing plan for one manual-path reel.

    Sentence indices are 1-based positions into `sentences`; sentences are the
    remaining (non-excluded) body sentences in source-time order.  The cold-open
    sentence appears in both cold_open_sentence_idx and in the last body window
    when replayed_in_body is True.
    """
    sentences: list[list]               # remaining sentences (lists of Word), 1-indexed
    body_windows: list[BodyWindow]
    cold_open_source: tuple[float, float] | None   # (start, end) in source time
    cold_open_sentence_idx: int | None             # 1-indexed in sentences, or None
    replayed_in_body: bool
    shots: list[ShotSpan]               # in output order (cold_open first if present)
    clip_end: float                     # source time where clip ends
    fade_start: float                   # source time where fade begins
    fade_sec: float                     # fade length in seconds


def build_manual_plan(reel: "Reel", words: list, smap: "dict | None",
                      cfg: "RenderConfig") -> RenderPlan:
    """Build the render plan for a manual-path reel (REEL_SPEC §1–§4).

    Parameters
    ----------
    reel   : Reel object from the manifest (selection_source=human, after --apply).
    words  : full transcript word list (Word objects with .t0 / .t1 / .word).
    smap   : speechmap dict (or None — falls back to reel.end / reel.end-fade_sec).
    cfg    : RenderConfig (needs cfg.audio_processing.end_air_sec / end_video_fade_sec).
    """
    from autoreels.cloud.edit import split_sentences, words_in_span

    ap = cfg.audio_processing
    end_air_sec: float = getattr(ap, "end_air_sec", 0.30)
    fade_sec: float = getattr(ap, "end_video_fade_sec", 0.25)

    # --- 1. Group segments into body windows ---
    # x: seam (terminal word in gap, or zero-gap with leaked terminal) → new window.
    # Filler-removal gaps (non-terminal words, or zero-gap without leaked terminal) → same window.
    segs = reel.effective_segments()
    seg_groups: list[list] = []
    if segs:
        seg_groups = [[segs[0]]]
        for seg in segs[1:]:
            prev = seg_groups[-1][-1]
            if _is_x_seam_boundary(prev, seg, words):
                seg_groups.append([seg])
            else:
                seg_groups[-1].append(seg)

    # --- 2. Remaining sentences and body windows ---
    remaining: list[list] = []
    body_windows: list[BodyWindow] = []
    for grp_idx, grp in enumerate(seg_groups):
        win_start = grp[0].start
        win_end = grp[-1].end
        grp_sents: list[list] = []
        has_next_group = grp_idx < len(seg_groups) - 1
        for seg_idx, seg in enumerate(grp):
            seg_sents = [
                s for s in split_sentences(words_in_span(words, seg.start, seg.end))
                if _is_terminal(s[-1])
            ]
            # _refine_seams leaks the excluded sentence's last terminal word into this
            # segment's span — remove that leaked sentence before counting.
            if seg_idx == len(grp) - 1 and has_next_group:
                _pop_leaked_sentence(seg_sents, seg, seg_groups[grp_idx + 1][0], words)
            grp_sents.extend(seg_sents)
        start_1 = len(remaining) + 1
        remaining.extend(grp_sents)
        end_1 = len(remaining)
        if start_1 <= end_1:
            body_windows.append(BodyWindow(win_start, win_end,
                                           list(range(start_1, end_1 + 1))))

    # --- 3. Cold-open sentence index and replay ---
    cold_open_sentence_idx: int | None = None
    replayed_in_body = False
    if reel.cold_open is not None:
        co_start = reel.cold_open.start
        co_end = reel.cold_open.end
        for i, sent in enumerate(remaining, 1):
            if co_start - 0.02 <= sent[0].t0 < co_end:
                cold_open_sentence_idx = i
                for bw in body_windows:
                    if i in bw.sentence_indices:
                        replayed_in_body = True
                        break
                break

    # --- 4. Close-shot (c:) sentence indices ---
    # A sentence is c: when reel.c_close_ranges has a range whose start falls
    # inside [sent[0].t0 - epsilon, sent[-1].t1 - epsilon) — tight at end to avoid
    # false positives from Whisper timestamp bleeding.
    c_idxs: set[int] = set()
    for rng in (reel.c_close_ranges or []):
        rng_start = rng[0]
        for i, sent in enumerate(remaining, 1):
            if sent[0].t0 - 0.02 <= rng_start < sent[-1].t1 - 0.01:
                c_idxs.add(i)
                break

    # --- 5. Shot spans (REEL_SPEC §3) ---
    shots: list[ShotSpan] = []

    if reel.cold_open is not None and cold_open_sentence_idx is not None:
        shots.append(ShotSpan("close", [cold_open_sentence_idx], "cold open"))

    last_shot = "close" if reel.cold_open else None

    for wi, bw in enumerate(body_windows):
        if wi == 0:
            seam_reason = "cold-open seam" if reel.cold_open else "start"
            base_shot = "wide"
        else:
            base_shot = "close" if last_shot == "wide" else "wide"
            seam_reason = "x: seam"

        # If the window's first sentence is c: and base is already the same shot,
        # the stated reason is "c:" (not the seam reason).
        first_is_c = bool(bw.sentence_indices and bw.sentence_indices[0] in c_idxs)
        initial_reason = "c:" if first_is_c else seam_reason

        current_shot = base_shot
        current_run: list[int] = []
        current_reason = initial_reason

        for sent_idx in bw.sentence_indices:
            is_c = sent_idx in c_idxs

            if is_c and current_shot != "close":
                # c: forces a shot change → flush current span
                if current_run:
                    shots.append(ShotSpan(current_shot, current_run, current_reason))
                current_shot = "close"
                current_run = []
                current_reason = "c:"
            elif not is_c and current_reason == "c:":
                # Returning from c: to base shot
                if current_run:
                    shots.append(ShotSpan(current_shot, current_run, current_reason))
                current_shot = base_shot
                current_run = []
                current_reason = seam_reason

            current_run.append(sent_idx)

        if current_run:
            shots.append(ShotSpan(current_shot, current_run, current_reason))

        last_shot = current_shot

    # --- 6. Clip end and fade (REEL_SPEC §4) ---
    clip_end = reel.end
    fade_start = max(clip_end - fade_sec, reel.end - fade_sec)

    last_sub = reel.subtitles[-1] if reel.subtitles else None
    if last_sub is not None and smap:
        from autoreels.local.render import _smap_word_lookup, _tail_from_smap_full
        lookup = _smap_word_lookup(smap)
        tail = _tail_from_smap_full(
            last_sub.t0, reel.end, smap, lookup,
            last_t1=last_sub.t1,
            tail_pad_sec=end_air_sec,
            onset_margin_sec=0.06,
            fade_keep_sec=0.0,
            tail_fade_sec=fade_sec,
            fps=30.0,
        )
        if tail is not None:
            clip_end = tail.end
            fade_start = tail.fade_start
            fade_sec = tail.fade_len

    return RenderPlan(
        sentences=remaining,
        body_windows=body_windows,
        cold_open_source=(reel.cold_open.start, reel.cold_open.end) if reel.cold_open else None,
        cold_open_sentence_idx=cold_open_sentence_idx,
        replayed_in_body=replayed_in_body,
        shots=shots,
        clip_end=clip_end,
        fade_start=fade_start,
        fade_sec=fade_sec,
    )
