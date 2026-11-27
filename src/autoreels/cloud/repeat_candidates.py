"""Conservative, read-only text candidates for whole-video take review.

These are suggestions, not classifications of bad takes or instructions to
remove speech. The caller must bind the numbered sentences to its exact
transcript revision. Actual cut boundaries belong to the audio-aware planner.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal, Sequence

from autoreels.core.models import Word


_TOKEN = re.compile(r"[^\W_]+(?:[-’'][^\W_]+)*", re.UNICODE)
_MIN_TOKENS = 4
_MAX_SENTENCE_DISTANCE = 2


@dataclass(frozen=True, slots=True)
class RepeatCandidate:
    """One pair of 1-based sentence references, in source transcript order."""

    earlier: int
    later: int
    kind: Literal["exact_text", "possible_restart"]
    matched_tokens: int


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(_TOKEN.findall(unicodedata.normalize("NFC", text).casefold()))


def _unfinished(text: str) -> bool:
    # Punctuation is a text hint only. It is not speech/prosody evidence.
    text = text.rstrip().rstrip('»"\')]}').rstrip()
    return bool(text) and (text.endswith("...") or not text.endswith((".", "!", "?")))


def find_repeat_candidates(sentences: Sequence[Sequence[Word]]) -> tuple[RepeatCandidate, ...]:
    """Compare only nearby sentence units; never mutate text, timing or plan.

    The first conservative slice uses exact normalized token equality and
    incomplete-prefix evidence. No fuzzy semantic judgment, timing inference,
    provider call, or automatic choice of which occurrence to keep.
    """
    texts = [" ".join(w.word for w in sentence) for sentence in sentences]
    tokens = [_tokens(text) for text in texts]
    out: list[RepeatCandidate] = []
    for later, right in enumerate(tokens):
        if len(right) < _MIN_TOKENS:
            continue
        for earlier in range(max(0, later - _MAX_SENTENCE_DISTANCE), later):
            left = tokens[earlier]
            if len(left) < _MIN_TOKENS:
                continue
            if left == right:
                out.append(RepeatCandidate(earlier + 1, later + 1, "exact_text", len(left)))
            elif len(left) < len(right) and right[:len(left)] == left and _unfinished(texts[earlier]):
                out.append(RepeatCandidate(earlier + 1, later + 1, "possible_restart", len(left)))
    return tuple(out)
