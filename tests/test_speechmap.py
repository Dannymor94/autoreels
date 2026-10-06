"""M1.8 Stage A: unit tests for speech map (energy-based VAD + word refinement).

Synthetic audio keeps tests hermetic — no real sources, no fixtures in git.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from autoreels.cloud.speechmap import (
    CUT_PAUSE_MIN_SEC,
    SPEECHMAP_VERSION,
    _gap_analysis,
    _merge_speech_mask,
    _params_hash,
    boundary_pauses,
    build_speech_intervals,
    frame_energies_db,
    refine_word_boundaries,
    whisper_gaps,
)


# ── synthetic audio helper ──────────────────────────────────────────────────

def _make_audio(sr: int = 16000) -> tuple[np.ndarray, int]:
    """Create 3-second synthetic audio with known silence/speech pattern.

    Pattern (seconds):
      0.0–0.5   speech A
      0.5–0.7   silence (0.2s — real gap, > pause_min_sec=0.15)
      0.7–1.2   speech B
      1.2–1.27  closure (0.07s — stop consonant, < pause_min_sec=0.15)
      1.27–1.77 speech C
      1.77–2.07 silence (0.3s — real boundary pause, >= pause_min_sec)
      2.07–2.57 speech D
      2.57–3.0  silence (tail)
    """
    rng = np.random.default_rng(42)
    samples = rng.standard_normal(sr * 3).astype(np.float32) * 1e-4  # -80 dBFS noise

    def _add(t0: float, t1: float, amp: float = 0.3) -> None:
        s, e = int(t0 * sr), int(t1 * sr)
        t = np.linspace(0, (t1 - t0) * 440 * 2 * np.pi, e - s, dtype=np.float32)
        samples[s:e] += np.sin(t) * amp

    _add(0.0, 0.5)
    _add(0.7, 1.2)
    _add(1.27, 1.77)
    _add(2.07, 2.57)
    return samples, sr


def _words(*pairs) -> list:
    """Build a list of fake Word-like objects from (t0, t1) pairs."""
    return [SimpleNamespace(word=f"w{i}", t0=t0, t1=t1)
            for i, (t0, t1) in enumerate(pairs)]


# ── basic energy ────────────────────────────────────────────────────────────

def test_frame_energies_shape():
    samples, sr = _make_audio()
    en = frame_energies_db(samples, sr, frame_sec=0.01)
    expected_frames = len(samples) // int(sr * 0.01)
    assert len(en) == expected_frames
    assert en.dtype == np.float32


def test_noise_frames_well_below_speech_frames():
    samples, sr = _make_audio()
    en = frame_energies_db(samples, sr, frame_sec=0.01)
    # Speech frames (t=0–0.5 → indices 0–49) should be much louder than noise frames (t=0.6–0.7)
    speech_idx = slice(0, 50)
    noise_idx = slice(60, 70)
    assert en[speech_idx].mean() > en[noise_idx].mean() + 20  # >= 20 dB separation


# ── interval detection ───────────────────────────────────────────────────────

def test_speech_intervals_splits_real_gaps():
    """Gaps >= 0.2s (> min_silence_sec=0.05) produce separate intervals."""
    samples, sr = _make_audio()
    intervals, noise_floor, threshold = build_speech_intervals(
        samples, sr, min_silence_sec=0.05)
    # With min_silence=0.05: 0.2s silence and 0.07s closure both split
    # → intervals: A / B / C / D (4 intervals)
    assert len(intervals) == 4
    # First interval starts near 0.0
    assert abs(intervals[0][0]) < 0.06
    # Interval D starts near 2.07
    assert abs(intervals[3][0] - 2.07) < 0.08


def test_noise_floor_and_threshold_reasonable():
    samples, sr = _make_audio()
    _, noise_floor, threshold = build_speech_intervals(samples, sr)
    assert noise_floor < -50.0        # background is quiet
    assert threshold < -30.0          # threshold is above noise but below speech
    assert threshold > noise_floor    # threshold is always above noise floor


def test_empty_audio_returns_empty():
    samples = np.zeros(0, dtype=np.float32)
    intervals, nf, th = build_speech_intervals(samples, 16000)
    assert intervals == []


# ── _merge_speech_mask ───────────────────────────────────────────────────────

def test_merge_bridges_short_gap():
    """A gap shorter than min_silence_sec is bridged, not split."""
    mask = np.array([True, True, False, True, True], dtype=bool)  # gap at idx=2 (0.01s)
    result = _merge_speech_mask(mask, frame_sec=0.01, min_silence_sec=0.05)
    assert len(result) == 1
    assert abs(result[0][0]) < 1e-9
    assert abs(result[0][1] - 0.05) < 1e-9


def test_merge_splits_long_gap():
    """A gap >= min_silence_sec produces two intervals."""
    # 5 silence frames at min_silence_sec=0.04 → gap=0.05 which is > 0.04 (4 frames)
    mask = np.array([True, True, False, False, False, False, False, True, True], dtype=bool)
    result = _merge_speech_mask(mask, frame_sec=0.01, min_silence_sec=0.04)
    assert len(result) == 2


# ── word boundary refinement ─────────────────────────────────────────────────

def test_stop_consonant_bridged_in_audible_end():
    """0.07s closure inside a word is bridged; audible_end extends past it."""
    samples, sr = _make_audio()
    intervals, _, _ = build_speech_intervals(samples, sr, min_silence_sec=0.05)
    # Fake word spanning B through C (the stop-consonant gap lives between them)
    words = _words((0.7, 1.77))  # one word that encompasses B + closure + C
    refined = refine_word_boundaries(words, intervals, pause_min_sec=0.15)
    # audible_end should be past 1.27 (not stuck at end of B at 1.2)
    assert refined[0]["audible_end"] > 1.5


def test_real_pause_is_word_boundary():
    """0.3s pause between words is >= pause_min_sec → word split is correct."""
    samples, sr = _make_audio()
    intervals, _, _ = build_speech_intervals(samples, sr, min_silence_sec=0.05)
    words = _words((1.27, 1.77), (2.07, 2.57))
    refined = refine_word_boundaries(words, intervals, pause_min_sec=0.15)
    pause = max(0.0, refined[1]["audible_start"] - refined[0]["audible_end"])
    assert pause >= 0.15  # 0.3s gap is a real boundary


def test_boundary_pause_never_negative():
    """boundary_pauses() returns non-negative pauses and untranscribed_speech lists."""
    samples, sr = _make_audio()
    intervals, _, _ = build_speech_intervals(samples, sr)
    words = _words((0.0, 0.5), (0.7, 1.2), (1.27, 1.77), (2.07, 2.57))
    refined = refine_word_boundaries(words, intervals)
    boundaries = boundary_pauses(refined, intervals)
    assert all(b["pause"] >= 0.0 for b in boundaries)
    assert all(isinstance(b["untranscribed_speech"], list) for b in boundaries)


def test_gap_analysis_trailing_silence_regression():
    """_gap_analysis regression: trailing silence, not longest silence.

    Three cases verified by ear on the 11h 42m 49s lecture:
    #69  поместить→в: untranscribed "а как бы" then pause → trailing silence (~0.8s)
    #81  Действуете,→думаете: untr "понятно" at END of gap → trailing ~0.07s (no pause)
    #201 ограничен.→Понятно?: speech IS the word, silence before it is real → trailing 0.63s
    """
    # #69-like: speech in middle of gap, silence after last speech
    # ae=0.0 as=2.0, speech [0.5-0.9] [1.0-1.3] [1.4-1.45], then silence 0.55s to as
    # [0.5-0.9] and [1.0-1.3] kept (dur>=0.10, edge>=60ms)
    # [1.4-1.45] dropped: dur=0.05s < _UNTRANSCRIBED_MIN_SEC=0.10s
    intervals_69 = [[0.5, 0.9], [1.0, 1.3], [1.4, 1.45]]
    pause_69, untr_69 = _gap_analysis(0.0, 2.0, intervals_69)
    # trailing silence from 1.45 to 2.0 = 0.55s (uses all speech for pause calc)
    assert 0.50 <= pause_69 <= 0.60, f"#69-like pause={pause_69}"
    assert len(untr_69) == 2, f"#69-like: tiny seg dropped, expect 2 kept, got {len(untr_69)}"

    # #81-like: untr speech at END of gap → tiny trailing silence
    # ae=0.0 as=1.0, silence [0, 0.45] speech [0.45-0.87] silence [0.87-1.0]=0.13s
    intervals_81 = [[0.45, 0.87]]
    pause_81, untr_81 = _gap_analysis(0.0, 1.0, intervals_81)
    assert pause_81 < 0.15, f"#81-like pause={pause_81} should be < pause_min_sec"
    assert len(untr_81) == 1

    # #201-like: speech in middle (the word itself), real silence before and after
    # ae=0.0 as=2.5, speech [1.13-1.84]=710ms, trailing=2.5-1.84=0.66s
    intervals_201 = [[1.13, 1.84]]
    pause_201, untr_201 = _gap_analysis(0.0, 2.5, intervals_201)
    assert 0.60 <= pause_201 <= 0.70, f"#201-like pause={pause_201}"
    assert len(untr_201) == 1

    # Noise blip: gap with only tiny speech (<20ms) → full gap returned, blip dropped from untr
    # dur=15ms < _UNTRANSCRIBED_MIN_SEC=100ms → not reported as untranscribed
    intervals_noise = [[0.5, 0.515]]  # 15ms < 20ms threshold
    pause_noise, untr_noise = _gap_analysis(0.0, 1.0, intervals_noise)
    assert pause_noise == pytest.approx(1.0), f"noise blip should not reduce gap: {pause_noise}"
    assert len(untr_noise) == 0, "noise blip < 100ms not reported in untranscribed_speech"


def test_cut_pause_min_sec_regression():
    """CUT_PAUSE_MIN_SEC > 0.29 so #568 (continuous speech, 0.29s gap) is not a cut point."""
    assert CUT_PAUSE_MIN_SEC > 0.29, f"#568 (0.29s) must be below cut threshold: {CUT_PAUSE_MIN_SEC}"
    assert CUT_PAUSE_MIN_SEC <= 0.5, "sanity: threshold should not exceed 0.5s"


def test_fallback_to_whisper_when_no_energy():
    """If there's no energy near a word, audible_start/end fall back to Whisper t0/t1."""
    silence = np.zeros(16000, dtype=np.float32)  # pure silence → no speech intervals
    intervals, _, _ = build_speech_intervals(silence, 16000)
    words = _words((0.1, 0.3), (0.5, 0.7))
    refined = refine_word_boundaries(words, intervals)
    assert refined[0]["audible_start"] == pytest.approx(0.1)
    assert refined[0]["audible_end"] == pytest.approx(0.3)


# ── cache invalidation ───────────────────────────────────────────────────────

def test_params_hash_changes_on_any_param():
    base = dict(frame_sec=0.01, noise_percentile=10, headroom_db=15.0,
                min_silence_sec=0.05, pause_min_sec=0.15,
                min_edge_dist=0.060, untranscribed_min_sec=0.100)
    h0 = _params_hash(**base)
    for key, new_val in [("frame_sec", 0.02), ("noise_percentile", 20),
                          ("headroom_db", 16.0), ("min_silence_sec", 0.1),
                          ("pause_min_sec", 0.2),
                          ("min_edge_dist", 0.080), ("untranscribed_min_sec", 0.150)]:
        params = {**base, key: new_val}
        assert _params_hash(**params) != h0, f"hash did not change when {key} changed"


def test_cache_hit_on_second_load(tmp_path):
    """build_or_load writes the map; second call returns cached without re-extracting."""
    from autoreels.cloud.speechmap import build_or_load

    # Write a pre-built map as the cache file
    samples, sr = _make_audio()
    intervals, noise_floor, threshold = build_speech_intervals(samples, sr)

    from autoreels.cloud.speechmap import _params_hash as ph
    from autoreels.cloud.speechmap import DEFAULT_FRAME_SEC, DEFAULT_HEADROOM_DB
    from autoreels.cloud.speechmap import DEFAULT_MIN_SILENCE_SEC, DEFAULT_NOISE_PERCENTILE
    from autoreels.cloud.speechmap import DEFAULT_PAUSE_MIN_SEC

    from autoreels.cloud.speechmap import _MIN_EDGE_DIST, _UNTRANSCRIBED_MIN_SEC
    hash_val = ph(frame_sec=DEFAULT_FRAME_SEC, noise_percentile=DEFAULT_NOISE_PERCENTILE,
                  headroom_db=DEFAULT_HEADROOM_DB, min_silence_sec=DEFAULT_MIN_SILENCE_SEC,
                  pause_min_sec=DEFAULT_PAUSE_MIN_SEC,
                  min_edge_dist=_MIN_EDGE_DIST, untranscribed_min_sec=_UNTRANSCRIBED_MIN_SEC)
    cached = {
        "version": SPEECHMAP_VERSION,
        "source_sha256": "deadbeef",
        "params_hash": hash_val,
        "intervals": intervals,
        "words": [],
        "n_intervals": len(intervals),
        "noise_floor_db": round(noise_floor, 2),
        "threshold_db": round(threshold, 2),
        "duration_sec": 3.0,
        "frame_sec": DEFAULT_FRAME_SEC,
    }
    cache_file = tmp_path / "test.speechmap.json"
    cache_file.write_text(json.dumps(cached))

    # Pass a non-existent source path — cache hit must not call ffmpeg
    result = build_or_load(
        source=Path("/nonexistent/source.mp4"),
        source_sha256="deadbeef",
        words=[],
        out_path=cache_file,
    )
    assert result["source_sha256"] == "deadbeef"
    assert result["params_hash"] == hash_val


def test_cache_miss_on_param_change(tmp_path):
    """Stale cache (different params_hash) is rejected."""
    cache_file = tmp_path / "test.speechmap.json"
    stale = {"version": SPEECHMAP_VERSION, "source_sha256": "abc", "params_hash": "stale000"}
    cache_file.write_text(json.dumps(stale))

    # Should raise (no real ffmpeg source) because stale cache is rejected
    with pytest.raises(Exception):
        from autoreels.cloud.speechmap import build_or_load
        build_or_load(source=Path("/no.mp4"), source_sha256="abc",
                      words=[], out_path=cache_file)


# ── whisper_gaps baseline ────────────────────────────────────────────────────

def test_whisper_gaps_can_be_negative():
    """Whisper gaps can be negative (overlapping timestamps) — that's the bug M1.8 fixes."""
    words = _words((0.0, 1.0), (0.9, 1.8))  # t1=1.0 > t0_next=0.9
    gaps = whisper_gaps(words)
    assert gaps[0] < 0.0


# ── PART 3: corrupted smap entries from overlapping timestamps ────────────────

def test_refine_word_boundaries_overlapping_timestamps_no_corrupt_ae():
    """PART 1: next_t0 < t0 (overlapping Whisper timestamps) → midpoint-based fallback.

    Inverted search window (search_end < win_start) previously produced ae < t0 (zero-length).
    Fix: find the interval containing the word midpoint; ae is derived from that interval.
    """
    # word1: t0=1.0, t1=1.5; word2: t0=0.8 (OVERLAPS — next_t0 < word1.t0)
    words = [SimpleNamespace(word="душе.", t0=1.0, t1=1.5),
             SimpleNamespace(word="next", t0=0.8, t1=1.2)]
    intervals = [[0.7, 1.8]]  # speech spans both words
    refined = refine_word_boundaries(words, intervals)
    w1 = refined[0]
    assert w1["audible_end"] > w1["t0"], (
        f"ae={w1['audible_end']:.3f} must be strictly > t0={w1['t0']:.3f}"
    )
    assert w1["audible_start"] <= w1["audible_end"], (
        f"as={w1['audible_start']:.3f} > ae={w1['audible_end']:.3f}"
    )


def test_refine_word_boundaries_overlapping_r03_dusha_case():
    """PART 1: real r03 'душе.' case — next_t0=378.143 < t0=378.483; ae must come from interval."""
    words = [
        SimpleNamespace(word="душе.", t0=378.483, t1=378.883),
        SimpleNamespace(word="Понятно?", t0=378.143, t1=379.163),  # inverts next_t0
    ]
    intervals = [[378.0, 379.3]]  # speech covering the overlapping region
    refined = refine_word_boundaries(words, intervals)
    w0 = refined[0]
    assert w0["audible_end"] > w0["t0"], (
        f"'душе.' ae={w0['audible_end']:.3f} must be > t0={w0['t0']:.3f} (not zero-length)"
    )
    # ae should come from the interval, not from the clamp (which would give t0=378.483)
    assert w0["audible_end"] > 378.6, (
        f"ae={w0['audible_end']:.3f} expected to come from interval, not from clamp"
    )


def test_no_zero_duration_when_c_off_before_lower_bound():
    """prev_ae + epsilon > c_off must not produce zero-duration entry."""
    # prev word's ae=100.0; curr word t0=100.0, t1=100.1
    # interval [99.92, 100.03] — c_off=100.03 < prev_ae+eps=100.05 → was zero-duration
    words = [
        SimpleNamespace(word="prev", t0=99.7, t1=100.0),
        SimpleNamespace(word="curr", t0=100.0, t1=100.1),
    ]
    intervals = [(99.7, 100.03)]
    result = refine_word_boundaries(words, intervals)
    for entry in result:
        assert entry["audible_end"] > entry["audible_start"] + 1e-6, (
            f"zero-duration at idx={entry['idx']}: "
            f"as={entry['audible_start']:.4f} ae={entry['audible_end']:.4f}"
        )
