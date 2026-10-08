"""Single definition of 'jump seam' for the entire pipeline.

A jump seam is a cut between non-consecutive source sentences: an x: exclusion,
a cold-open/body boundary, a filler cut, or a beat jump to a non-adjacent source
position.  Used by assign_shots, the render-time shot check, and verify_gate.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autoreels.core.models import Segment, Word

_DEFAULT_GAP_SEC = 2.0  # fallback only — callers should pass jump_seam_gap_sec from config


def is_jump_seam(
    prev_window: "Segment",
    next_window: "Segment",
    sentences: "list[Word] | None" = None,
    *,
    cold_open: bool = False,
    jump_seam_gap_sec: float = _DEFAULT_GAP_SEC,
) -> bool:
    """Return True when the boundary between prev_window and next_window is a jump seam.

    Priority (first match wins):
    1. cold_open=True: structural cold-open→body boundary — always True.
    2. Backward: next_window.start < prev_window.end → always True (source reversal).
    3. sentences provided: True if any word starts strictly between prev_window.end and
       next_window.start — at least one sentence was skipped (x: cut, filler removal…).
    4. Fallback: gap > jump_seam_gap_sec (from config; no literal in production code).
    """
    if cold_open:
        return True
    if next_window.start < prev_window.end - 0.001:
        return True
    if sentences:
        return any(prev_window.end - 0.001 < w.t0 < next_window.start for w in sentences)
    return (next_window.start - prev_window.end) > jump_seam_gap_sec
