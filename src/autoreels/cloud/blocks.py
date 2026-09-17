"""Candidate block segmentation (M1.6 stage 1).

Groups compressed-transcript lines into deterministic candidate blocks.
No LLM involvement: code finds the boundaries, LLM only scores blocks in a later stage.

Boundary priority (highest → lowest):
  pause        gap between consecutive lines > min_pause_for_phrase_end
  paragraph    line text contains \\n (Whisper paragraph marker, future-proof)
  speaker_turn next line starts with em/en dash — reuses _DASH_CHARS from select.py
  sentence     previous line ends with terminal punctuation (.?!…)

Sizing:
  - blocks longer than max_sec are split recursively at the longest internal pause
  - blocks shorter than min_sec merge forward; dropped if merging would exceed max_sec
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

from autoreels.cloud.select import _DASH_CHARS   # reuse speaker-change marker set

_SENTENCE_END = frozenset("?!")
_SENTENCE_END_WORD_SUFFIXES = (".", "?", "!", "…")
_TRAILING = "»\"')]"

_LINE_RE = re.compile(r"^\[(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\] (.+)$")


class _Line(NamedTuple):
    t0: float
    t1: float
    text: str


@dataclass
class CandidateBlock:
    """One candidate block ready for LLM scoring."""
    id: str                  # sha256[:16] of normalised text — stable cache key
    start: float
    end: float
    duration: float          # end - start
    text: str
    boundary_reason: str     # "pause" | "paragraph" | "speaker_turn" | "sentence"
    lines: list[_Line] = field(default_factory=list, repr=False)
    has_internal_speaker_change: bool = False  # set by filter_blocks; stage 3 treats as strong negative
    heuristic_score: float = 0.0              # set by score_block (M1.6 stage 3)
    score_breakdown: dict = field(default_factory=dict, repr=False)  # per-feature contributions


# --------------------------------------------------------------------------- parsing

def _parse_lines(compressed: str) -> list[_Line]:
    out: list[_Line] = []
    for ln in compressed.splitlines():
        m = _LINE_RE.match(ln.strip())
        if m:
            out.append(_Line(float(m.group(1)), float(m.group(2)), m.group(3)))
    return out


def _block_id(text: str) -> str:
    """Stable content-based id: sha256 of normalised (lower, collapsed whitespace) text."""
    normalised = " ".join(text.lower().split())
    return hashlib.sha256(normalised.encode()).hexdigest()[:16]


def _ends_terminal(text: str) -> bool:
    stripped = text.rstrip(_TRAILING)
    return bool(stripped) and stripped[-1] in (".", "?", "!", "…")


# --------------------------------------------------------------------------- boundary detection

def _boundary_reason(prev: _Line, curr: _Line, min_pause: float) -> str | None:
    """Return the highest-priority boundary reason between prev and curr, or None."""
    gap = curr.t0 - prev.t1
    if gap > min_pause:
        return "pause"
    if "\n" in prev.text:
        return "paragraph"
    if curr.text.lstrip().startswith(_DASH_CHARS):
        return "speaker_turn"
    if _ends_terminal(prev.text):
        return "sentence"
    return None


# --------------------------------------------------------------------------- grouping

def _group_into_raw_blocks(lines: list[_Line], min_pause: float) -> list[tuple[list[_Line], str]]:
    """Walk lines left-to-right, opening a new group at each boundary signal.

    Returns list of (lines, boundary_reason) pairs.
    The first group uses "sentence" as a nominal reason (no preceding boundary).
    """
    if not lines:
        return []
    groups: list[tuple[list[_Line], str]] = []
    current: list[_Line] = [lines[0]]
    current_reason = "sentence"
    for i in range(1, len(lines)):
        reason = _boundary_reason(lines[i - 1], lines[i], min_pause)
        if reason is not None:
            groups.append((current, current_reason))
            current = [lines[i]]
            current_reason = reason
        else:
            current.append(lines[i])
    groups.append((current, current_reason))
    return groups


# --------------------------------------------------------------------------- sizing

def _split_at_longest_pause(lines: list[_Line]) -> tuple[list[_Line], list[_Line]]:
    """Split lines at the position with the largest gap; ties broken toward the midpoint."""
    mid = len(lines) / 2.0
    best_k, best_gap = 1, -1.0
    for k in range(1, len(lines)):
        gap = lines[k].t0 - lines[k - 1].t1
        if gap > best_gap or (
            abs(gap - best_gap) < 1e-9 and abs(k - mid) < abs(best_k - mid)
        ):
            best_gap, best_k = gap, k
    return lines[:best_k], lines[best_k:]


def _split_recursive(
    lines: list[_Line], reason: str, max_sec: float
) -> list[tuple[list[_Line], str]]:
    """Recursively split lines that exceed max_sec at the longest internal pause."""
    if not lines:
        return []
    dur = lines[-1].t1 - lines[0].t0
    if dur <= max_sec or len(lines) <= 1:
        return [(lines, reason)]
    left, right = _split_at_longest_pause(lines)
    return (
        _split_recursive(left, reason, max_sec)
        + _split_recursive(right, "pause", max_sec)
    )


def _merge_short(
    groups: list[tuple[list[_Line], str]], min_sec: float, max_sec: float
) -> list[tuple[list[_Line], str]]:
    """Merge forward any block shorter than min_sec.

    Merged block inherits the reason of the FIRST (short) block, since that is the
    boundary that opened it. If merging would exceed max_sec, the short block is dropped.
    Iterates until stable (handles cascaded short blocks).
    """
    remaining = list(groups)
    result: list[tuple[list[_Line], str]] = []
    while remaining:
        lines, reason = remaining.pop(0)
        dur = lines[-1].t1 - lines[0].t0
        if dur >= min_sec:
            result.append((lines, reason))
            continue
        # Short block: try to merge with next
        if remaining:
            next_lines, _next_reason = remaining[0]
            combined = lines + next_lines
            combined_dur = combined[-1].t1 - combined[0].t0
            if combined_dur <= max_sec:
                remaining[0] = (combined, reason)   # re-evaluate combined next turn
                continue
        # No next block or would exceed max_sec → drop
    return result


# --------------------------------------------------------------------------- public API

def _make_block(lines: list[_Line], reason: str) -> CandidateBlock:
    text = " ".join(ln.text for ln in lines)
    start, end = lines[0].t0, lines[-1].t1
    return CandidateBlock(
        id=_block_id(text),
        start=start,
        end=end,
        duration=end - start,
        text=text,
        boundary_reason=reason,
        lines=list(lines),
    )


_PRICE_RE = re.compile(r"\d[\d\s]*рубл", re.IGNORECASE)
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_SENT_END_RE = re.compile(r"(?<=[.!?…])\s+")


def _has_signoff_at_sentence_start(text: str, phrases: Sequence[str]) -> bool:
    """True if any phrase opens a sentence (block start or after punctuation)."""
    if not phrases:
        return False
    text_lower = text.lstrip("—– \t").lower()
    sentences = _SENT_END_RE.split(text_lower)
    for sent in sentences:
        sent_stripped = sent.lstrip("—– \t")
        for phrase in phrases:
            if sent_stripped.startswith(phrase.lower()):
                return True
    return False


def _filter_reason(
    block: CandidateBlock,
    total_duration: float,
    head_skip_sec: float,
    tail_skip_sec: float,
    speech_density_min: float,
    repetition_unique_ratio_min: float,
    artefact_markers: Sequence[str],
    promo_keywords: Sequence[str],
    signoff_phrases: Sequence[str] = (),
) -> str | None:
    """Return a drop reason string, or None if the block should be kept."""
    text_lower = block.text.lower()

    if any(m.lower() in text_lower for m in artefact_markers):
        return "artefact"

    if any(kw.lower() in text_lower for kw in promo_keywords) or _PRICE_RE.search(block.text):
        return "promo"

    if _has_signoff_at_sentence_start(block.text, signoff_phrases):
        return "signoff"

    mid = (block.start + block.end) / 2
    if mid < head_skip_sec:
        return "head"
    if mid > total_duration - tail_skip_sec:
        return "tail"

    speech_time = sum(ln.t1 - ln.t0 for ln in block.lines)
    if block.duration > 0 and speech_time / block.duration < speech_density_min:
        return "low_density"

    words = _WORD_RE.findall(text_lower)
    if words and len(set(words)) / len(words) < repetition_unique_ratio_min:
        return "repetition"

    return None


def _detect_internal_speaker_change(block: CandidateBlock, host_affirmations: Sequence[str]) -> bool:
    """True if a non-first line starts with a dash or a host-affirmation word.

    Pass an empty host_affirmations to disable entirely (use for lecture material).
    """
    if not host_affirmations or len(block.lines) < 2:
        return False
    aff_lower = {a.lower() for a in host_affirmations}
    for ln in block.lines[1:]:
        txt = ln.text.lstrip()
        if txt.startswith(_DASH_CHARS):
            return True
        m = _WORD_RE.match(txt)
        if m and m.group().lower() in aff_lower:
            return True
    return False


def filter_blocks(
    blocks: list[CandidateBlock],
    *,
    total_duration: float,
    head_skip_sec: float = 30.0,
    tail_skip_sec: float = 30.0,
    speech_density_min: float = 0.4,
    repetition_unique_ratio_min: float = 0.3,
    artefact_markers: Sequence[str] = (),
    promo_keywords: Sequence[str] = (),
    signoff_phrases: Sequence[str] = (),
    host_affirmations: Sequence[str] = (),
) -> tuple[list[CandidateBlock], list[tuple[CandidateBlock, str]]]:
    """Apply deterministic pre-filters (M1.6 stage 2).

    Returns (kept, dropped) where dropped is a list of (block, reason) pairs.
    Kept blocks have has_internal_speaker_change set if an internal turn was detected.
    Priority: artefact → promo → signoff → head → tail → low_density → repetition.
    """
    kept: list[CandidateBlock] = []
    dropped: list[tuple[CandidateBlock, str]] = []
    for block in blocks:
        reason = _filter_reason(
            block, total_duration,
            head_skip_sec, tail_skip_sec,
            speech_density_min, repetition_unique_ratio_min,
            artefact_markers, promo_keywords,
            signoff_phrases,
        )
        if reason is not None:
            dropped.append((block, reason))
        else:
            block.has_internal_speaker_change = _detect_internal_speaker_change(
                block, host_affirmations
            )
            kept.append(block)
    return kept, dropped


def candidate_blocks(
    compressed: str,
    *,
    min_sec: float,
    max_sec: float,
    min_pause_for_phrase_end: float,
) -> list[CandidateBlock]:
    """Segment compressed transcript into candidate blocks ready for LLM scoring.

    Args:
        compressed: output of compress_transcript()
        min_sec: minimum block duration in seconds (from r0_cfg.min_meaningful_sec)
        max_sec: maximum block duration in seconds (from r0_cfg.max_duration)
        min_pause_for_phrase_end: pause threshold to open a boundary (from r0.yaml)

    Returns:
        List of CandidateBlock, each with duration in [min_sec, max_sec].
        Empty list when the input is empty or all blocks are dropped during sizing.
    """
    lines = _parse_lines(compressed)
    if not lines:
        return []
    raw = _group_into_raw_blocks(lines, min_pause_for_phrase_end)
    # Split oversized, then merge undersized
    expanded: list[tuple[list[_Line], str]] = []
    for lns, reason in raw:
        expanded.extend(_split_recursive(lns, reason, max_sec))
    sized = _merge_short(expanded, min_sec, max_sec)
    return [_make_block(lns, reason) for lns, reason in sized]


# --------------------------------------------------------------------------- stage 3: heuristic scoring

def _duration_sweet_score(duration: float, min_sec: float, sweet_min: float, sweet_max: float) -> float:
    """0.0-1.0 bell curve: ramp up from min_sec to sweet_min, flat peak, fall off symmetrically."""
    if duration <= min_sec:
        return 0.0
    if duration <= sweet_min:
        return (duration - min_sec) / (sweet_min - min_sec)
    if duration <= sweet_max:
        return 1.0
    falloff_end = sweet_max + (sweet_max - sweet_min)
    return max(0.0, 1.0 - (duration - sweet_max) / (sweet_max - sweet_min))


def score_block(block: "CandidateBlock", cfg: "BlockScoringConfig") -> tuple[float, dict]:
    """Compute heuristic score (0-100) and per-feature breakdown for one block.

    Returns (score, breakdown) where breakdown maps feature name → raw points contributed.
    Positive entries add to score, negative subtract. Clamped to [0, 100].
    """
    from autoreels.core.config import BlockScoringConfig as _BSC  # local to avoid top-level cycle
    text = block.text
    text_lower = text.lower()

    # -- positive features --
    dur_raw = _duration_sweet_score(block.duration, cfg.min_sec, cfg.sweet_spot_min, cfg.sweet_spot_max)
    dur_pts = cfg.w_duration * dur_raw

    ends_sent = 1.0 if _ends_terminal(text.rstrip()) else 0.0
    ends_pts = cfg.w_ends_sentence * ends_sent

    bad_set = {w.lower() for w in cfg.bad_open_words}
    first_word = _WORD_RE.match(text_lower.lstrip("—– \t"))
    opens_clean = 0.0 if (first_word and first_word.group() in bad_set) else 1.0
    opens_pts = cfg.w_opens_sentence * opens_clean

    has_q = 1.0 if "?" in text else 0.0
    q_pts = cfg.w_question * has_q

    has_contr = 1.0 if any(m.lower() in text_lower for m in cfg.contrarian_markers) else 0.0
    contr_pts = cfg.w_contrarian * has_contr

    words = _WORD_RE.findall(text_lower)
    lexical = len(set(words)) / len(words) if words else 0.0
    lex_pts = cfg.w_lexical * lexical

    # -- negative features --
    # Dangling reference: 3rd-person pronoun/demonstrative density in first sentence > 25%.
    # Uses cfg.dangling_pronouns (pronouns only) — NOT bad_open_words (which includes conjunctions
    # that appear normally mid-sentence and would inflate the count spuriously).
    first_sent_end = next((i for i, c in enumerate(text) if c in ".?!…"), -1)
    first_sent = text_lower[:first_sent_end] if first_sent_end > 0 else text_lower
    fs_words = _WORD_RE.findall(first_sent)
    dangle_set = {w.lower() for w in cfg.dangling_pronouns}
    dangling_count = sum(1 for w in fs_words if w in dangle_set)
    dangling = 1.0 if fs_words and dangling_count / len(fs_words) > 0.25 else 0.0
    dangle_pts = cfg.w_dangling * dangling

    sc_pts = cfg.w_speaker_change * (1.0 if block.has_internal_speaker_change else 0.0)

    speech_time = sum(ln.t1 - ln.t0 for ln in block.lines)
    density = speech_time / block.duration if block.duration > 0 else 0.0
    # penytail: only near-silence is abnormal; dense speech (>0.95) is the norm for this material
    dens_pen = 1.0 if density < 0.5 else 0.0
    dens_pts = cfg.w_density_penalty * dens_pen

    max_positive = cfg.w_duration + cfg.w_ends_sentence + cfg.w_opens_sentence + cfg.w_question + cfg.w_contrarian + cfg.w_lexical
    raw = dur_pts + ends_pts + opens_pts + q_pts + contr_pts + lex_pts - dangle_pts - sc_pts - dens_pts
    score = max(0.0, min(100.0, raw / max_positive * 100.0))

    breakdown = {
        "duration": round(dur_pts, 2),
        "ends_sentence": ends_pts,
        "opens_sentence": opens_pts,
        "question": q_pts,
        "contrarian": contr_pts,
        "lexical": round(lex_pts, 2),
        "dangling_ref": -round(dangle_pts, 2),
        "speaker_change": -sc_pts,
        "density_penalty": -dens_pts,
    }
    return score, breakdown


def topk_filter(
    blocks: list[CandidateBlock],
    *,
    chunk_window_sec: float,
    top_k: int,
) -> tuple[list[CandidateBlock], list[CandidateBlock]]:
    """Keep top_k highest-scoring blocks per time window; return (kept, cut).

    Blocks must have heuristic_score set before calling.
    Kept list is sorted by start time; cut list preserves input order.
    """
    if not blocks or top_k <= 0:
        return list(blocks), []

    from collections import defaultdict
    windows: dict[int, list[CandidateBlock]] = defaultdict(list)
    for b in blocks:
        windows[int(b.start / chunk_window_sec)].append(b)

    kept: list[CandidateBlock] = []
    cut: list[CandidateBlock] = []
    for blks in windows.values():
        ranked = sorted(blks, key=lambda b: b.heuristic_score, reverse=True)
        kept.extend(ranked[:top_k])
        cut.extend(ranked[top_k:])

    kept.sort(key=lambda b: b.start)
    return kept, cut
