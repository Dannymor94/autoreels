"""Part 3: cold open no longer replays in the body by default (h:N removes it; h:N! keeps it),
and the permanent 'source range played twice' check."""
from autoreels.core.models import Reel, Segment, Word, make_cold_open_segment
from autoreels.cloud.blocks import _parse_fields
from autoreels.__main__ import _check_source_range_replayed


def _reel(**kw):
    base = dict(id="r01", start=10.0, end=30.0, score=80, hook="h", title="t", description="d")
    base.update(kw)
    return Reel(**base)


# one word onset every 0.5s across the whole span (incl. the cold-open region before the body)
_WORDS = [Word(word=f"w{i}", t0=t / 2.0, t1=t / 2.0 + 0.3) for i, t in enumerate(range(4, 62))]


# ── h:N / h:N! parsing ───────────────────────────────────────────────────────────

def test_parse_hook_default_no_keep():
    s, e, hook, keep = _parse_fields("| h:3")[:4]
    assert hook == 3 and keep is False


def test_parse_hook_bang_keeps():
    s, e, hook, keep = _parse_fields("| h:3!")[:4]
    assert hook == 3 and keep is True


def test_parse_hook_bang_with_other_fields():
    s, e, hook, keep = _parse_fields("| s:2 | h:5! | x:7")[:4]
    assert hook == 5 and keep is True and s == 2


# ── _check_source_range_replayed ──────────────────────────────────────────────────

def test_replay_check_clean_no_cold_open():
    assert _check_source_range_replayed([_reel()], _WORDS) == []


def test_replay_check_cold_open_outside_body_ok():
    r = _reel(cold_open=make_cold_open_segment(5.0, 7.0))   # before the body [10,30]
    assert _check_source_range_replayed([r], _WORDS) == []


def test_replay_check_cold_open_in_body_unsanctioned_fails():
    """Hook overlaps the body (words heard in both) and no h:N! → the repeat is a bug."""
    r = _reel(cold_open=make_cold_open_segment(15.0, 17.0))  # inside body [10,30]
    r._hook_keep = False
    errs = _check_source_range_replayed([r], _WORDS)
    assert errs and "played twice" in errs[0] and "h:N" in errs[0]


def test_replay_check_cold_open_in_body_with_keep_ok():
    """h:N! sanctions the cold-open replay."""
    r = _reel(cold_open=make_cold_open_segment(15.0, 17.0))
    r._hook_keep = True
    assert _check_source_range_replayed([r], _WORDS) == []


def test_replay_check_body_segments_overlap_fails():
    """Two body windows covering the same source span — always a bug (no cold open involved)."""
    r = _reel(segments=[Segment(start=10.0, end=20.0), Segment(start=18.0, end=30.0)])
    errs = _check_source_range_replayed([r], _WORDS)
    assert errs and "two body windows" in errs[0]


def test_replay_check_boundary_bleed_tolerated():
    """A seam overlap with no word ONSET inside it (Whisper boundary bleed) must not fire."""
    # overlap [20.1, 20.15]; _WORDS onsets are on the 0.5s grid (…,20.0,20.5,…), none in (20.1,20.15)
    r = _reel(segments=[Segment(start=10.0, end=20.15), Segment(start=20.1, end=30.0)])
    assert _check_source_range_replayed([r], _WORDS) == []
