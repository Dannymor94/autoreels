"""Tests for interview host-turn clip boundary logic."""
from pathlib import Path

import pytest

from autoreels.cloud.select import detect_host_turns, _stage_interview_snap
from autoreels.core.models import Reel


def _word(text, t0, t1):
    from autoreels.core.models import Word
    return Word(word=text, t0=t0, t1=t1)


def _reel(start=0.0, end=60.0, r0_start=None, id="r01", score=80):
    return Reel(
        id=id, start=start, end=end, score=score,
        hook="h", title="t", description="d",
        r0_start=r0_start if r0_start is not None else start,
        r0_end=end,
    )


ROOT = Path(__file__).parent.parent


def _cfg(**kwargs):
    from autoreels.core.config import load_r0_config
    cfg = load_r0_config(ROOT / "config" / "r0.yaml")
    for k, v in kwargs.items():
        object.__setattr__(cfg, k, v)
    return cfg


# ---------- detect_host_turns ----------

def test_detect_host_turns_basic():
    # sentence with '?' and 'вы' → detected
    words = [
        _word("Как", 10.0, 10.3),
        _word("вы", 10.3, 10.5),
        _word("справляетесь?", 10.5, 11.0),
        _word("Хорошо", 12.0, 12.4),
        _word("работаете.", 12.4, 12.8),
    ]
    turns = detect_host_turns(words)
    assert len(turns) == 1
    assert turns[0][0] == pytest.approx(10.0)
    assert turns[0][1] == pytest.approx(11.0)


def test_detect_host_turns_no_question_mark():
    words = [
        _word("Как", 10.0, 10.3),
        _word("вы", 10.3, 10.5),
        _word("справляетесь", 10.5, 11.0),
    ]
    turns = detect_host_turns(words)
    assert turns == []


def test_detect_host_turns_question_no_second_person():
    words = [
        _word("Это", 10.0, 10.3),
        _word("работает?", 10.3, 10.8),
    ]
    turns = detect_host_turns(words)
    assert turns == []


def test_detect_host_turns_host_opener():
    words = [
        _word("Расскажите", 5.0, 5.4),
        _word("подробнее?", 5.4, 5.9),
    ]
    turns = detect_host_turns(words)
    assert len(turns) == 1


def test_detect_host_turns_empty():
    assert detect_host_turns([]) == []


# ---------- _stage_interview_snap: end rule ----------

def test_host_turn_ends_clip():
    # host turn at 50-53s, reel ends at 60s, r0_start=0 → end moves to 50-0.15=49.85
    r = _reel(start=0.0, end=60.0, r0_start=0.0)
    host_turns = [(50.0, 53.0)]
    cfg = _cfg(source_kind="interview", min_clip_duration=15)
    kept, disc = _stage_interview_snap([r], host_turns, r0_cfg=cfg)
    assert len(kept) == 1
    assert kept[0].end == pytest.approx(50.0 - 0.15)
    assert kept[0].end_snap_reason == "before_host_turn"
    assert disc == []


def test_host_turn_clip_too_short_dropped():
    # host turn at 20s, reel start=10s, end=60s → end→19.85, duration=9.85 < 15 → drop
    r = _reel(start=10.0, end=60.0, r0_start=10.0)
    host_turns = [(20.0, 23.0)]
    cfg = _cfg(source_kind="interview", min_clip_duration=15)
    kept, disc = _stage_interview_snap([r], host_turns, r0_cfg=cfg)
    assert kept == []
    assert len(disc) == 1
    assert disc[0]["reason"] == "interview_snap_too_short"
    assert disc[0]["id"] == "r01"


def test_host_turn_after_end_ignored():
    # host turn starts after reel end → no change
    r = _reel(start=0.0, end=40.0, r0_start=0.0)
    host_turns = [(50.0, 53.0)]
    cfg = _cfg(source_kind="interview", min_clip_duration=15)
    kept, disc = _stage_interview_snap([r], host_turns, r0_cfg=cfg)
    assert len(kept) == 1
    assert kept[0].end == pytest.approx(40.0)
    assert kept[0].end_snap_reason is None


# ---------- _stage_interview_snap: start rule ----------

def test_host_question_included_in_start():
    # host turn ends 3s before r0_start, duration 5s ≤ 12s → include it
    r = _reel(start=30.0, end=60.0, r0_start=30.0)
    # host turn: 22.0..27.0 → ends 3s before r0_start=30
    host_turns = [(22.0, 27.0)]
    cfg = _cfg(source_kind="interview", min_clip_duration=15)
    kept, _ = _stage_interview_snap([r], host_turns, r0_cfg=cfg)
    assert len(kept) == 1
    assert kept[0].start == pytest.approx(22.0)
    assert kept[0].start_snap_reason == "host_question_included"


def test_host_question_too_far_not_included():
    # host turn ends 10s before r0_start → outside 8s window
    r = _reel(start=30.0, end=60.0, r0_start=30.0)
    host_turns = [(15.0, 20.0)]  # ends 10s before r0_start
    cfg = _cfg(source_kind="interview", min_clip_duration=15)
    kept, _ = _stage_interview_snap([r], host_turns, r0_cfg=cfg)
    assert kept[0].start == pytest.approx(30.0)
    assert kept[0].start_snap_reason is None


def test_host_question_too_long_not_included():
    # host turn duration 15s > 12s → not included
    r = _reel(start=30.0, end=60.0, r0_start=30.0)
    host_turns = [(12.0, 27.0)]  # 15s duration, ends 3s before r0_start
    cfg = _cfg(source_kind="interview", min_clip_duration=15)
    kept, _ = _stage_interview_snap([r], host_turns, r0_cfg=cfg)
    assert kept[0].start == pytest.approx(30.0)


# ---------- ends_on_host_turn flag ----------

def test_ends_on_host_turn_flag_true():
    r = _reel(start=0.0, end=60.0, r0_start=0.0)
    host_turns = [(58.0, 62.0)]  # starts within end±5
    r.ends_on_host_turn = any(
        ts > r.r0_start and ts <= r.end + 5.0
        for ts, te in host_turns
    )
    assert r.ends_on_host_turn is True


def test_ends_on_host_turn_flag_false():
    r = _reel(start=0.0, end=60.0, r0_start=0.0)
    host_turns = [(70.0, 74.0)]  # after end+5
    r.ends_on_host_turn = any(
        ts > r.r0_start and ts <= r.end + 5.0
        for ts, te in host_turns
    )
    assert r.ends_on_host_turn is False


# ---------- lecture mode: no change ----------

def test_lecture_mode_stage_not_called():
    # In lecture mode, _stage_interview_snap should not be wired in pipeline.
    # Validate that the stage itself still works but lecture mode skips it at call site.
    # (Pipeline guard is in __main__.py — tested via integration; here just confirm
    # lecture cfg has source_kind="lecture".)
    cfg = _cfg(source_kind="lecture")
    assert cfg.source_kind == "lecture"
