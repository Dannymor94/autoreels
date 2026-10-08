"""M1.7 step 1b gate: two_shot_auto — seam alternation + symmetric max-shot rule."""
from types import SimpleNamespace

import pytest

from autoreels.core.models import Reel, Segment, Word


def _seg(start, end, shot="wide", close_intervals=None):
    return Segment(start=start, end=end, shot=shot, close_intervals=close_intervals or [])


def _reel(segs, id="r01", subtitles=None):
    r = Reel(
        id=id, start=segs[0].start, end=segs[-1].end,
        score=80, hook="", title="", description="",
        subtitles=subtitles or [],
    )
    r.segments = list(segs)
    return r


def _cfg(**kw):
    # two_shot_max_wide_sec kept as backward-compat alias; canonical is two_shot_max_shot_sec
    d = dict(two_shot=True, two_shot_auto=True, two_shot_max_shot_sec=9.0, two_shot_min_sec=2.5,
             two_shot_min_middle_sec=4.0)
    d.update(kw)
    return SimpleNamespace(**d)


def _apply(segs, words=None, **cfg_kw):
    from autoreels.__main__ import _stage_two_shot_auto
    reel = _reel(segs)
    _stage_two_shot_auto([reel], words or [], render_cfg=_cfg(**cfg_kw))
    return reel.effective_segments()


# ── Test 1: flag off → no change ─────────────────────────────────────────────

def test_flag_off_returns_identical():
    segs = [_seg(0, 5), _seg(6, 12)]
    reel = _reel(segs)
    orig = list(reel.segments)
    from autoreels.__main__ import _stage_two_shot_auto
    _stage_two_shot_auto([reel], [], render_cfg=_cfg(two_shot_auto=False))
    assert reel.segments == orig


# ── Test 2: alternation wide→close→wide at seams ─────────────────────────────

def test_alternation_at_three_seams():
    segs = [_seg(0, 5), _seg(6, 12), _seg(13, 20)]
    out = _apply(segs)
    assert out[0].shot == "close"
    assert out[1].shot == "wide"
    assert out[2].shot == "close"


# ── Test 3: manual assignment preserved ──────────────────────────────────────

def test_manual_close_not_overridden():
    segs = [_seg(0, 5), _seg(6, 12, shot="close"), _seg(13, 20)]
    out = _apply(segs)
    assert out[1].shot == "close"
    assert out[0].shot == "close"
    assert out[2].shot == "wide"


# ── Test 4: min-length suppresses flip ───────────────────────────────────────

def test_min_length_suppresses_flip():
    segs = [_seg(0, 1.0), _seg(1.5, 10)]
    out = _apply(segs, two_shot_min_sec=2.5)
    assert out[1].shot == "close"


# ── Test 5: max-wide fires (backward-compat alias) ────────────────────────────

def test_max_wide_inserts_close_intervals_at_pause():
    words = [
        Word(word="а", t0=0.0, t1=1.0),
        Word(word="б.", t0=1.5, t1=3.0),
        Word(word="в", t0=3.5, t1=5.0),
        Word(word="г.", t0=6.0, t1=10.0),
    ]
    # Use the old alias key to verify backward compat
    cfg = SimpleNamespace(two_shot=True, two_shot_auto=True,
                          two_shot_max_wide_sec=9.0, two_shot_min_sec=2.5)
    from autoreels.__main__ import _stage_two_shot_auto
    reel = _reel([_seg(0, 12)])
    _stage_two_shot_auto([reel], words, render_cfg=cfg)
    out = reel.effective_segments()
    assert out[0].close_intervals, "max-close must trigger a close_intervals switch"
    # Single close seg → wide+ci=[[0, switch]]; switch_t = ci[0][1] (end of close portion)
    switch_t = out[0].close_intervals[0][1]
    assert 2.9 <= switch_t <= 3.6, f"switch expected near pause boundary ~3.0s, got {switch_t}"


# ── Test 6: symmetric max — close shot too long fires wide switch ─────────────

def test_symmetric_max_close_too_long():
    # close stretch = 14s > max_shot=9s; pause at t=3 in the close segment
    words = [
        Word(word="а", t0=0.0, t1=1.0),
        Word(word="б.", t0=2.0, t1=3.0),
        Word(word="в", t0=3.5, t1=5.0),
        Word(word="г.", t0=7.0, t1=8.0),
        Word(word="д", t0=8.5, t1=13.0),
    ]
    segs = [_seg(0.0, 5.0), _seg(5.5, 19.5, shot="close")]
    out = _apply(segs, words, two_shot_max_shot_sec=9.0)
    # The close segment should become wide+ci=[0, switch_rel]
    assert out[1].shot == "wide", "symmetric max must change close to wide+ci"
    ci = out[1].close_intervals
    assert ci and ci[0][0] == 0.0, "ci must start at 0 (close begins at segment start)"
    rel = ci[0][1]
    assert rel >= 2.5, f"close portion >= min_shot, got {rel:.2f}"
    assert (out[1].end - out[1].start) - rel >= 2.5, "wide tail must be >= min_shot"


# ── Test 7: no pause → warning reported, no ci inserted ──────────────────────

def test_no_pause_reported_when_no_boundary():
    # One long word with no sentence boundary → no pause found
    words = [Word(word="а", t0=0.0, t1=12.0)]
    segs = [_seg(0.0, 12.0)]
    reel = _reel(segs)
    from autoreels.__main__ import _stage_two_shot_auto
    _stage_two_shot_auto([reel], words, render_cfg=_cfg(two_shot_max_shot_sec=9.0))
    warns = getattr(reel, "_two_shot_warnings", [])
    assert any("no candidate" in w for w in warns), f"expected 'no candidate' warning, got {warns}"
    assert not reel.effective_segments()[0].close_intervals


# ── Test 8: Case B skipped when wide tail < min_middle (avoids A-B-A [ERROR]) ─

def test_no_short_spans_after_max_wide_with_filler():
    # 12s close span, 0.7s filler, close: Case B would create 3.0s tail < min_middle=4.0s,
    # so it is skipped. No A-B-A [ERROR] in Pass 4 output. Filler gap is a source artifact.
    words = [
        Word(word="а", t0=0.0, t1=2.0),
        Word(word="б.", t0=2.5, t1=4.0),
        Word(word="в", t0=4.5, t1=7.0),
        Word(word="г.", t0=8.0, t1=9.0),
        Word(word="д", t0=9.5, t1=12.0),
    ]
    segs = [_seg(0.0, 12.0), _seg(12.7, 20.0, shot="close")]
    reel = _reel(segs)
    from autoreels.__main__ import _stage_two_shot_auto, _shot_spans_output
    _stage_two_shot_auto([reel], words, render_cfg=_cfg(two_shot_max_shot_sec=9.0, two_shot_min_sec=2.5))
    warns = getattr(reel, "_two_shot_warnings", [])
    errors = [w for w in warns if "[ERROR]" in w]
    assert not errors, f"expected no [ERROR]; got: {errors}"
    result = reel.effective_segments()
    for stype, sa, se in _shot_spans_output(result):
        assert se - sa >= 2.5, f"short {stype} output span: {se-sa:.2f}s < 2.5s"


# ── Test 9: human-path stage list includes _stage_two_shot_auto ───────────────

def test_human_path_stage_list_includes_two_shot_auto():
    from autoreels import __main__ as cli
    assert "_stage_two_shot_auto" in cli._MANUAL_FORMATTING_STAGES, (
        "_stage_two_shot_auto must be in _MANUAL_FORMATTING_STAGES"
    )
    assert "_stage_two_shot_auto(" in inspect_src(), (
        "_stage_two_shot_auto must be called inside _blocks_do_apply"
    )


def inspect_src():
    import inspect
    from autoreels import __main__ as cli
    return inspect.getsource(cli._blocks_do_apply)


# ── Tests 10-12: _find_pause_boundary fallback levels ────────────────────────

def _w(word, t0, t1):
    return Word(word=word, t0=t0, t1=t1)


def test_fallback_level1_pause_ge_03():
    """Level 1: sentence boundary with real gap >= 0.3s is used."""
    from autoreels.__main__ import _find_pause_boundary
    words = [
        _w("привет", 0.0, 1.0), _w("мир.", 1.0, 2.0),
        _w("пауза", 2.4, 3.5),  # gap=0.4s >= 0.3
        _w("конец.", 3.5, 4.0),
    ]
    result = _find_pause_boundary(words, 0.0, 10.0, target=2.0, min_pause=0.3)
    assert result is not None
    boundary, level, _ = result
    assert level == "pause≥0.3s"
    assert abs(boundary - 2.0) < 0.1


def test_fallback_level2_sentence_no_gap():
    """Level 2: sentence boundary with 0-gap used when no level-1 candidate."""
    from autoreels.__main__ import _find_pause_boundary
    words = [
        _w("привет", 0.0, 1.0), _w("мир.", 1.0, 2.0),
        _w("сразу", 2.0, 3.0), _w("конец.", 3.0, 4.0),
        _w("ещё", 4.0, 6.0),
    ]
    result = _find_pause_boundary(words, 0.0, 10.0, target=2.0, min_pause=0.3)
    assert result is not None
    boundary, level, _ = result
    assert level == "sentence", f"expected 'sentence', got {level!r}"
    assert abs(boundary - 2.0) < 0.5


def test_fallback_level3_comma_only():
    """Level 3: comma boundary used when no sentence boundary exists."""
    from autoreels.__main__ import _find_pause_boundary
    words = [
        _w("раз", 0.0, 1.0), _w("два,", 1.0, 2.0),
        _w("три", 2.0, 3.0), _w("четыре", 3.0, 12.0),
    ]
    result = _find_pause_boundary(words, 0.0, 12.0, target=6.0, min_pause=0.3)
    assert result is not None
    boundary, level, _ = result
    assert level == "comma", f"expected 'comma', got {level!r}"
    assert abs(boundary - 2.0) < 0.1


def test_fallback_no_candidate_returns_none():
    """No candidate when no sentence or comma boundary exists."""
    from autoreels.__main__ import _find_pause_boundary
    words = [
        _w("слово", 0.0, 12.0),
    ]
    result = _find_pause_boundary(words, 0.0, 12.0, target=6.0, min_pause=0.3)
    assert result is None


# ── Tests 14-16: iterative max-shot ──────────────────────────────────────────

def test_prefer_le_target_boundary():
    """With two equidistant candidates, the one <= target is preferred."""
    from autoreels.__main__ import _find_pause_boundary
    # target=10, candidates at 8 (<=10, dist=2) and 12 (>10, dist=2): pick 8
    words = [
        _w("а", 0.0, 1.0), _w("б.", 1.0, 8.0),
        _w("в", 8.0, 9.0), _w("г.", 9.0, 12.0),
        _w("д", 12.0, 20.0),
    ]
    result = _find_pause_boundary(words, 0.0, 20.0, target=10.0, min_pause=0.3,
                                   search_start=2.0, search_end=18.0)
    assert result is not None
    boundary, _, _pause = result
    assert boundary <= 10.0 + 0.1, f"should prefer boundary ≤ target 10.0, got {boundary}"
    assert abs(boundary - 8.0) < 0.1, f"expected ~8.0, got {boundary}"


def test_iterative_splits_30s_into_three():
    """A 30s wide segment with two boundaries is split into exactly 3 spans."""
    from autoreels.__main__ import _stage_two_shot_auto, _shot_spans_merged
    words = [
        _w("а", 0.0, 5.0), _w("б.", 5.0, 10.0),   # sentence boundary at 10.0
        _w("в", 10.0, 15.0), _w("г.", 15.0, 20.0), # sentence boundary at 20.0
        _w("д", 20.0, 30.0),
    ]
    segs = [_seg(0.0, 30.0)]
    reel = _reel(segs)
    _stage_two_shot_auto([reel], words, render_cfg=_cfg(two_shot_max_shot_sec=11.0, two_shot_min_sec=3.0))
    spans = _shot_spans_merged(reel.effective_segments())
    assert len(spans) == 3, f"expected 3 spans, got {len(spans)}: {spans}"
    for stype, dur in spans:
        assert 3.0 <= dur <= 11.0, f"span {stype} {dur:.1f}s outside [3.0, 11.0]"


def test_property_no_short_spans_random_boundaries():
    """No output span is shorter than min_shot regardless of boundary placement."""
    import random
    from autoreels.__main__ import _stage_two_shot_auto, _shot_spans_merged
    rng = random.Random(7)
    min_s, max_s = 2.0, 8.0
    for _ in range(30):
        n = rng.randint(1, 5)
        # Place sentence-ending words at random positions in [3, 27]
        positions = sorted(rng.uniform(3.0, 27.0) for _ in range(n))
        words: list = []
        for i, pos in enumerate(positions):
            words.append(_w(f"w{i}.", pos - 0.4, pos))
        words.append(_w("end", 29.0, 30.0))
        segs = [_seg(0.0, 30.0)]
        reel = _reel(segs)
        _stage_two_shot_auto([reel], words, render_cfg=_cfg(two_shot_max_shot_sec=max_s, two_shot_min_sec=min_s))
        warns = getattr(reel, "_two_shot_warnings", [])
        for stype, dur in _shot_spans_merged(reel.effective_segments()):
            assert dur >= min_s, (
                f"short {stype} {dur:.2f}s < {min_s}s; boundaries={positions}; warns={warns}"
            )
            if dur > max_s:
                assert any("no candidate" in w for w in warns), (
                    f"{stype} {dur:.1f}s > {max_s}s with no 'no candidate' warning; "
                    f"boundaries={positions}; warns={warns}"
                )


# ── Part 2: c: annotation preserved; jump seams force shot change ─────────────────────────────

def test_ci_annotation_not_cleared_by_pass1():
    """wide+ci segments (c: annotations) with no short spans must not have ci cleared.

    ci[0][0]=5.0 > min_shot=2.5 → no leading snap.
    Trailing=0 → no tail snap. close=3s is the last span (not an A-B-A middle).
    Pass 1 must leave the shot and ci intact.
    """
    segs = [_seg(0, 5), _seg(6, 14, "wide", [[5.0, 8.0]])]
    out = _apply(segs)
    assert out[1].shot == "wide",             "shot must stay wide (as annotated)"
    assert out[1].close_intervals == [[5.0, 8.0]], "ci must not be cleared by Pass 1"


def _reel_beat(segs, id="r01"):
    """Reel with beat_gap_sec set — enables jump-seam logic."""
    r = _reel(segs, id=id)
    r.beat_gap_sec = 0.25
    return r


def _apply_beat(segs, words=None, **cfg_kw):
    from autoreels.__main__ import _stage_two_shot_auto
    reel = _reel_beat(segs)
    _stage_two_shot_auto([reel], words or [], render_cfg=_cfg(**cfg_kw))
    return reel


def test_jump_seam_r01_forces_shot_change():
    """Lecture r01 beat order: jump seams produce shot changes with cold-open=close rule.

    beat1=[66.10-69.02] and beat2=[69.04-72.15] have a 0.02 s source gap → pre-merged.
    beat4=[72.74-78.22] and beat5=[78.24-81.54] have a 0.02 s source gap → pre-merged.
    After pre-merge: 3 segments — merged_b1b2(6.05s), beat3(8.32s), merged_b4b5(8.80s).

    Processing (beat mode, cur=close):
    1. merged_b1b2: i=0 → close.
    2. beat3: jump seam (9.41s gap) → toggle → wide.
    3. merged_b4b5: jump seam (backward 17s) → toggle → close.
    4. A-B-A: wide middle 8.32s ≥ min_middle=4.0s → no merge.
    Final output: close(6.05s) → wide(8.32s) → close(8.80s). All spans ≥ 4.0 s.
    """
    segs = [
        _seg(66.10, 69.02),                          # beat1 auto
        _seg(69.04, 72.15, "close"),                  # beat2 (beat mode: not manual)
        _seg(81.56, 89.88, "wide", [[0.06, 8.32]]),   # beat3 (beat mode: not manual)
        _seg(72.74, 78.22, "close"),                  # beat4 (beat mode: not manual)
        _seg(78.24, 81.54, "close"),                  # beat5 (beat mode: not manual)
    ]
    reel = _apply_beat(segs)
    result = reel.effective_segments()
    # beat1+beat2 merged (0.02 s gap), beat4+beat5 merged (0.02 s gap) → 3 segments
    assert len(result) == 3, (
        f"expected 3 segments after pre-merge; got {len(result)}: {[(s.start, s.end) for s in result]}"
    )

    mb12, b3, mb45 = result[0], result[1], result[2]

    # i=0 starts close (cold-open rule); no A-B-A fires (wide middle ≥ min_middle)
    assert mb12.shot == "close" and not mb12.close_intervals, (
        f"merged_b1b2 must be close (cold-open rule); got shot={mb12.shot} ci={mb12.close_intervals}"
    )

    assert b3.shot == "wide" and not b3.close_intervals, (
        f"jump seam → toggle → beat3 must be wide; got shot={b3.shot} ci={b3.close_intervals}"
    )

    assert mb45.shot == "close" and not mb45.close_intervals, (
        f"jump seam → toggle → merged_b4b5 must be close; got shot={mb45.shot} ci={mb45.close_intervals}"
    )

    # No [ERROR] warnings (no sub-min-shot spans, no same-shot jump seams)
    warns = getattr(reel, "_two_shot_warnings", [])
    assert not any("[ERROR]" in w for w in warns), (
        f"no [ERROR] expected; got: {[w for w in warns if '[ERROR]' in w]}"
    )


def test_jump_seam_r06_shot_changes():
    """Lecture r06 beat order: all seams are jump seams; each must change shot.

    beat1=[467.5-469.3], beat2=[452.8-461.0], beat3=[469.7-473.2].
    Cold-open rule: beat1 starts close.
    Seam1: backward jump (-16.5 s) → toggle → beat2=wide.
    Seam2: forward jump 8.6 s → toggle → beat3=close.
    Beat mode ignores manual c: annotations.
    """
    segs = [
        _seg(467.526, 469.276),            # beat1
        _seg(452.786, 461.046, "close"),   # beat2 (beat mode: not manual)
        _seg(469.686, 473.226),            # beat3
    ]
    reel = _apply_beat(segs)
    result = reel.effective_segments()
    assert result[0].shot == "close", "beat1 must be close (cold-open rule)"
    assert result[1].shot == "wide",  "beat2: jump seam toggles to wide (beat mode ignores manual)"
    assert result[2].shot == "close", "beat3: jump seam toggles back to close"
    # Both jump seams must produce shot changes (no [ERROR] same-shot-jump-seam warnings)
    warns = getattr(reel, "_two_shot_warnings", [])
    assert not any("[ERROR]" in w for w in warns), (
        f"no [ERROR] expected for r06; got: {[w for w in warns if '[ERROR]' in w]}"
    )


# ── Part 3: snap close_intervals to window boundary; flash detection ──────────────────────────

def test_snap_ci_near_window_start():
    """close_interval starting within 0.15 s of window start snaps to 0."""
    segs = [_seg(0, 10, "wide", [[0.06, 5.0]])]
    out = _apply(segs)
    assert out[0].close_intervals[0][0] == 0.0, "ci within 0.15 s of start must snap to 0"
    assert out[0].close_intervals[0][1] == 5.0, "ci end must not be moved"


def test_snap_ci_near_window_end():
    """close_interval ending within 0.15 s of window end snaps to segment duration."""
    segs = [_seg(0, 10, "wide", [[3.0, 9.92]])]
    out = _apply(segs)
    # seg dur = 10.0; 10.0 - 9.92 = 0.08 < 0.15 → snap to 10.0
    assert out[0].close_intervals[-1][1] == 10.0, "ci within 0.15 s of end must snap to seg dur"


def test_snap_does_not_move_ci_outside_threshold():
    """close_interval boundaries more than min_shot from window edge must not be moved.

    ci[0][0]=3.0 > min_shot=2.5 → leading wide prefix not snapped.
    dur-ci[-1][1]=3.0 > min_shot=2.5 → trailing wide suffix not snapped.
    close span = 4.0 = min_middle (not < min_middle) → no A-B-A merge.
    """
    segs = [_seg(0, 10, "wide", [[3.0, 7.0]])]
    out = _apply(segs)
    assert out[0].close_intervals[0][0] == pytest.approx(3.0), "ci > min_shot from start must not snap"
    assert out[0].close_intervals[0][1] == pytest.approx(7.0), "ci > min_shot from end must not snap"


def test_snap_fixes_short_wide_gap_below_min_shot():
    """ci prefix of 0.3 s (< min_shot=2.5 s) is snapped away — no [ERROR] remains."""
    # ci starts at 0.3 s → snap extends ci[0][0] to 0.0 (and tail 2.0 s → 10.0)
    # → segment becomes fully close, no short wide span survives
    segs = [_seg(0, 10, "wide", [[0.3, 8.0]])]
    reel = _reel(segs)
    from autoreels.__main__ import _stage_two_shot_auto
    _stage_two_shot_auto([reel], [], render_cfg=_cfg())
    warns = getattr(reel, "_two_shot_warnings", [])
    assert not any("[ERROR]" in w and "short" in w for w in warns), (
        f"snap must fix 0.3 s wide gap; got warns={warns}"
    )


# ── Part 2: pre-merge collapses sub-0.1s gap; no flash ───────────────────────────────────────

def test_small_gap_merged_no_flash():
    """Lecture r01 case: beat4=[72.74-78.22] close + beat5=[78.24-81.54] close have a 0.02 s gap.

    Pre-merge (gap < 0.1 s) must merge them into a single close segment.
    The output-time flash check must report no [ERROR] (no source-time filler treated as flash).
    """
    segs = [
        _seg(72.74, 78.22, "close"),   # beat4
        _seg(78.24, 81.54, "close"),   # beat5, gap=0.02 s < _MERGE_GAP_MAX=0.1 s
    ]
    # Use a plain reel (non-beat) — pre-merge applies regardless of beat_gap_sec.
    from autoreels.__main__ import _stage_two_shot_auto
    reel = _reel(segs)
    _stage_two_shot_auto([reel], [], render_cfg=_cfg())
    result = reel.effective_segments()

    assert len(result) == 1, f"pre-merge should collapse 2 segments into 1; got {len(result)}"
    assert result[0].shot == "close", "merged segment must be close"
    assert result[0].start == pytest.approx(72.74)
    assert result[0].end == pytest.approx(81.54)

    warns = getattr(reel, "_two_shot_warnings", [])
    assert not any("[ERROR]" in w for w in warns), (
        f"no [ERROR] expected after merge; got: {warns}"
    )


# ── PART 2: cold_open first effective segment not absorbed by option 2 ───────────────────────

def test_cold_open_first_seg_not_absorbed_by_option2():
    """cold_open → body jump seam forces body[0] to wide; option 2 must not absorb it.

    cold_open is always close. The jump seam forces body[0] to wide (not close).
    body[0] = 2s < min_shot=2.5s: option 2 would absorb it, but must be skipped (jump seam).
    cold-open A-B-A extension then widens seg1 to avoid the A-B-A.
    """
    segs = [
        _seg(100.0, 102.0),              # seg0: auto, 2s; jump seam → wide; option 2 skipped
        _seg(103.0, 110.0, "close"),     # seg1: manual close; extended to wide by cold-open A-B-A
    ]
    reel = _reel(segs)
    reel.cold_open = _seg(110.5, 114.5, "close")

    from autoreels.__main__ import _stage_two_shot_auto
    _stage_two_shot_auto([reel], [], render_cfg=_cfg())
    result = reel.effective_segments()

    assert result[0].shot == "wide", (
        "first effective segment must be wide (cold_open→body jump seam forces opposite shot)"
    )
    assert result[1].shot == "wide", (
        "seg1 extended to wide by cold-open A-B-A (initial wide 2.0s < min_middle 4.0s)"
    )
    warns = getattr(reel, "_two_shot_warnings", [])
    assert any("cold-open A-B-A" in w for w in warns), (
        f"expected cold-open A-B-A warning; got {warns}"
    )


# ── PART 3: jump-seam close_interval truncation must not leave a sub-min-shot span ───────────

def test_jump_seam_no_sub_min_shot_span():
    """Lecture r01: jump-seam enforcement makes beat3 entirely wide (no short ci span left).

    New rule: when same shot at seam and min_shot < min_middle, make entire next beat opposite.
    beat3 had ci=[[0.06,8.32]] (basically all-close). Jump-seam makes it shot=wide, ci=[]
    → no sub-min-shot span possible, no [ERROR] warning.
    Uses beat_clip_shots_only_at_seams=False (old all-seams-toggle path).
    """
    segs = [
        _seg(66.10, 72.15, "wide", [[0.0, 6.05]]),  # merged_b1b2 after pre-merge (6.05 s close)
        _seg(81.56, 89.88, "wide", [[0.06, 8.32]]),  # beat3: c: annotation, 8.26 s close span
        _seg(72.74, 81.54, "close"),                  # merged_b4b5 after pre-merge
    ]
    reel = _apply_beat(segs, beat_clip_shots_only_at_seams=False)
    warns = getattr(reel, "_two_shot_warnings", [])

    # No [ERROR] for short spans
    error_warns = [w for w in warns if "[ERROR]" in w]
    assert not error_warns, (
        f"no [ERROR] expected after jump-seam JUMP_CLOSE_MIN fix; got: {error_warns}"
    )

    result = reel.effective_segments()
    # beat3 (result[1]) must be entirely wide — truncated ci was < 1.0 s, so dropped
    b3 = result[1]
    b3_has_close_end = b3.shot == "close" or (
        b3.close_intervals and b3.close_intervals[-1][1] > (b3.end - b3.start) - 1.0 / 60.0
    )
    assert not b3_has_close_end, (
        f"beat3 must end wide (sub-min-shot ci dropped); got shot={b3.shot} ci={b3.close_intervals}"
    )


# ── PART 4: jump seam modifies NEXT beat; A-B-A merge ────────────────────────────────────────

def test_jump_seam_next_beat_modified_not_prev():
    """Jump-seam rule modifies the NEXT beat's starting shot, never the previous beat.
    Uses beat_clip_shots_only_at_seams=False (old all-seams-toggle path).
    """
    # A→B jump seam, both start/end close. Prev beat must be unchanged.
    segs = [
        _seg(0.0, 5.0, "close"),    # seg0: close (source 0-5)
        _seg(15.0, 20.0, "close"),  # seg1: close (gap 10s > 2s → jump seam)
    ]
    reel = _apply_beat(segs, beat_clip_shots_only_at_seams=False)
    result = reel.effective_segments()
    assert len(result) == 2
    # seg0 (prev beat) must be unchanged — still close
    assert result[0].shot == "close" and not result[0].close_intervals, (
        f"prev beat must remain close unchanged; got shot={result[0].shot} ci={result[0].close_intervals}"
    )
    # seg1 (next beat) must start wide (opposite of close)
    hf = 1.0 / 60.0
    seg1_starts_wide = not (result[1].shot == "close" or
                            (result[1].close_intervals and result[1].close_intervals[0][0] < hf))
    assert seg1_starts_wide, (
        f"next beat must start wide at jump seam; got shot={result[1].shot} ci={result[1].close_intervals}"
    )


def test_jump_seam_no_aba_when_min_shot_lt_min_middle():
    """When min_shot < min_middle, jump seam makes entire next beat opposite (no A-B-A span).
    Uses beat_clip_shots_only_at_seams=False (old all-seams-toggle path).
    """
    # A (close) → B (close, 8s) at jump seam → B should become all-wide (no short-wide flash)
    segs = [
        _seg(0.0, 3.0, "close"),    # seg0: close 3s
        _seg(15.0, 23.0, "close"),  # seg1: close 8s (gap 12s → jump seam)
    ]
    reel = _apply_beat(segs, beat_clip_shots_only_at_seams=False)
    result = reel.effective_segments()
    assert len(result) == 2
    seg1 = result[1]
    # Entire seg1 must be wide (no partial close interval)
    assert seg1.shot == "wide" and not seg1.close_intervals, (
        f"seg1 must be all-wide (no A-B-A): shot={seg1.shot} ci={seg1.close_intervals}"
    )


def test_aba_merge_short_natural_middle():
    """Natural A-B-A close→wide(3s)→close — 3s < min_middle=4.0 → merged to all-close."""
    # All auto segments. cold-open=close rule: seg0=close, seg1=wide(3s), seg2=close.
    # A-B-A: wide middle 3s < min_middle=4.0 → merge to close.
    # Gaps 0.5 s between segments to avoid pre-merge (needs gap < 0.1 s).
    segs = [
        _seg(0.0, 10.0),      # seg0: auto → close (cold-open rule)
        _seg(10.5, 13.5),     # seg1: auto → wide (3s, < min_middle=4.0)
        _seg(14.0, 24.0),     # seg2: auto → close
    ]
    reel = _reel(segs)
    from autoreels.__main__ import _stage_two_shot_auto
    _stage_two_shot_auto([reel], [], render_cfg=_cfg())
    result = reel.effective_segments()
    assert len(result) == 3, f"expected 3 segments; got {len(result)}"
    # A-B-A must merge the short wide middle to close
    assert result[1].shot == "close" and not result[1].close_intervals, (
        f"short wide middle must be merged to close; got shot={result[1].shot} ci={result[1].close_intervals}"
    )


def test_aba_removes_premerge_ci():
    """A-B-A must fire through pre-merge ci (not blocked by it).

    Before fix: ci-guard blocked A-B-A whenever the middle segment had any ci,
    including ci created by pre-merge (wide+close gap<0.1s → wide+ci).
    After fix: only Pass-3 ci is protected (_pass3_segs); pre-merge ci is removed.
    """
    # wide(0-5) + close(5.05-7.5, gap=0.05) → pre-merge → wide(0-7.5, ci=[[5.05, 7.5]])
    # ci span = 2.45s < min_middle=4.0 → A-B-A candidate
    segs = [
        _seg(0.0, 5.0),            # seg0: wide 5s
        _seg(5.05, 7.5, "close"),  # seg1: close 2.45s (gap=0.05 → pre-merge with seg0)
        _seg(9.0, 17.0),           # seg2: wide 8s
    ]
    out = _apply(segs)
    assert len(out) == 2, f"expected 2 segments after pre-merge; got {len(out)}"
    # pre-merge ci (2.45s close span) must be removed by A-B-A
    assert out[0].shot == "wide" and not out[0].close_intervals, (
        f"A-B-A must remove pre-merge ci; got shot={out[0].shot} ci={out[0].close_intervals}"
    )


def test_aba_merge_skips_jump_seam_forced():
    """A-B-A merge must NOT remove a span that was set by jump-seam enforcement.

    seg0(close) → seg1(forced wide by jump seam, 3s) → seg2(close) = A-B-A with short middle.
    A-B-A merge must skip seg1 because it is in _js_forced.
    Uses beat_clip_shots_only_at_seams=False (old all-seams-toggle path).
    """
    # Gap 0.5 s between seg1 and seg2 to avoid pre-merge (needs < 0.1 s to pre-merge).
    segs = [
        _seg(0.0, 3.0, "close"),     # seg0: close 3s
        _seg(15.0, 18.0, "close"),   # seg1: close 3s (gap 12s → jump seam → forced wide)
        _seg(18.5, 25.5, "close"),   # seg2: close 7s (gap 0.5s → not a jump seam)
    ]
    reel = _apply_beat(segs, beat_clip_shots_only_at_seams=False)
    result = reel.effective_segments()
    assert len(result) == 3, f"expected 3 segments; got {len(result)}: {[(s.start, s.end) for s in result]}"
    # seg1 was forced wide by jump seam (3s < min_middle=4.0, so entire seg made wide, in _js_forced)
    # A-B-A: close(seg0)→wide(seg1,3s)→close(seg2) → would trigger merge without guard
    # Guard: seg1 in _js_forced → merge skipped → seg1 stays wide
    assert result[0].shot == "close", "seg0 must remain close"
    assert result[1].shot == "wide" and not result[1].close_intervals, (
        f"seg1 must stay wide (jump-seam forced, A-B-A guard); got shot={result[1].shot} ci={result[1].close_intervals}"
    )
    assert result[2].shot == "close", "seg2 must remain close"


# ── PART 5: beat_clip_shots_only_at_seams — new default rule ─────────────────

def test_beat_shots_only_at_seams_r01():
    """beat_clip_shots_only_at_seams=True: shot changes ONLY at jump seams.

    r01 segment layout (source order in output, 5 segments):
      seg0 66.10-69.02  (non-jump to seg1, gap=0.02s)
      seg1 69.04-72.15  (jump to seg2, gap=9.41s)
      seg2 81.56-89.88  (jump to seg3, backward 17s)
      seg3 72.74-78.22  (non-jump to seg4, gap=0.02s)
      seg4 78.24-81.54

    After pre-merge (gap 0.02 s < 0.1 s merges adjacent segments):
      merged01 66.10-72.15 (6.05 s)  → wide (no toggle at non-jump seam)
      seg2     81.56-89.88 (8.32 s)  → close (jump toggle)
      merged34 72.74-81.54 (8.80 s)  → wide (jump toggle back)

    Expected: close(0-6.05s) → wide(6.05-14.37s) → close(14.37-end)
    """
    segs = [
        _seg(66.10, 69.02),  # wide (auto)
        _seg(69.04, 72.15),  # wide (auto)
        _seg(81.56, 89.88),  # wide (auto)
        _seg(72.74, 78.22),  # wide (auto)
        _seg(78.24, 81.54),  # wide (auto)
    ]
    reel = _apply_beat(segs)   # beat_clip_shots_only_at_seams=True by default
    result = reel.effective_segments()
    # Pre-merge collapses adjacent pairs → 3 segments
    assert len(result) == 3, f"expected 3 after pre-merge; got {len(result)}: {[(s.start,s.end) for s in result]}"
    shots = [s.shot for s in result]
    assert shots == ["close", "wide", "close"], (
        f"expected [close,wide,close] (cold-open rule, non-jump seams don't toggle); got {shots}"
    )
    durs = [round(s.end - s.start, 2) for s in result]
    assert durs == [6.05, 8.32, 8.80], f"expected durations [6.05, 8.32, 8.80]; got {durs}"
    for s in result:
        assert not s.close_intervals, f"no ci inside beats; got ci={s.close_intervals}"


def test_beat_shots_only_at_seams_r01_stale_manifest():
    """Stale manifest shots must not survive into the render.

    Mirrors the real r01 manifest: seg1 has shot=close (an adjacent-seam stale assignment)
    and seg2 has wide+ci (wrong pre-snap ci).  After _apply_two_shot_auto_reel the result
    must be [wide, close, wide] with no ci — identical to the fresh-segments case.
    """
    segs = [
        _seg(66.10, 69.02, "wide"),           # beat block 1, seg0 (stale: wide, fine)
        _seg(69.04, 72.15, "close"),           # beat block 1, seg1 — STALE: close at adjacent seam
        _seg(81.56, 89.88, "wide", [[0.060, 8.320]]),  # beat block 2, STALE ci
        _seg(72.74, 78.22, "close"),           # beat block 3, seg0 (stale: close)
        _seg(78.24, 81.54, "close"),           # beat block 3, seg1 (stale: close)
    ]
    reel = _apply_beat(segs)
    result = reel.effective_segments()
    assert len(result) == 3, f"expected 3 after pre-merge; got {len(result)}"
    shots = [s.shot for s in result]
    assert shots == ["close", "wide", "close"], (
        f"stale manifest shots must be overwritten; got {shots}"
    )
    for s in result:
        assert not s.close_intervals, f"no ci inside beats; got ci={s.close_intervals}"


def test_beat_shots_only_at_seams_r06():
    """beat_clip_shots_only_at_seams=True: r06 has only jump seams → all seams toggle.

    r06 segment layout:
      seg0 467.52-469.28  (jump to seg1, backward 14.7s)
      seg1 452.79-461.05  (jump to seg2, gap=8.64s)
      seg2 469.69-473.23

    Expected shots: [wide, close, wide] — unchanged from the all-seams-toggle path.
    """
    segs = [
        _seg(467.526, 469.276),   # wide (auto)
        _seg(452.786, 461.046),   # wide (auto)
        _seg(469.686, 473.226),   # wide (auto)
    ]
    reel = _apply_beat(segs, id="r06")
    result = reel.effective_segments()
    shots = [s.shot for s in result]
    assert shots == ["close", "wide", "close"], (
        f"expected [close,wide,close]; got {shots}"
    )
    for s in result:
        assert not s.close_intervals, f"no ci inside beats; got ci={s.close_intervals} on seg {s.start}"


# ── Part 1 gate: assign_shots public API ─────────────────────────────────────

def test_assign_shots_pxl_r01_cold_open_close():
    """assign_shots: cold_open→body seam changes shot, c: preserved, no A-B-A incl. cold_open."""
    from autoreels.__main__ import assign_shots, _shot_spans_merged, _shot_spans_output

    # Gaps >= 2.5s so fillers don't create sub-min_shot wide spans.
    segs = [
        _seg(0.0, 5.0),                                           # auto 5s
        _seg(7.5, 13.5),                                          # auto 6s (gap=2.5s)
        _seg(16.0, 43.0, "wide", [[0.0, 9.0], [17.0, 27.0]]),    # c: annotation (2 intervals, gap=2.5s)
    ]
    reel = _reel(segs)
    reel.cold_open = _seg(43.0, 47.0, "close")

    assign_shots(reel, [], render_cfg=_cfg())

    # cold_open is always close by construction
    assert reel.cold_open.shot == "close", "cold_open must be close"

    result = reel.effective_segments()

    # cold_open→body jump seam changes shot: body[0] must be wide
    assert result[0].shot == "wide", (
        "cold_open→body jump seam must force body[0] to wide (opposite of close)"
    )

    # c: annotation must be preserved
    assert result[2].shot == "wide", "c: annotation shot must stay wide"
    assert result[2].close_intervals, "c: annotation ci must be preserved"

    # No span < two_shot_min_sec
    for stype, dur in _shot_spans_merged(result):
        assert dur >= 2.5, f"short {stype} span: {dur:.2f}s < 2.5s"

    # No A-B-A middle < min_middle=4.0s — check includes cold_open span
    co_dur = reel.cold_open.end - reel.cold_open.start
    full_spans = [("close", 0.0, co_dur)] + [
        (sh, sa + co_dur, se + co_dur)
        for sh, sa, se in _shot_spans_output(result)
    ]
    for i in range(len(full_spans) - 2):
        sa, _, _ = full_spans[i]
        sb, b0, be = full_spans[i + 1]
        sc, _, _ = full_spans[i + 2]
        bd = be - b0
        assert not (sa == sc and sa != sb and bd < 4.0), (
            f"A-B-A middle {sb}({bd:.2f}s) at output {b0:.2f}–{be:.2f} < 4.0s (incl. cold_open)"
        )


def test_assign_shots_lec_r01_beat_seams():
    """assign_shots: lecture r01 beat reel — shot changes ONLY at jump seams."""
    from autoreels.__main__ import assign_shots

    segs = [
        _seg(66.10, 69.02),
        _seg(69.04, 72.15),
        _seg(81.56, 89.88),
        _seg(72.74, 78.22),
        _seg(78.24, 81.54),
    ]
    reel = _reel_beat(segs)
    assign_shots(reel, [], render_cfg=_cfg())
    result = reel.effective_segments()

    assert len(result) == 3, f"expected 3 after pre-merge; got {len(result)}"
    shots = [s.shot for s in result]
    assert shots == ["close", "wide", "close"], (
        f"beat reel: shot changes only at jump seams; got {shots}"
    )
    durs = [round(s.end - s.start, 2) for s in result]
    assert durs == [6.05, 8.32, 8.80], f"durations must be unchanged; got {durs}"


# ── Rule3 priority tests ───────────────────────────────────────────────────────

def test_rule3_double_jump_seam_no_short_span():
    """Rule3 > Rule2: 0.76s segment at double-jump seam must not produce a short span.

    pxl1129/r01 proxy: segs 0-3 close, seg4=wide(0.76s) between two jump seams,
    segs 5-6 close.  After Rule3, seg4 should get the same shot as the previous
    ending (close), merging into the large close spans → no span < 2.5s, no [ERROR].
    """
    from autoreels.__main__ import _stage_two_shot_auto, _shot_spans_output

    segs = [
        _seg(86.84, 97.27, "close"),
        _seg(97.54, 100.42, "close"),
        _seg(102.27, 103.93, "close"),
        _seg(104.29, 104.82, "close"),
        _seg(107.19, 107.95, "wide"),   # 0.760 s — double-jump: left=2.37s, right=29.28s
        _seg(137.23, 149.96, "close"),
        _seg(150.26, 152.39, "close"),
        _seg(109.86, 113.56, "wide"),
    ]
    reel = _reel_beat(segs)
    _stage_two_shot_auto([reel], [], render_cfg=_cfg())
    result = reel.effective_segments()

    # no [ERROR] in warnings
    warns = getattr(reel, "_two_shot_warnings", [])
    errors = [w for w in warns if "[ERROR]" in w]
    assert not errors, f"unexpected [ERROR] warnings: {errors}"

    # no output span < min_shot after merging
    spans = _shot_spans_output(result)
    short = [(stype, sa, se) for stype, sa, se in spans if se - sa < 2.5]
    assert not short, f"short spans found: {short}"


def test_rule3_c_annotation_short_range_filtered():
    """Rule3 > Rule4: a c: annotation range shorter than min_shot must be filtered out.

    lec0933/r03 / lec1059/r03 proxy: reel with _c_close_ranges where the range is
    1.12s < 2.5s (min_shot).  After applying, no close_intervals should be created.
    """
    from autoreels.__main__ import _stage_two_shot_auto
    from autoreels.local.render import assign_close_shots

    seg = _seg(0.0, 40.0)
    reel = _reel([seg])
    reel._c_close_ranges = [[38.5, 39.62]]  # 1.12 s — shorter than min_shot=2.5s

    # Simulate the assign_close_shots call with Rule3 filter (as done in --apply flow).
    _min_c = 2.5
    c_ranges = [r for r in reel._c_close_ranges if r[1] - r[0] >= _min_c]
    if c_ranges:
        reel.segments = assign_close_shots(reel.effective_segments(), c_ranges)

    # No close_intervals should be set (filtered before assign_close_shots).
    for s in reel.effective_segments():
        assert not getattr(s, "close_intervals", []), (
            f"expected no close_intervals after Rule3 filter; got {s.close_intervals}"
        )


def test_rule3_c_annotation_adequate_range_passes():
    """Sanity: a c: range ≥ min_shot is NOT filtered out."""
    from autoreels.local.render import assign_close_shots

    seg = _seg(0.0, 40.0)
    reel = _reel([seg])
    reel._c_close_ranges = [[34.0, 40.0]]  # 6.0 s — well above min_shot=2.5s

    _min_c = 2.5
    c_ranges = [r for r in reel._c_close_ranges if r[1] - r[0] >= _min_c]
    if c_ranges:
        reel.segments = assign_close_shots(reel.effective_segments(), c_ranges)

    # close_intervals should be set (range is large enough).
    has_ci = any(getattr(s, "close_intervals", []) for s in reel.effective_segments())
    assert has_ci, "expected close_intervals for a ≥2.5s c: range"


# ── jump-seam minimum for A-B-A middles (task: r03 fix) ──────────────────────

def _reel_with_cold_open(segs, co_seg):
    """Reel with cold_open set."""
    r = _reel(segs)
    r.cold_open = co_seg
    return r


def test_cold_open_seam_is_jump_seam_passes_2_13s():
    """cold_open → body is a jump seam; body[0] of 2.13s (>= 1.0s) must NOT produce [ERROR].

    IMG r03 proxy: cold_open close, then body[0] wide 2.13s, body[1] close with source gap.
    """
    from autoreels.__main__ import _stage_two_shot_auto

    # body[0] at source 30-32.13 (2.13s); body[1] at source 40-50 (jump gap 7.87s > 2s)
    segs = [
        _seg(30.0, 32.13),        # body[0]: 2.13s, will be wide
        _seg(40.0, 50.0, "close"),  # body[1]: 10s close
    ]
    reel = _reel_with_cold_open(segs, _seg(55.0, 60.0, "close"))  # cold_open far from body

    _stage_two_shot_auto([reel], [], render_cfg=_cfg())
    warns = getattr(reel, "_two_shot_warnings", [])
    errors = [w for w in warns if "[ERROR]" in w]
    assert not errors, f"2.13s between two jump seams must pass; got errors: {errors}"
    result = reel.effective_segments()
    assert result[0].shot == "wide", "body[0] must remain wide (jump-seam alternation)"


def test_x_seam_is_jump_seam_passes_2_13s():
    """Non-adjacent source sentences (x: cut gap > 2s) create a jump seam.

    A 2.13s wide span between two such seams must NOT produce [ERROR].
    """
    from autoreels.__main__ import _stage_two_shot_auto

    # seg0 close (10s), seg1 wide gap > 2s on both sides (2.13s), seg2 close (10s)
    segs = [
        _seg(0.0, 10.0, "close"),    # seg0: 10s close
        _seg(15.0, 17.13),           # seg1: 2.13s; gap from seg0 is 5s > 2s (jump); gap to seg2 is 5s > 2s (jump)
        _seg(22.13, 32.13, "close"), # seg2: 10s close
    ]
    reel = _reel(segs)
    _stage_two_shot_auto([reel], [], render_cfg=_cfg())
    warns = getattr(reel, "_two_shot_warnings", [])
    errors = [w for w in warns if "[ERROR]" in w]
    assert not errors, f"2.13s between two x:-seams must pass; got errors: {errors}"


def test_double_jump_seam_0_8s_still_fails():
    """A span < 1.0s between two jump seams fails via Rule3 (too short to alternate).

    Rule3 fires for segments < _JUMP_SEAM_MIN (1.0s) at a double-jump seam: assigns same shot
    as prev end with a [WARNING] rather than silently passing.
    Requires beat_gap_sec so _enforce_jump_seams runs and creates the wide alternation.
    """
    segs = [
        _seg(0.0, 10.0, "close"),   # seg0: close 10s
        _seg(15.0, 15.8),           # seg1: 0.8s; gap 5s on each side → both jump seams
        _seg(20.8, 30.8, "close"),  # seg2: close 10s
    ]
    reel = _apply_beat(segs)
    warns = getattr(reel, "_two_shot_warnings", [])
    # Rule3 fires: [WARNING] "too short to alternate" — not a silent pass
    rule3 = [w for w in warns if "Rule3" in w or "too short to alternate" in w]
    assert rule3, f"0.8s double-jump span must trigger Rule3 warning; got warns: {warns}"


# ── is_jump_seam unit tests ────────────────────────────────────────────────────

def test_is_jump_seam_x_cut_skipped_sentence():
    """A word in the gap (x: exclusion) makes the boundary a jump seam."""
    from types import SimpleNamespace
    from autoreels.core.seams import is_jump_seam
    from autoreels.core.models import Word

    prev_win = SimpleNamespace(start=0.0, end=10.0)
    next_win = SimpleNamespace(start=13.5, end=15.0)  # 1.5s sentence after gap
    words = [
        Word(word="last", t0=9.5, t1=10.0, emph=False),
        Word(word="skip", t0=11.0, t1=11.5, emph=False),   # in the gap → skipped sentence
        Word(word="first", t0=13.5, t1=14.0, emph=False),
    ]
    assert is_jump_seam(prev_win, next_win, words), (
        "word in gap means a sentence was skipped → must be a jump seam"
    )


def test_is_jump_seam_adjacent_long_pause_not_a_jump():
    """Adjacent sentences with a 2.5s pause (no skipped words) are NOT a jump seam."""
    from types import SimpleNamespace
    from autoreels.core.seams import is_jump_seam
    from autoreels.core.models import Word

    prev_win = SimpleNamespace(start=0.0, end=10.0)
    next_win = SimpleNamespace(start=12.5, end=20.0)
    words = [
        Word(word="last", t0=9.5, t1=10.0, emph=False),   # end of prev window
        Word(word="first", t0=12.5, t1=13.0, emph=False),  # start of next window
    ]
    # gap = 2.5s, but no word in (10.0, 12.5) → not a jump seam
    assert not is_jump_seam(prev_win, next_win, words), (
        "no word in the gap → consecutive sentences, just a pause → not a jump seam"
    )


def test_is_jump_seam_cold_open_always_jump():
    """cold_open=True always returns True regardless of windows or sentences."""
    from types import SimpleNamespace
    from autoreels.core.seams import is_jump_seam

    prev_win = SimpleNamespace(start=5.0, end=8.0)
    next_win = SimpleNamespace(start=10.0, end=15.0)
    assert is_jump_seam(prev_win, next_win, cold_open=True), (
        "cold open → body is always a structural jump seam"
    )


# ── Part 2: shots only for emphasis and seams (human clips) ──────────────────

def _apply_human(segs, words=None, **cfg_kw):
    from autoreels.__main__ import _stage_two_shot_auto
    reel = _reel(segs)
    cfg_kw.setdefault("two_shot_auto_human", False)
    _stage_two_shot_auto([reel], words or [], render_cfg=_cfg(**cfg_kw), selection_source="human")
    return reel


def test_human_no_c_no_seams_one_shot():
    """Human clip with adjacent sentences and no c: → all segments same shot (no alternation)."""
    # Adjacent sentences (no skipped words) — no jump seams, no c: annotations
    words = [
        Word(word="a", t0=0.5, t1=1.0, emph=False),
        Word(word="b", t0=3.5, t1=4.0, emph=False),
        Word(word="c", t0=6.5, t1=7.0, emph=False),
    ]
    segs = [_seg(0, 3), _seg(3, 6), _seg(6, 9)]
    reel = _apply_human(segs, words)
    shots = [s.shot for s in reel.effective_segments()]
    # All same shot — no alternation occurred
    assert len(set(shots)) == 1, f"expected one shot value, got {shots}"


def test_human_with_c_exactly_one_switch():
    """Human clip: c_close_ranges drives close; stale shot=close on segment is reset to wide."""
    words = [
        Word(word="a", t0=0.5, t1=1.0, emph=False),
        Word(word="b", t0=4.5, t1=5.0, emph=False),
        Word(word="c", t0=10.0, t1=10.5, emph=False),
    ]
    # Middle segment has stale shot='close' from a prior auto run — must be reset.
    # c_close_ranges covers segment 2 fully → close via c: range application, not stale shot.
    # Adjacent gaps (0.5s) are not jump seams, so no alternation flip occurs.
    from autoreels.__main__ import _stage_two_shot_auto
    segs = [_seg(0, 3.5), _seg(4, 9, shot="close"), _seg(9.5, 13)]
    reel = _reel(segs)
    reel.c_close_ranges = [[4.0, 9.0]]
    _stage_two_shot_auto([reel], words, render_cfg=_cfg(two_shot_auto_human=False), selection_source="human")
    result = reel.effective_segments()
    assert result[1].shot == "close", f"c: range must produce close, got {result[1].shot}"
    assert not result[0].close_intervals, "auto must not add ci to non-c: seg"


# ── Part 1 fix: human shots reset from scratch using c_close_ranges and jump seams ────────────


def test_human_r01_cold_open_body0_wide_body1_close_via_jump_seam():
    """r01 proxy: cold_open → wide body[0] → x: seam (terminal in gap) → close body[1]; c: redundant.

    Stale shot=close on both body segs must be cleared; x: seam drives body[1]=close.
    """
    from autoreels.__main__ import _stage_two_shot_auto
    # segs match IMG_6848 r01 body segments; both have stale shot=close from prior auto run
    segs = [
        _seg(164.349, 196.279, shot="close"),
        _seg(200.629, 205.689, shot="close"),
    ]
    # Terminal word in the 4.35s gap (x: cut leaves a sentence-ending word in the gap)
    words = [Word(word="нет.", t0=197.0, t1=197.4, emph=False)]
    reel = _reel(segs)
    reel.c_close_ranges = [[202.609, 205.709]]  # c:10 covers only end of body[1]
    reel.cold_open = _seg(201.409, 205.709, shot="close")
    _stage_two_shot_auto([reel], words, render_cfg=_cfg(two_shot_auto_human=False), selection_source="human")
    result = reel.effective_segments()
    assert result[0].shot == "wide", f"body[0] must be wide after cold_open flip; got {result[0].shot}"
    assert result[1].shot == "close", f"body[1] must be close via x: seam (terminal in gap); got {result[1].shot}"


def test_human_r02_no_cold_open_no_jump_seam_c_adds_ci():
    """r02 proxy: no cold_open, no jump seam → base wide; c:7 adds close_intervals only.

    Stale shot=close must be reset; partial c: range adds ci to wide segment.
    """
    from autoreels.__main__ import _stage_two_shot_auto
    segs = [_seg(642.355, 675.95, shot="close")]  # stale shot from prior auto run
    reel = _reel(segs)
    reel.c_close_ranges = [[673.015, 675.815]]  # partial coverage (last 2.8s of 33.6s segment)
    _stage_two_shot_auto([reel], [], render_cfg=_cfg(two_shot_auto_human=False), selection_source="human")
    result = reel.effective_segments()
    assert result[0].shot == "wide", f"base must be wide (no jump seam); got {result[0].shot}"
    ci = result[0].close_intervals or []
    assert ci, "c: range must produce close_intervals on wide segment"
    assert abs(ci[0][0] - (673.015 - 642.355)) < 0.1, f"ci start wrong: {ci[0][0]}"
    # ci end snaps to segment end if within _SNAP_THRESH=0.15s of it
    assert ci[0][1] <= 675.95 - 642.355 + 0.01, f"ci end must not exceed segment end: {ci[0][1]}"
    assert ci[0][1] >= 675.815 - 642.355 - 0.2, f"ci end must be near c: range end: {ci[0][1]}"


def test_human_r03_x7_jump_seam_makes_body1_close():
    """r03 proxy: cold_open → wide body[0]; x:7 x: seam (4.05s gap, terminal word) → close body[1].

    Both body segs previously wide (stale); x: seam flip drives body[1]=close.
    """
    from autoreels.__main__ import _stage_two_shot_auto
    segs = [
        _seg(851.238, 853.37, shot="wide"),   # 2.13s — check it stays wide
        _seg(857.42, 901.5, shot="wide"),     # 44s — x: seam flip to close
    ]
    # Terminal word in the 4.05s gap (x:7 cut)
    words = [Word(word="всё.", t0=854.0, t1=854.4, emph=False)]
    reel = _reel(segs)
    reel.c_close_ranges = [[900.540, 901.340]]  # c:14 at end of body[1] (0.8s, partial)
    reel.cold_open = _seg(899.600, 901.340, shot="close")
    _stage_two_shot_auto([reel], words, render_cfg=_cfg(two_shot_auto_human=False), selection_source="human")
    result = reel.effective_segments()
    assert result[0].shot == "wide", f"body[0] must be wide after cold_open flip; got {result[0].shot}"
    assert result[1].shot == "close", f"body[1] must be close via x:7 x: seam; got {result[1].shot}"


# ── r05 fix: c: span at jump seam satisfies flip, no separate short A-B-A span ──

def test_human_r05_c_at_jump_seam_no_aba_error():
    """r05: c:3 ends 1.46s before seg0 end, then x:1,2 jump seam flips seg1→close.

    Option 2 extends ci to seg0 end; combined ci+seg1 creates 2.70s A-B-A middle.
    Fix: ci ends at jump-seam boundary → revert seg1 to wide; A-B-A merge drops ci.
    Result: no [ERROR] A-B-A warning.
    """
    from autoreels.__main__ import _stage_two_shot_auto
    # seg0: 14.366s (last 1.46s covered by c:3)
    # seg1: 1.130s — jump seam from seg0 (8s source gap > jump_seam_gap_sec=2.0)
    # seg2-4: more segments (close/wide from manifest)
    seg0 = _seg(1201.384, 1215.750, shot="close")  # stale shot from manifest
    seg1 = _seg(1223.764, 1224.894, shot="close")  # stale; jump seam from seg0
    seg2 = _seg(1225.124, 1232.590, shot="close")
    seg3 = _seg(1233.850, 1239.494, shot="close")
    seg4 = _seg(1239.924, 1242.104, shot="wide")
    segs = [seg0, seg1, seg2, seg3, seg4]
    reel = _reel(segs)
    reel.c_close_ranges = [[1214.184, 1215.644]]  # 1.46s at end of seg0
    _stage_two_shot_auto([reel], [], render_cfg=_cfg(two_shot_auto_human=False,
                                                     jump_seam_gap_sec=2.0),
                         selection_source="human")
    result = reel.effective_segments()
    warnings = getattr(reel, "_two_shot_warnings", [])
    # No [ERROR] in warnings
    errors = [w for w in warnings if "[ERROR]" in w]
    assert not errors, f"expected no [ERROR] warnings; got: {errors}"
    # seg0 must be wide (ci absorbed then removed by A-B-A merge)
    assert result[0].shot == "wide" and not result[0].close_intervals, (
        f"seg0 should be wide (ci dropped by A-B-A merge); got shot={result[0].shot} ci={result[0].close_intervals}"
    )
    # seg1 must be wide (reverted from jump-seam flip by c:-at-seam rule)
    assert result[1].shot == "wide", (
        f"seg1 should be wide (c: at seam satisfies flip); got {result[1].shot}"
    )
