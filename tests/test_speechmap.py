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
    SPEECHMAP_VERSION,
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
    """boundary_pauses() clips negatives to 0."""
    samples, sr = _make_audio()
    intervals, _, _ = build_speech_intervals(samples, sr)
    words = _words((0.0, 0.5), (0.7, 1.2), (1.27, 1.77), (2.07, 2.57))
    refined = refine_word_boundaries(words, intervals)
    pauses = boundary_pauses(refined, words)
    assert all(p >= 0.0 for p in pauses)


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
                min_silence_sec=0.05, pause_min_sec=0.15)
    h0 = _params_hash(**base)
    for key, new_val in [("frame_sec", 0.02), ("noise_percentile", 20),
                          ("headroom_db", 16.0), ("min_silence_sec", 0.1),
                          ("pause_min_sec", 0.2)]:
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

    hash_val = ph(frame_sec=DEFAULT_FRAME_SEC, noise_percentile=DEFAULT_NOISE_PERCENTILE,
                  headroom_db=DEFAULT_HEADROOM_DB, min_silence_sec=DEFAULT_MIN_SILENCE_SEC,
                  pause_min_sec=DEFAULT_PAUSE_MIN_SEC)
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
