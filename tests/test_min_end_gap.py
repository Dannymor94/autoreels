"""_stage_min_end_gap: soft minimum-gap guard for clip endings.

1. End gap < floor → extends to next sentence with adequate gap.
2. End gap >= floor → untouched.
3. _explicit_end=True → never moved regardless of gap.
4. No qualifying pause within window → keeps current end, prints warning.
"""
import sys
import pytest

from autoreels.core.models import Reel, Transcript, Word


def _w(t0: float, t1: float, word: str = "x") -> Word:
    return Word(word=word, t0=t0, t1=t1)


def _reel(start: float, end: float, rid: str = "r01") -> Reel:
    return Reel(id=rid, start=start, end=end, score=80,
                hook="h", title="t", description="d", reason="r", topic="x")


def _transcript(words: list[Word]) -> Transcript:
    return Transcript(language="ru", words=words)


def _cfg(**kwargs):
    """Minimal stand-in for r0_cfg with only the fields _stage_min_end_gap reads."""
    class Cfg:
        min_end_gap_sec = kwargs.get("min_end_gap_sec", 0.15)
        target_end_gap_sec = kwargs.get("target_end_gap_sec", 0.30)
        end_gap_search_sec = kwargs.get("end_gap_search_sec", 20.0)
    return Cfg()


# Import the function under test.
from autoreels.__main__ import _stage_min_end_gap


# ── Test 1: small gap → extends to next adequate-gap sentence end ──────────
def test_small_gap_extends_to_next_paused_sentence():
    # Clip ends on "конец." followed 0.05s later by "и" (tiny gap).
    # Further ahead: "стоп." with a 0.50s gap after it.
    words = [
        _w(0.0, 0.4, "начало"),
        _w(0.5, 1.0, "конец."),    # ← clip ends here; gap to next word = 0.05s
        _w(1.05, 1.4, "и"),        # next word; tiny gap
        _w(1.5, 2.0, "потом"),
        _w(2.1, 2.6, "стоп."),     # sentence end; gap after = 0.50s → qualifies
        _w(3.10, 3.5, "дальше"),
    ]
    reel = _reel(0.0, 1.1)         # ends just after "конец."
    tx = _transcript(words)
    _stage_min_end_gap([reel], tx, r0_cfg=_cfg())
    # Should extend to "стоп." t1 = 2.6
    assert abs(reel.end - 2.6) < 1e-6, f"expected 2.6, got {reel.end}"
    assert reel.end_snap_reason == "min_end_gap"


# ── Test 2: adequate gap → untouched ──────────────────────────────────────
def test_adequate_gap_leaves_reel_untouched():
    words = [
        _w(0.0, 0.5, "слово"),
        _w(0.6, 1.0, "конец."),
        _w(1.60, 2.0, "дальше"),   # gap = 0.60s ≥ min_end_gap=0.15 → fine
    ]
    reel = _reel(0.0, 1.1)
    original_end = reel.end
    original_reason = reel.end_snap_reason
    tx = _transcript(words)
    _stage_min_end_gap([reel], tx, r0_cfg=_cfg())
    assert reel.end == original_end
    assert reel.end_snap_reason == original_reason


# ── Test 3: explicit_end flag suppresses the rule ─────────────────────────
def test_explicit_end_never_moved(capsys):
    words = [
        _w(0.0, 0.5, "слово"),
        _w(0.6, 1.0, "конец."),
        _w(1.03, 1.4, "сразу"),    # gap = 0.03s < min_end_gap
        _w(1.5, 2.0, "пауза."),
        _w(2.60, 3.0, "потом"),    # gap after "пауза." = 0.60s → would qualify
    ]
    reel = _reel(0.0, 1.1)
    reel._explicit_end = True
    original_end = reel.end
    tx = _transcript(words)
    _stage_min_end_gap([reel], tx, r0_cfg=_cfg())
    assert reel.end == original_end   # must not move


# ── Test 4: no qualifying pause within window → warn, keep end ────────────
def test_no_qualifying_pause_warns_keeps_end(capsys):
    words = [
        _w(0.0, 0.5, "слово"),
        _w(0.6, 1.0, "конец."),
        _w(1.03, 1.4, "сразу"),    # gap = 0.03s < min_end_gap
        _w(1.5, 2.0, "потом."),    # sentence end but gap after = 0.20s < target 0.30
        _w(2.20, 2.6, "ещё"),
        # nothing within 20s search window has gap ≥ 0.30
    ]
    reel = _reel(0.0, 1.1)
    original_end = reel.end
    tx = _transcript(words)
    _stage_min_end_gap([reel], tx, r0_cfg=_cfg())
    assert reel.end == original_end   # kept
    captured = capsys.readouterr()
    assert "no pause" in captured.err.lower() or "no pause" in captured.out.lower()
