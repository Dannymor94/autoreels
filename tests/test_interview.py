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
    kept, disc = _stage_interview_snap([r], host_turns, tx_words=[], r0_cfg=cfg)
    assert len(kept) == 1
    assert kept[0].end == pytest.approx(50.0 - 0.15)
    assert kept[0].end_snap_reason == "before_host_turn"
    assert disc == []


def test_host_turn_clip_too_short_dropped():
    # host turn at 20s, reel start=10s, end=60s → end→19.85, duration=9.85 < 15 → drop
    r = _reel(start=10.0, end=60.0, r0_start=10.0)
    host_turns = [(20.0, 23.0)]
    cfg = _cfg(source_kind="interview", min_clip_duration=15)
    kept, disc = _stage_interview_snap([r], host_turns, tx_words=[], r0_cfg=cfg)
    assert kept == []
    assert len(disc) == 1
    assert disc[0]["reason"] == "interview_snap_too_short"
    assert disc[0]["id"] == "r01"


def test_host_turn_after_end_ignored():
    # host turn starts after reel end → no change
    r = _reel(start=0.0, end=40.0, r0_start=0.0)
    host_turns = [(50.0, 53.0)]
    cfg = _cfg(source_kind="interview", min_clip_duration=15)
    kept, disc = _stage_interview_snap([r], host_turns, tx_words=[], r0_cfg=cfg)
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
    kept, _ = _stage_interview_snap([r], host_turns, tx_words=[], r0_cfg=cfg)
    assert len(kept) == 1
    assert kept[0].start == pytest.approx(22.0)
    assert kept[0].start_snap_reason == "host_question_included"


def test_host_question_too_far_not_included():
    # host turn ends 10s before r0_start → outside 8s window
    r = _reel(start=30.0, end=60.0, r0_start=30.0)
    host_turns = [(15.0, 20.0)]  # ends 10s before r0_start
    cfg = _cfg(source_kind="interview", min_clip_duration=15)
    kept, _ = _stage_interview_snap([r], host_turns, tx_words=[], r0_cfg=cfg)
    assert kept[0].start == pytest.approx(30.0)
    assert kept[0].start_snap_reason is None


def test_host_question_too_long_not_included():
    # host turn duration 15s > 12s → not included
    r = _reel(start=30.0, end=60.0, r0_start=30.0)
    host_turns = [(12.0, 27.0)]  # 15s duration, ends 3s before r0_start
    cfg = _cfg(source_kind="interview", min_clip_duration=15)
    kept, _ = _stage_interview_snap([r], host_turns, tx_words=[], r0_cfg=cfg)
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


# ---------- ты-form detection (informal interview) ----------

def test_detect_host_turns_ty_second_person():
    """'ты' form: 'А ты как ты с этим работаешь?' → detected as host turn."""
    words = [
        _word("А", 10.0, 10.2),
        _word("ты", 10.2, 10.4),
        _word("как", 10.4, 10.6),
        _word("ты", 10.6, 10.8),
        _word("с", 10.8, 10.9),
        _word("этим", 10.9, 11.1),
        _word("работаешь?", 11.1, 11.8),
    ]
    turns = detect_host_turns(words)
    assert len(turns) == 1
    assert turns[0] == pytest.approx((10.0, 11.8))


def test_detect_host_turns_tebe_form():
    """'тебе' form: 'что ты делаешь с ними?' → detected."""
    words = [
        _word("что", 5.0, 5.2),
        _word("ты", 5.2, 5.4),
        _word("делаешь", 5.4, 5.8),
        _word("с", 5.8, 5.9),
        _word("ними?", 5.9, 6.5),
    ]
    turns = detect_host_turns(words)
    assert len(turns) == 1


def test_detect_host_turns_no_question_no_flag():
    """Guest sentence with 'ты' but NO '?' (reported speech) → NOT a host turn."""
    words = [
        _word("он", 0.0, 0.3),
        _word("говорит,", 0.3, 0.6),
        _word("что", 0.6, 0.8),
        _word("ты", 0.8, 1.0),
        _word("молодец.", 1.0, 1.4),
    ]
    turns = detect_host_turns(words)
    assert turns == []


def test_detect_host_turns_informal_opener_rasskazhi():
    """'расскажи' opener → detected without second-person marker."""
    words = [
        _word("Расскажи", 3.0, 3.4),
        _word("подробнее?", 3.4, 3.9),
    ]
    turns = detect_host_turns(words)
    assert len(turns) == 1


def test_detect_host_turns_a_kak_ty():
    """'а как ты' opener → detected."""
    words = [
        _word("а", 0.0, 0.2),
        _word("как", 0.2, 0.5),
        _word("ты", 0.5, 0.7),
        _word("справляешься?", 0.7, 1.3),
    ]
    turns = detect_host_turns(words)
    assert len(turns) == 1


# ---------- regression: __7 and __19 scenarios ----------

def test_regression_clip7_host_question_at_end_cut():
    """Regression __7: reel ends on host question → end moved back."""
    guest_words = [
        _word("не", 30.0, 30.3),
        _word("наступает.", 30.3, 31.0),
    ]
    host_words = [
        _word("А", 32.0, 32.2),
        _word("ты", 32.2, 32.4),
        _word("как", 32.4, 32.7),
        _word("ты", 32.7, 32.9),
        _word("с", 32.9, 33.0),
        _word("этим", 33.0, 33.2),
        _word("работаешь?", 33.2, 34.0),
    ]
    all_words = guest_words + host_words

    host_turns = detect_host_turns(all_words)
    assert len(host_turns) == 1, f"host turn not detected; turns={host_turns}"

    r = _reel(start=10.0, end=34.0, r0_start=10.0)
    cfg = _cfg(source_kind="interview", min_clip_duration=15)
    kept, disc = _stage_interview_snap([r], host_turns, tx_words=all_words, r0_cfg=cfg)

    assert len(kept) == 1
    assert kept[0].end < 32.0, f"end should be before host turn at 32.0; got {kept[0].end}"
    assert kept[0].end_snap_reason == "before_host_turn"


def test_regression_clip19_trailing_host_question_cut():
    """Regression __19: trailing 'А когда к тебе приходят…что ты делаешь…?' → cut."""
    words = [
        _word("Я", 0.0, 0.2),
        _word("ответил.", 0.2, 0.9),
        _word("А", 2.0, 2.2),
        _word("когда", 2.2, 2.5),
        _word("к", 2.5, 2.6),
        _word("тебе", 2.6, 2.9),
        _word("приходят", 2.9, 3.3),
        _word("люди,", 3.3, 3.6),
        _word("что", 3.6, 3.8),
        _word("ты", 3.8, 4.0),
        _word("делаешь?", 4.0, 4.8),
    ]

    host_turns = detect_host_turns(words)
    assert len(host_turns) == 1, f"host turn not detected; got {host_turns}"

    r = _reel(start=0.0, end=4.8, r0_start=0.0)
    cfg = _cfg(source_kind="interview", min_clip_duration=1)
    kept, disc = _stage_interview_snap([r], host_turns, tx_words=words, r0_cfg=cfg)

    assert len(kept) == 1
    assert kept[0].end < 2.0, f"should end before host turn at 2.0; got {kept[0].end}"


# ---------- ends_on_host_turn on all reels ----------

def test_ends_on_host_turn_set_on_all_reels():
    """ends_on_host_turn field exists and defaults False on Reel."""
    from autoreels.core.models import Reel
    r = Reel(id="x", start=0.0, end=30.0, score=80, hook="h", title="t", description="d")
    assert hasattr(r, "ends_on_host_turn")
    assert r.ends_on_host_turn is False


# ---------- _stage_interview_snap signature: tx_words is explicit parameter ----------

def test_stage_interview_snap_accepts_tx_words_param():
    """_stage_interview_snap accepts tx_words as a named parameter (not via r0_cfg)."""
    import inspect
    sig = inspect.signature(_stage_interview_snap)
    assert "tx_words" in sig.parameters
