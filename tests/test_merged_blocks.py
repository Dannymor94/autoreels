"""Merged-block invariants.

A human '+' merge is an explicit instruction:
1. One reel spanning both blocks, never two.
2. Snap adjusts outer edges only; no internal cut.
3. A merged reel exceeding max_duration is reported, not silently trimmed.
4. Human-merged reels survive apply_top_n regardless of score or max_reels.
"""
from types import SimpleNamespace

import pytest

from autoreels.core.models import Reel, Word


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _word(t0: float, t1: float, word: str = "слово") -> Word:
    return Word(t0=t0, t1=t1, word=word)


def _reel(start: float, end: float, score: int = 50, flags=None, *, merged=False) -> Reel:
    r = Reel(
        id=f"r_{start}_{end}",
        start=start,
        end=end,
        score=score,
        hook="hook",
        title="",
        description="",
    )
    r.r0_start = start
    r.r0_end = end
    if merged:
        r.flags.append("human_merged")
    if flags:
        r.flags.extend(flags)
    return r


def _host_turn(t0: float, t1: float):
    return (t0, t1)


# ---------------------------------------------------------------------------
# 1. Merged pair produces exactly ONE reel spanning both blocks
# ---------------------------------------------------------------------------

def test_merged_pair_interview_snap_skipped(monkeypatch):
    """Interview snap must not cut a human-merged reel even if a host turn sits inside it."""
    from autoreels.cloud.select import _stage_interview_snap

    # Merged reel spans [10, 50]. A host turn at [30, 35] is inside the span.
    r = _reel(10.0, 50.0, merged=True)
    host_turns = [_host_turn(30.0, 35.0)]

    cfg = SimpleNamespace(min_clip_duration=8.0, host_affirmations=[])
    kept, disc = _stage_interview_snap([r], host_turns, tx_words=[], r0_cfg=cfg)

    assert len(kept) == 1
    assert len(disc) == 0
    assert kept[0].end == 50.0, "end must not be moved before internal host turn"


def test_non_merged_reel_still_snapped_by_interview(monkeypatch):
    """Sanity: non-merged reels are still subject to interview snap."""
    from autoreels.cloud.select import _stage_interview_snap

    r = _reel(10.0, 50.0, merged=False)
    host_turns = [_host_turn(30.0, 35.0)]

    cfg = SimpleNamespace(min_clip_duration=8.0, host_affirmations=[])
    kept, disc = _stage_interview_snap([r], host_turns, tx_words=[], r0_cfg=cfg)

    # end is moved to 30.0 - 0.15 = 29.85
    assert len(kept) == 1
    assert kept[0].end == pytest.approx(30.0 - 0.15, abs=0.01)


# ---------------------------------------------------------------------------
# 2. Snap adjusts only outer edges; no internal cut for merged reel
# ---------------------------------------------------------------------------

def test_snap_does_not_cut_merged_reel_end_before_span(monkeypatch):
    """snap_segments must not move a merged reel's end inside the first block's range.

    We test this by giving a transcript that has a phrase-end only at the
    boundary between the two merged blocks (the "internal" boundary). snap
    should find the end at or after r0_end, never retreat into block-1 territory.
    """
    from autoreels.cloud.snap import snap_segments

    # Merged reel: block1=[10,30], block2=[31,50]. r0_end = 50.
    r = _reel(10.0, 50.0, merged=True)

    # Transcript words spanning the range. A pause at t=30 (boundary between blocks).
    words = [
        _word(10.0, 11.0, "слово."),   # sentence-end inside block1
        _word(11.5, 12.5, "ещё"),
        _word(29.0, 30.0, "конец."),   # sentence-end at block1 boundary
        _word(31.0, 32.0, "начало."),  # block2 start
        _word(48.0, 49.0, "финал."),   # near r0_end
        _word(50.5, 51.0, "после"),
    ]

    snap_segments(
        [r], words,
        tail_sec=0.3, window_sec=1.5,
        max_duration=90.0,
        min_pause_for_phrase_end=0.4,
        max_micro_pause=0.15,
        hanging_words=[],
        max_end_search_sec=12.0,
        min_clip_duration=8.0,
    )

    # End must not be moved below block2.start (31s) — no internal cut.
    assert r.end >= 31.0, f"snap moved end inside first block: {r.end}"


# ---------------------------------------------------------------------------
# 3. Merged reel exceeding max_duration is reported, not silently trimmed
# ---------------------------------------------------------------------------

def test_merged_reel_exceeding_max_duration_is_reported(capsys):
    """trim_too_long must warn and keep a human_merged reel with too_long flag."""
    from autoreels.cloud.trim import trim_too_long

    r = _reel(0.0, 100.0, merged=True, flags=["too_long"])
    words = [_word(0.0, 1.0, "слово.")]

    trim_too_long([r], words, max_duration=90.0, pause_sec=0.35, policy="trim")

    # Reel must survive (not removed, not trimmed).
    assert r.end == 100.0, "merged reel must not be trimmed"
    assert "too_long" not in r.flags, "too_long flag should be cleared after reporting"
    # Warning goes to stderr.
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower() or "merged" in captured.err.lower()


def test_normal_reel_too_long_still_trimmed():
    """Non-merged too_long reels continue to be trimmed normally."""
    from autoreels.cloud.trim import trim_too_long

    words = [
        _word(0.0, 1.0, "начало"),
        _word(50.0, 51.0, "середина."),   # sentence-end in range
        _word(95.0, 96.0, "конец."),
    ]
    r = _reel(0.0, 100.0, flags=["too_long"])

    trim_too_long([r], words, max_duration=90.0, pause_sec=0.35, policy="trim")

    assert r.end < 100.0 or r.start > 0.0, "non-merged reel should be trimmed"


# ---------------------------------------------------------------------------
# 4. Human-merged reels unaffected by top-N or heuristic filters
# ---------------------------------------------------------------------------

def test_human_merged_reels_survive_top_n():
    """Merged reels survive apply_top_n even when their score would lose to other clips."""
    from autoreels.cloud.select import apply_top_n

    # 3 merged reels with low scores + 5 non-merged reels with high scores.
    merged = [_reel(i * 10.0, i * 10.0 + 9.0, score=10, merged=True) for i in range(3)]
    others = [_reel(100.0 + i * 10.0, 109.0 + i * 10.0, score=90) for i in range(5)]

    kept, cut = apply_top_n(merged + others, max_reels=5, transcript_words=None)

    # All 3 merged reels must be in kept, regardless of score.
    kept_ids = {r.id for r in kept}
    for r in merged:
        assert r.id in kept_ids, f"merged reel {r.id} was dropped by top-N"


def test_human_merged_reels_unaffected_by_min_clip_filter():
    """_stage_min_clip_filter must keep merged reels even if they are below min_dur."""
    from autoreels import __main__ as cli
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    # A merged reel shorter than min_clip_duration (can happen if snap shrinks it).
    r = _reel(0.0, 5.0, merged=True)   # 5s < 8s min_dur
    transcript = MagicMock()
    transcript.words = []
    r0_cfg = SimpleNamespace(min_clip_duration=8.0, max_duration=90.0,
                             min_pause_for_phrase_end=0.4, max_micro_pause=0.15,
                             hanging_words=SimpleNamespace(enabled=False))

    kept, disc = cli._stage_min_clip_filter([r], transcript, r0_cfg=r0_cfg)

    assert len(kept) == 1
    assert len(disc) == 0


def test_human_merged_reels_unaffected_by_meaningful_sec_recheck():
    """_stage_meaningful_sec_recheck must not drop merged reels below the floor."""
    from autoreels import __main__ as cli
    from unittest.mock import MagicMock

    r = _reel(0.0, 12.0, merged=True)   # 12s < 18s floor
    transcript = MagicMock()
    transcript.words = []
    r0_cfg = SimpleNamespace(
        min_meaningful_sec=18.0, min_duration=8.0, max_duration=90.0,
    )

    kept, disc = cli._stage_meaningful_sec_recheck([r], transcript, r0_cfg=r0_cfg)

    assert len(kept) == 1
    assert len(disc) == 0
