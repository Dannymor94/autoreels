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

SPEECHMAP_VERSION = "6"

# Defaults — all overridable by callers or future config.
DEFAULT_FRAME_SEC = 0.01         # 10 ms energy window
DEFAULT_NOISE_PERCENTILE = 10    # noise floor = 10th-pct of frame energies
DEFAULT_HEADROOM_DB = 15.0       # threshold = noise_floor + headroom_db
DEFAULT_MIN_SILENCE_SEC = 0.05   # minimum silence to split intervals in the map
DEFAULT_PAUSE_MIN_SEC = 0.15     # minimum pause to count as a word boundary
DEFAULT_WORD_EPSILON = 0.05      # ±ε search window around Whisper timestamps

# ── boundary pause constants ─────────────────────────────────────────────────
_MIN_SPEECH_DUR = 0.020   # speech intervals shorter than this are treated as noise

# Defaults — also exposed in SpeechMapConfig (config.py); kept here as module fallbacks.
_MIN_EDGE_DIST = 0.060    # interval within 60 ms of a word edge → word residue, not untranscribed
_UNTRANSCRIBED_MIN_SEC = 0.100  # minimum duration for a detached interval to count

# Consumers must use this threshold for pause-based cut decisions, never raw pause > 0.
# Rationale: voiceless stop closures (e.g. "т" in "такая?") produce genuine energy gaps
# of ~0.3 s that are continuous speech by ear — see regression case #568 (0.29 s).
# Default also exposed in SpeechMapConfig.cut_pause_min_sec.
CUT_PAUSE_MIN_SEC: float = 0.35


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

        # Overlapping Whisper timestamps: next word's t0 < this word's t0, inverting the
        # search window (search_end < win_start). Normal frag collection would yield ae < t0.
        # Fix: use the speech interval containing the word's midpoint (or t0 as fallback).
        if search_end <= win_start:
            ref_t = (w.t0 + w.t1) / 2
            c_on, c_off = next(
                ((on, off) for on, off in intervals if on <= ref_t <= off),
                next(((on, off) for on, off in intervals if on <= w.t0 <= off),
                     (w.t0, w.t1)),  # last resort: Whisper bounds
            )
            prev_ae = refined[-1]["audible_end"] if refined else 0.0
            as_ = max(c_on, prev_ae + epsilon, w.t0 - epsilon)
            ae = max(min(c_off, w.t1 + epsilon), as_)
            if ae <= w.t0:
                ae = w.t1  # absolute fallback: Whisper t1 is always > t0
            refined.append({"idx": idx, "t0": w.t0, "t1": w.t1,
                            "audible_start": as_, "audible_end": ae})
            continue

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
        if audible_end <= w.t0:
            # Near-inverted window or interval ends before word onset — same midpoint fix.
            ref_t = (w.t0 + w.t1) / 2
            c_on, c_off = next(
                ((on, off) for on, off in intervals if on <= ref_t <= off),
                next(((on, off) for on, off in intervals if on <= w.t0 <= off), (w.t0, w.t1)),
            )
            prev_ae = refined[-1]["audible_end"] if refined else 0.0
            as_ = max(c_on, prev_ae + epsilon, w.t0 - epsilon)
            ae = max(min(c_off, w.t1 + epsilon), as_)
            if ae <= w.t0:
                ae = w.t1
            refined.append({"idx": idx, "t0": w.t0, "t1": w.t1,
                            "audible_start": as_, "audible_end": ae})
            continue
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
    min_edge_dist: float = _MIN_EDGE_DIST,
    untranscribed_min_sec: float = _UNTRANSCRIBED_MIN_SEC,
) -> str:
    s = json.dumps({
        "frame_sec": frame_sec,
        "noise_percentile": noise_percentile,
        "headroom_db": headroom_db,
        "min_silence_sec": min_silence_sec,
        "pause_min_sec": pause_min_sec,
        "min_edge_dist": min_edge_dist,
        "untranscribed_min_sec": untranscribed_min_sec,
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
    min_edge_dist: float = _MIN_EDGE_DIST,
    untranscribed_min_sec: float = _UNTRANSCRIBED_MIN_SEC,
) -> dict:
    """Build the speech map (or load cached) and return the map dict.

    Cache hit: out_path exists and its params_hash + source_sha256 + version match.
    Cache miss: extract PCM, compute energy, refine words, write out_path.
    """
    ph = _params_hash(
        frame_sec=frame_sec, noise_percentile=noise_percentile,
        headroom_db=headroom_db, min_silence_sec=min_silence_sec,
        pause_min_sec=pause_min_sec,
        min_edge_dist=min_edge_dist, untranscribed_min_sec=untranscribed_min_sec,
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

    boundaries = boundary_pauses(word_entries, intervals,
                                 min_edge_dist=min_edge_dist,
                                 untranscribed_min_sec=untranscribed_min_sec)

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
        "boundaries": boundaries,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


# ── boundary pause stats ─────────────────────────────────────────────────────


def _gap_analysis(
    ae: float,
    as_: float,
    intervals: list[list[float]],
    *,
    min_edge_dist: float = _MIN_EDGE_DIST,
    untranscribed_min_sec: float = _UNTRANSCRIBED_MIN_SEC,
) -> tuple[float, list[list[float]]]:
    """Analyse gap [ae, as_] using speech intervals.

    Returns (pause, untranscribed_speech).
    pause = trailing silence: silence from the end of the last significant speech
    interval (≥ _MIN_SPEECH_DUR) to as_.  Measures the silence immediately before
    the next word — the only stretch where a cut is actually possible.
    untranscribed_speech: detached intervals only — those at least min_edge_dist
    from both word edges and at least untranscribed_min_sec long.  Intervals
    closer than min_edge_dist to ae or as_ are word residue (vowel tail, breath)
    and are silently dropped.

    If no significant speech in the gap, pause = full gap length.
    """
    if as_ <= ae:
        return 0.0, []
    gap = as_ - ae

    speech_in_gap: list[list[float]] = []
    for onset, offset in intervals:
        if offset <= ae:
            continue
        if onset >= as_:
            break
        clipped = [max(onset, ae), min(offset, as_)]
        if clipped[1] > clipped[0]:
            speech_in_gap.append(clipped)

    if not speech_in_gap:
        return gap, []

    # Find the last significant speech interval; ignore noise blips.
    last_significant_end: float | None = None
    for seg in reversed(speech_in_gap):
        if seg[1] - seg[0] >= _MIN_SPEECH_DUR:
            last_significant_end = seg[1]
            break

    if last_significant_end is None:
        pause = gap
    else:
        pause = max(0.0, as_ - last_significant_end)

    # untranscribed_speech: keep only detached, substantive intervals.
    untranscribed = [
        seg for seg in speech_in_gap
        if (seg[0] - ae) >= min_edge_dist
        and (as_ - seg[1]) >= min_edge_dist
        and (seg[1] - seg[0]) >= untranscribed_min_sec
    ]
    return pause, untranscribed


def boundary_pauses(
    words_refined: list[dict],
    intervals: list[list[float]],
    *,
    min_edge_dist: float = _MIN_EDGE_DIST,
    untranscribed_min_sec: float = _UNTRANSCRIBED_MIN_SEC,
) -> list[dict]:
    """Compute boundary pauses between consecutive words using speech intervals.

    pause = trailing silence: silence from end of last significant speech to as(w+1).
    untranscribed_speech = speech intervals inside the gap (energy, no Whisper word).
    Returns N-1 dicts for N words.
    """
    result: list[dict] = []
    for i in range(len(words_refined) - 1):
        ae = words_refined[i]["audible_end"]
        as_ = words_refined[i + 1]["audible_start"]
        pause, untr = _gap_analysis(ae, as_, intervals,
                                    min_edge_dist=min_edge_dist,
                                    untranscribed_min_sec=untranscribed_min_sec)
        result.append({
            "pause": round(pause, 4),
            "untranscribed_speech": [[round(a, 4), round(b, 4)] for a, b in untr],
        })
    return result


def whisper_gaps(transcript_words: list[Any]) -> list[float]:
    """Whisper-gap baseline: t0(w+1) - t1(w) for consecutive words."""
    return [transcript_words[i + 1].t0 - transcript_words[i].t1
            for i in range(len(transcript_words) - 1)]
