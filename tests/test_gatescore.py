"""M188: unit tests for cloud/gatescore.py — per-clip and per-source gate metrics."""
from __future__ import annotations

import pytest

from autoreels.cloud.gatescore import score_clip, summarize, coverage, verdicts


# ── helpers ───────────────────────────────────────────────────────────────────

def _seg(start, end, shot="wide", window_cut=False, close_intervals=None):
    return {
        "start": start, "end": end, "shot": shot,
        "window_cut": window_cut,
        "close_intervals": close_intervals or [],
    }


def _co(start, end, shot="close"):
    return {"start": start, "end": end, "shot": shot, "window_cut": False, "close_intervals": []}


def _word(word, t0, t1=None, emph=False):
    return {"word": word, "t0": t0, "t1": t1 or t0 + 0.3, "emph": emph}


def _pword(t0, end_pct, v=20, dur=0.3):
    return {"t0": t0, "v": v, "end_pct": end_pct, "dur": dur}


def _reel(start, end, segments=None, cold_open=None, subtitles=None, speed=1.0, warnings=None):
    segs = segments if segments is not None else [_seg(start, end)]
    return {
        "id": "r01",
        "start": start, "end": end,
        "segments": segs,
        "cold_open": cold_open,
        "subtitles": subtitles or [],
        "speed": speed,
        "warnings": warnings or [],
        "marks": [],
        "reordered": False,
    }


def _cfg(short_shot_sec=2.0, context_min_words=4):
    return {"short_shot_sec": short_shot_sec, "context_min_words": context_min_words}


# ── 1. dur ────────────────────────────────────────────────────────────────────

def test_dur_no_cold_open():
    r = _reel(10.0, 20.0, speed=1.0)
    c = score_clip(r, {}, {}, _cfg())
    assert abs(c["dur"] - 10.0) < 1e-6


def test_dur_with_cold_open_and_speed():
    # cold_open = 3s, body = 10s, speed = 1.1 → (3+10)/1.1
    co = _co(0.0, 3.0)
    r = _reel(10.0, 20.0, cold_open=co, speed=1.1)
    c = score_clip(r, {}, {}, _cfg())
    assert abs(c["dur"] - 13.0 / 1.1) < 1e-4


def test_dur_multi_segment_with_speed():
    segs = [_seg(10.0, 15.0), _seg(20.0, 25.0)]
    r = _reel(10.0, 25.0, segments=segs, speed=2.0)
    c = score_clip(r, {}, {}, _cfg())
    assert abs(c["dur"] - 5.0) < 1e-6  # (5+5)/2


# ── 2. seams, cuts, back_jumps ────────────────────────────────────────────────

def test_seams_and_cuts_distinguished_by_window_cut():
    segs = [
        _seg(0.0, 5.0, window_cut=False),
        _seg(5.0, 10.0, window_cut=False),   # seam
        _seg(10.0, 15.0, window_cut=True),   # cut
    ]
    r = _reel(0.0, 15.0, segments=segs)
    c = score_clip(r, {}, {}, _cfg())
    assert c["seams"] == 1
    assert c["cuts"] == 1


def test_back_jumps_reorder():
    # second segment starts before first (reordered)
    segs = [
        _seg(20.0, 30.0, window_cut=False),
        _seg(5.0, 15.0, window_cut=False),   # starts earlier → back_jump
    ]
    r = _reel(5.0, 30.0, segments=segs)
    c = score_clip(r, {}, {}, _cfg())
    assert c["back_jumps"] == 1


def test_no_back_jumps_normal_order():
    segs = [_seg(0.0, 5.0), _seg(6.0, 10.0)]
    r = _reel(0.0, 10.0, segments=segs)
    c = score_clip(r, {}, {}, _cfg())
    assert c["back_jumps"] == 0


# ── 3. first_text, start_backref, start_short ─────────────────────────────────

def test_first_text_stops_on_period():
    # "Страх мешает. Но можно" → first_text = ["Страх", "мешает."]
    words = [
        _word("Страх", 1.0), _word("мешает.", 1.3), _word("Но", 1.6), _word("можно", 1.9),
    ]
    r = _reel(0.9, 5.0, subtitles=words)
    c = score_clip(r, {}, {}, _cfg())
    assert c["first_text"] == "Страх мешает."


def test_first_text_no_sentence_end():
    words = [_word("Просто", 1.0), _word("идти", 1.3), _word("вперёд", 1.6)]
    r = _reel(0.9, 5.0, subtitles=words)
    c = score_clip(r, {}, {}, _cfg())
    assert c["first_text"] == "Просто идти вперёд"


def test_start_backref_detected():
    # "И это так важно." — starts with "И" → back_reference returns non-None
    words = [_word("И", 1.0), _word("это", 1.3), _word("так", 1.6), _word("важно.", 1.9)]
    r = _reel(0.9, 5.0, subtitles=words)
    c = score_clip(r, {}, {}, _cfg())
    assert c["start_backref"] is not None


def test_start_backref_question_none():
    # "Что такое страх?" — question, should not be back_reference
    words = [_word("Что", 1.0), _word("такое", 1.3), _word("страх?", 1.6)]
    r = _reel(0.9, 5.0, subtitles=words)
    c = score_clip(r, {}, {}, _cfg())
    assert c["start_backref"] is None


def test_start_short_below_threshold():
    # 2 words, threshold = 4, not a question
    words = [_word("Идти", 1.0), _word("надо.", 1.3)]
    r = _reel(0.9, 5.0, subtitles=words, speed=1.0)
    c = score_clip(r, {}, {}, _cfg(context_min_words=4))
    assert c["start_short"] is True


def test_start_short_question_not_short():
    words = [_word("Да?", 1.0)]
    r = _reel(0.9, 5.0, subtitles=words)
    c = score_clip(r, {}, {}, _cfg(context_min_words=4))
    assert c["start_short"] is False


# ── 4. end_tone ───────────────────────────────────────────────────────────────

def test_end_tone_final():
    words = [_word("хорошо.", 5.0)]
    r = _reel(4.9, 6.0, subtitles=words)
    prosody = {"words": [_pword(5.0, 10.0)]}   # end_pct=10 → final
    c = score_clip(r, {}, prosody, _cfg())
    assert c["end_tone"] == "final"


def test_end_tone_open():
    words = [_word("говорит", 5.0)]
    r = _reel(4.9, 6.0, subtitles=words)
    prosody = {"words": [_pword(5.0, 80.0)]}   # end_pct=80 → open
    c = score_clip(r, {}, prosody, _cfg())
    assert c["end_tone"] == "open"


def test_end_tone_none_no_prosody_entry():
    words = [_word("нет.", 5.0)]
    r = _reel(4.9, 6.0, subtitles=words)
    prosody = {"words": [_pword(10.0, 50.0)]}  # no entry near t0=5.0
    c = score_clip(r, {}, prosody, _cfg())
    assert c["end_tone"] == "none"


def test_end_tone_none_empty_prosody():
    words = [_word("конец.", 5.0)]
    r = _reel(4.9, 6.0, subtitles=words)
    c = score_clip(r, {}, {}, _cfg())
    assert c["end_tone"] == "none"


# ── 5. coverage ───────────────────────────────────────────────────────────────

def _gate_reel(id_, start, end, segments=None):
    segs = segments or [_seg(start, end)]
    return {**_reel(start, end, segments=segs), "id": id_}


def _owner_reel(id_, start, end, segments=None):
    segs = segments or [_seg(start, end)]
    return {**_reel(start, end, segments=segs), "id": id_}


def test_coverage_found_at_60_pct():
    owner = [_owner_reel("o1", 0.0, 10.0)]
    gate = [_gate_reel("g1", 0.0, 6.0)]   # 6/10 = 60% of shorter (6s) → found
    result = coverage(owner, gate)
    assert result["found"] == 1
    assert result["total"] == 1


def test_coverage_not_found_at_40_pct():
    # owner [0,5] = 5s, gate [3,8] = 5s, overlap = 2s → 2/5 = 40% of shorter → not found
    owner = [_owner_reel("o1", 0.0, 5.0)]
    gate = [_gate_reel("g1", 3.0, 8.0)]
    result = coverage(owner, gate)
    assert result["found"] == 0
    assert result["total"] == 1


def test_coverage_found_at_60_pct_asymmetric():
    # owner [0,5] = 5s, gate [2,8] = 6s, overlap = 3s → 3/5 = 60% of shorter → found
    owner = [_owner_reel("o1", 0.0, 5.0)]
    gate = [_gate_reel("g1", 2.0, 8.0)]
    result = coverage(owner, gate)
    assert result["found"] == 1


def test_coverage_gate_clip_not_counted_twice():
    # One gate clip that overlaps both owner clips
    owner = [_owner_reel("o1", 0.0, 10.0), _owner_reel("o2", 5.0, 15.0)]
    gate = [_gate_reel("g1", 0.0, 10.0)]   # fully covers o1, 50% of o2
    result = coverage(owner, gate)
    # g1 can only match one owner clip (greedy by best overlap)
    assert result["found"] == 1
    assert result["total"] == 2


def test_coverage_reports_missed_and_best():
    # owner[0] found at 60%, owner[1] best 30% (not found)
    # gate[0] covers owner[0] at 60%, gate[1] covers owner[1] at 30%
    owner = [_owner_reel("o1", 0.0, 5.0), _owner_reel("o2", 10.0, 20.0)]
    gate = [_gate_reel("g0", 2.0, 8.0), _gate_reel("g1", 13.0, 16.0)]
    # o1 [0,5]=5s, g0 [2,8]=6s, overlap [2,5]=3s → 3/5=60% → found
    # o2 [10,20]=10s, g1 [13,16]=3s, overlap [13,16]=3s → 3/3=100%... wait
    # Let me recalculate: g1 [13,16]=3s, o2 [10,20]=10s, overlap=3s, shorter=3 → 100% found
    # Need to adjust: o2=[10,20]=10s, g1=[15,18]=3s, overlap=3s, shorter=3 → 100% found
    # Use: o2=[10,20]=10s, g1=[17,20]=3s, overlap=3s, shorter=3 → 100% found
    # Let me just test the structure with a clear 30% case:
    # o1=[0,10]=10s, g0=[0,3]=3s overlap=3, shorter=3 → 100% found; o2=[20,30]=10s, g1=[23,26]=3s → 100% found
    # For 30%: owner=[0,10]=10s, gate=[7,10]=3s, overlap=3, shorter=3 → 100%
    # I need: overlap < 50% of shorter. E.g. owner=[0,10], gate=[8,11]=3s, overlap=2s, shorter=3s → 67% found.
    # For 30%: owner=[0,10], gate=[9,12]=3s, overlap=1s, shorter=3s → 33% < 50% → not found, best=33%
    owner2 = [_owner_reel("o1", 0.0, 5.0), _owner_reel("o2", 0.0, 10.0)]
    gate2 = [_gate_reel("g0", 2.0, 8.0), _gate_reel("g1", 7.0, 10.0)]
    # o1=[0,5]=5s, g0=[2,8]=6s, overlap=[2,5]=3s, shorter=5 → 60% found
    # o2=[0,10]=10s, g1=[7,10]=3s, overlap=[7,10]=3s, shorter=3 → 100% found... g0 already used
    # Actually g0 shorter=5 → 3/5=60% → found; g1 for o2: 3/3=100% → also found
    # This doesn't test missed. Let me use a simple case:
    owner3 = [_owner_reel("o1", 0.0, 5.0), _owner_reel("o2", 20.0, 30.0)]
    gate3 = [_gate_reel("g0", 2.0, 8.0), _gate_reel("g1", 29.0, 33.0)]
    # o1=[0,5]=5s, g0=[2,8]=6s, overlap=3s, shorter=5 → 60% → found
    # o2=[20,30]=10s, g1=[29,33]=4s, overlap=1s, shorter=4 → 25% → NOT found
    result3 = coverage(owner3, gate3)
    assert result3["found"] == 1
    assert result3["total"] == 2
    assert 1 in result3["missed"]
    assert result3["matched"][0][0] == 0   # owner index 0 found
    # best for owner[1]: g1 gave 25% overlap
    assert result3["best"][1][0] is not None
    assert abs(result3["best"][1][1] - 0.25) < 0.05


def test_coverage_best_none_without_overlap():
    owner = [_owner_reel("o1", 0.0, 5.0)]
    gate = [_gate_reel("g1", 10.0, 15.0)]  # no overlap
    result = coverage(owner, gate)
    assert result["best"][0] == [None, 0.0]
    assert 0 in result["missed"]


# ── 6. units ─────────────────────────────────────────────────────────────────

def _unit(t0, t1, role="thesis", punch=3, topic=1):
    return {"t0": t0, "t1": t1, "role": role, "punch": punch, "topic": topic,
            "text": "тест текст слова мысли фраза"}


def test_units_40_pct_not_included():
    # unit [0, 10], segment covers [0, 4] → 4/10 = 40% < 50% → excluded
    segs = [_seg(0.0, 4.0)]
    r = _reel(0.0, 4.0, segments=segs)
    map_ = {"units": [_unit(0.0, 10.0)]}
    c = score_clip(r, map_, {}, _cfg())
    assert len(c["units"]) == 0


def test_units_50_pct_included():
    # unit [0, 10], segment [0, 5] → 5/10 = 50% → included
    segs = [_seg(0.0, 5.0)]
    r = _reel(0.0, 5.0, segments=segs)
    map_ = {"units": [_unit(0.0, 10.0)]}
    c = score_clip(r, map_, {}, _cfg())
    assert len(c["units"]) == 1


def test_units_order_by_playback_with_reorder():
    # Two segments reordered: seg1=[20,30], seg2=[5,15]
    # unit_a=[5,15], unit_b=[20,30]
    # playback: seg1 plays first (out_time 0), seg2 plays second (out_time 10)
    # seg1 covers unit_b, seg2 covers unit_a → playback order: unit_b, unit_a
    segs = [_seg(20.0, 30.0), _seg(5.0, 15.0)]
    r = _reel(5.0, 30.0, segments=segs)
    map_ = {"units": [_unit(5.0, 15.0, role="question"), _unit(20.0, 30.0, role="thesis")]}
    c = score_clip(r, map_, {}, _cfg())
    assert len(c["units"]) == 2
    # first unit in playback should be thesis (covered by seg1 which plays first)
    assert c["units"][0]["role"] == "thesis"
    assert c["units"][1]["role"] == "question"


# ── 7. closure ────────────────────────────────────────────────────────────────

def test_closure_common_stems():
    # "страхи мешают жить" and "без страха жить легче" share "страх" (5+ letters) and "жить"
    segs = [_seg(0.0, 5.0), _seg(10.0, 15.0)]
    r = _reel(0.0, 15.0, segments=segs)
    unit1 = {"t0": 0.0, "t1": 5.0, "role": "thesis", "punch": 3, "topic": 1,
              "text": "страхи мешают жить"}
    unit2 = {"t0": 10.0, "t1": 15.0, "role": "conclusion", "punch": 3, "topic": 1,
              "text": "без страха жить легче"}
    map_ = {"units": [unit1, unit2]}
    c = score_clip(r, map_, {}, _cfg())
    assert c["closure"] is not None and c["closure"] >= 1


def test_closure_none_single_unit():
    segs = [_seg(0.0, 10.0)]
    r = _reel(0.0, 10.0, segments=segs)
    map_ = {"units": [{"t0": 0.0, "t1": 10.0, "role": "thesis", "punch": 3, "topic": 1,
                       "text": "одна мысль здесь"}]}
    c = score_clip(r, map_, {}, _cfg())
    assert c["closure"] is None


# ── 8. short_shots and slivers ────────────────────────────────────────────────

def test_short_shots_matches_measure_shots():
    # Segment with close_intervals creates shots
    # close_intervals = [(1.0, 3.0)] inside a 5s segment → 3 shots: [0,1], [1,3], [3,5]
    # [0,1] = 1.0s → short (< 2.0s), [1,3] = 2.0s → not short, [3,5] = 2.0s = last → not counted
    segs = [_seg(10.0, 15.0, close_intervals=[(1.0, 3.0)])]
    r = _reel(10.0, 15.0, segments=segs)
    c = score_clip(r, {}, {}, _cfg(short_shot_sec=2.0))
    # shots: (0,1) short, (1,3) ok, (3,5) last → 1 short
    assert c["short_shots"] == 1
    assert c["slivers"] == 0


def test_slivers_detected():
    # close_intervals creates a 0.1s sliver
    segs = [_seg(10.0, 15.0, close_intervals=[(0.1, 0.2)])]
    r = _reel(10.0, 15.0, segments=segs)
    c = score_clip(r, {}, {}, _cfg(short_shot_sec=2.0))
    assert c["slivers"] >= 1


def test_cold_open_shots_not_counted():
    # cold_open only → no shots counted (excluded)
    co = _co(0.0, 1.0)
    r = _reel(5.0, 10.0, cold_open=co)
    c = score_clip(r, {}, {}, _cfg(short_shot_sec=2.0))
    assert c["short_shots"] == 0


# ── summarize ─────────────────────────────────────────────────────────────────

def test_summarize_basic():
    clips = [
        {"dur": 30.0, "hook": True, "start_backref": "«И…»", "start_short": False,
         "end_tone": "open", "seams": 1, "cuts": 0, "back_jumps": 0,
         "short_shots": 0, "slivers": 0, "open_role": True, "close_role": False,
         "topics": 1, "closure": 2, "punch_mean": 3.0,
         "warnings": {"montage": 1}, "units": []},
        {"dur": 20.0, "hook": False, "start_backref": None, "start_short": True,
         "end_tone": "final", "seams": 0, "cuts": 1, "back_jumps": 0,
         "short_shots": 1, "slivers": 0, "open_role": False, "close_role": True,
         "topics": 2, "closure": 0, "punch_mean": 2.0,
         "warnings": {}, "units": []},
    ]
    s = summarize(clips)
    assert s["n"] == 2
    assert abs(s["hook_pct"] - 50.0) < 0.1
    assert abs(s["start_backref_pct"] - 50.0) < 0.1
    assert abs(s["end_open_pct"] - 50.0) < 0.1
    assert s["back_jumps"] == 0


# ── verdicts ──────────────────────────────────────────────────────────────────

def test_verdicts_counts():
    rows = [
        {"gate": "m183", "verdict": "good", "reasons": ["hook_ok"], "stem": "s1"},
        {"gate": "m183", "verdict": "bad", "reasons": ["no_hook", "start_weak"], "stem": "s1"},
        {"gate": "m176", "verdict": "good", "reasons": [], "stem": "s2"},
    ]
    v = verdicts(rows, "m183")
    assert v["total_rows"] == 3
    assert v["by_verdict"]["good"] == 1
    assert v["by_verdict"]["bad"] == 1
    assert v["by_reason"]["no_hook"] == 1
    assert v["by_reason"]["start_weak"] == 1
    # m176 row not included in by_verdict, but total_rows covers all
    assert "good" not in v["by_verdict"] or v["by_verdict"].get("good") == 1
