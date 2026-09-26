"""M1.8 Stage A: per-source speech map from audio energy.

Replaces Whisper-gap heuristics for pause/word-edge detection.
Stage A: build and cache the map only. No consumers yet (flag speech_map=false).

Cache key: source_sha256 + params_hash + SPEECHMAP_VERSION.
Artifact: transcripts/<stem>.speechmap.json
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

SPEECHMAP_VERSION = "1"

# Defaults — all overridable by callers or future config.
DEFAULT_FRAME_SEC = 0.01         # 10 ms energy window
DEFAULT_NOISE_PERCENTILE = 10    # noise floor = 10th-pct of frame energies
DEFAULT_HEADROOM_DB = 15.0       # threshold = noise_floor + headroom_db
DEFAULT_MIN_SILENCE_SEC = 0.05   # minimum silence to split intervals in the map
DEFAULT_PAUSE_MIN_SEC = 0.15     # minimum pause to count as a word boundary
DEFAULT_WORD_EPSILON = 0.05      # ±ε search window around Whisper timestamps


# ── audio extraction ─────────────────────────────────────────────────────────

def extract_pcm(source: Path, ffmpeg: str = "ffmpeg") -> tuple[np.ndarray, int]:
    """Extract mono 16 kHz float32 PCM from video/audio via ffmpeg pipe."""
    sr = 16000
    cmd = [
        ffmpeg, "-i", str(source), "-vn",
        "-ac", "1", "-ar", str(sr),
        "-f", "f32le", "pipe:1",
        "-loglevel", "error",
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg PCM extraction failed for {source}: "
            f"{result.stderr.decode('utf-8', errors='replace')[:400]}"
        )
    samples = np.frombuffer(result.stdout, dtype=np.float32).copy()
    return samples, sr


# ── energy and intervals ─────────────────────────────────────────────────────

def frame_energies_db(
    samples: np.ndarray,
    sr: int,
    frame_sec: float = DEFAULT_FRAME_SEC,
) -> np.ndarray:
    """Compute per-frame RMS energy in dBFS (vectorised). Returns float32 array."""
    frame_size = max(1, int(sr * frame_sec))
    n = len(samples) // frame_size
    if n == 0:
        return np.array([], dtype=np.float32)
    frames = samples[:n * frame_size].reshape(n, frame_size)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    return (20.0 * np.log10(np.maximum(rms, 1e-10))).astype(np.float32)


def build_speech_intervals(
    samples: np.ndarray,
    sr: int,
    *,
    frame_sec: float = DEFAULT_FRAME_SEC,
    noise_percentile: float = DEFAULT_NOISE_PERCENTILE,
    headroom_db: float = DEFAULT_HEADROOM_DB,
    min_silence_sec: float = DEFAULT_MIN_SILENCE_SEC,
) -> tuple[list[list[float]], float, float]:
    """Detect speech intervals from energy.

    Returns (intervals, noise_floor_db, threshold_db).
    Each interval = [onset_sec, offset_sec].
    """
    energies = frame_energies_db(samples, sr, frame_sec)
    if len(energies) == 0:
        return [], -60.0, -60.0 + headroom_db

    noise_floor = float(np.percentile(energies, noise_percentile))
    threshold = noise_floor + headroom_db
    speech_mask = energies >= threshold

    intervals = _merge_speech_mask(speech_mask, frame_sec, min_silence_sec)
    return intervals, noise_floor, threshold


def _merge_speech_mask(
    speech_mask: np.ndarray,
    frame_sec: float,
    min_silence_sec: float,
) -> list[list[float]]:
    """Convert a boolean frame mask into merged [onset, offset] intervals (seconds)."""
    min_gap_frames = max(1, round(min_silence_sec / frame_sec))
    n = len(speech_mask)
    if n == 0:
        return []

    intervals: list[list[float]] = []
    in_speech = False
    start = 0
    i = 0
    while i < n:
        if not in_speech:
            if speech_mask[i]:
                start = i
                in_speech = True
        else:
            if not speech_mask[i]:
                # look ahead: is the gap short enough to bridge?
                gap_start = i
                while i < n and not speech_mask[i]:
                    i += 1
                gap_len = i - gap_start
                if gap_len < min_gap_frames and i < n:
                    # bridge: stay in speech
                    continue
                # real silence: close interval
                intervals.append([start * frame_sec, gap_start * frame_sec])
                in_speech = False
                continue
        i += 1

    if in_speech:
        intervals.append([start * frame_sec, n * frame_sec])

    return intervals


# ── word boundary refinement ─────────────────────────────────────────────────

def refine_word_boundaries(
    words: list[Any],
    intervals: list[list[float]],
    *,
    pause_min_sec: float = DEFAULT_PAUSE_MIN_SEC,
    epsilon: float = DEFAULT_WORD_EPSILON,
) -> list[dict]:
    """Find audible_start/audible_end for each word from speech intervals.

    audible_start looks back past win_start when a preceding Whisper-bloated word
    hid the real speech onset: if the interval containing w.t0 started earlier than
    t0-epsilon (i.e. was clamped), we use the actual onset bounded by prev_ae+epsilon.
    Stop-consonant rule: bridge gaps < pause_min_sec only when the gap does not
    straddle a Whisper word boundary (w.t1 or next_t0).
    """
    refined: list[dict] = []
    for idx, w in enumerate(words):
        next_t0 = words[idx + 1].t0 if idx + 1 < len(words) else w.t1 + 1.0
        search_end = min(next_t0 + epsilon, w.t1 + 1.5)
        win_start = max(0.0, w.t0 - epsilon)

        # Each frag: (clamped_onset, offset, original_onset)
        frags: list[tuple[float, float, float]] = []
        for onset, offset in intervals:
            if offset <= win_start:
                continue
            if onset >= search_end:
                break
            frags.append((max(onset, win_start), min(offset, search_end), onset))

        if not frags:
            # No energy near this word — fall back to Whisper timestamps
            refined.append({
                "idx": idx, "t0": w.t0, "t1": w.t1,
                "audible_start": w.t0, "audible_end": w.t1,
            })
            continue

        # audible_start: use actual interval onset when the interval was clamped at
        # win_start (Whisper bloated prev word, real speech started before t0-epsilon).
        clamped_onset, frag_offset, orig_onset = frags[0]
        if orig_onset < win_start:
            # Interval straddles win_start — find the earliest position that is
            # still past the previous word's audible end.
            lower_bound = refined[-1]["audible_end"] + epsilon if refined else 0.0
            candidate = max(orig_onset, lower_bound)
            # Only use it if the candidate still falls within the speech region
            audible_start = candidate if candidate < frag_offset else clamped_onset
        else:
            audible_start = clamped_onset

        # audible_end: bridge gaps inside the word span; stop at word boundaries
        audible_end = frags[0][1]
        for i, (onset, offset, _) in enumerate(frags[1:], start=1):
            gap_start_t = frags[i - 1][1]
            gap = onset - gap_start_t
            at_boundary = (gap_start_t <= w.t1 <= onset) or (gap_start_t <= next_t0 <= onset)
            if not at_boundary and gap < pause_min_sec:
                audible_end = offset
            else:
                break

        refined.append({
            "idx": idx, "t0": w.t0, "t1": w.t1,
            "audible_start": audible_start,
            "audible_end": audible_end,
        })

    return refined


# ── cache key ────────────────────────────────────────────────────────────────

def _params_hash(
    *,
    frame_sec: float,
    noise_percentile: float,
    headroom_db: float,
    min_silence_sec: float,
    pause_min_sec: float,
) -> str:
    s = json.dumps({
        "frame_sec": frame_sec,
        "noise_percentile": noise_percentile,
        "headroom_db": headroom_db,
        "min_silence_sec": min_silence_sec,
        "pause_min_sec": pause_min_sec,
        "version": SPEECHMAP_VERSION,
    }, sort_keys=True)
    return hashlib.sha256(s.encode()).hexdigest()[:16]


# ── main entry point ─────────────────────────────────────────────────────────

def build_or_load(
    source: Path,
    source_sha256: str,
    words: list[Any],
    out_path: Path,
    *,
    ffmpeg: str = "ffmpeg",
    frame_sec: float = DEFAULT_FRAME_SEC,
    noise_percentile: float = DEFAULT_NOISE_PERCENTILE,
    headroom_db: float = DEFAULT_HEADROOM_DB,
    min_silence_sec: float = DEFAULT_MIN_SILENCE_SEC,
    pause_min_sec: float = DEFAULT_PAUSE_MIN_SEC,
    epsilon: float = DEFAULT_WORD_EPSILON,
) -> dict:
    """Build the speech map (or load cached) and return the map dict.

    Cache hit: out_path exists and its params_hash + source_sha256 + version match.
    Cache miss: extract PCM, compute energy, refine words, write out_path.
    """
    ph = _params_hash(
        frame_sec=frame_sec, noise_percentile=noise_percentile,
        headroom_db=headroom_db, min_silence_sec=min_silence_sec,
        pause_min_sec=pause_min_sec,
    )

    if out_path.is_file():
        try:
            cached = json.loads(out_path.read_text(encoding="utf-8"))
            if (cached.get("source_sha256") == source_sha256
                    and cached.get("params_hash") == ph
                    and cached.get("version") == SPEECHMAP_VERSION):
                return cached
        except (json.JSONDecodeError, KeyError):
            pass

    samples, sr = extract_pcm(source, ffmpeg=ffmpeg)
    intervals, noise_floor, threshold = build_speech_intervals(
        samples, sr,
        frame_sec=frame_sec, noise_percentile=noise_percentile,
        headroom_db=headroom_db, min_silence_sec=min_silence_sec,
    )

    word_entries = refine_word_boundaries(
        words, intervals, pause_min_sec=pause_min_sec, epsilon=epsilon,
    )

    result: dict = {
        "version": SPEECHMAP_VERSION,
        "source_sha256": source_sha256,
        "params_hash": ph,
        "frame_sec": frame_sec,
        "noise_floor_db": round(noise_floor, 2),
        "threshold_db": round(threshold, 2),
        "duration_sec": round(len(samples) / sr, 3),
        "n_intervals": len(intervals),
        "intervals": [[round(a, 4), round(b, 4)] for a, b in intervals],
        "words": word_entries,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


# ── boundary pause stats ─────────────────────────────────────────────────────

def boundary_pauses(words_refined: list[dict], transcript_words: list[Any]) -> list[float]:
    """Compute boundary pauses (seconds) between consecutive words.

    Boundary pause = max(0, audible_start(w+1) - audible_end(w)).
    Returns a list of N-1 values for N words.
    """
    pauses = []
    for i in range(len(words_refined) - 1):
        end = words_refined[i]["audible_end"]
        start = words_refined[i + 1]["audible_start"]
        pauses.append(max(0.0, start - end))
    return pauses


def whisper_gaps(transcript_words: list[Any]) -> list[float]:
    """Whisper-gap baseline: t0(w+1) - t1(w) for consecutive words."""
    return [transcript_words[i + 1].t0 - transcript_words[i].t1
            for i in range(len(transcript_words) - 1)]
