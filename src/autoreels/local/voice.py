"""M50: how the voice sounds on a stretch of the source — loudness and pitch — for montage seams.

A montage joins speech from parts of a lecture far apart. Two things make such a seam audible even
when the words fit: the speaker is louder or quieter there (moved away from the microphone, spoke
to the room), or the voice sits higher or lower (excited vs calm). Measured on the played speech
next to the seam (a few seconds on each side):

  level_db   median RMS level (dBFS) of the 10 ms frames that carry speech — frames above the
             speech-map threshold (threshold_db of transcripts/<stem>.speechmap.json; without it
             frames within 30 dB of the loudest frame). Silences between words do not count.
  pitch_st   median pitch of the voiced frames in semitones relative to the speaker's median
             (ref_f0 of transcripts/<stem>.prosody.json; Praat pitch, as arl prosody).

Pure measure (`measure`) + a reader that cuts the stretch out of the source with ffmpeg (`meter`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

SR = 16000
FRAME = 0.01


@dataclass(frozen=True)
class Voice:
    level_db: float | None
    pitch_st: float | None


def level_db(x: np.ndarray, sr: int = SR, threshold_db: float | None = None) -> float | None:
    n = int(sr * FRAME)
    if len(x) < n:
        return None
    frames = np.asarray(x[: len(x) // n * n], dtype=np.float64).reshape(-1, n)
    db = 20.0 * np.log10(np.maximum(np.sqrt(np.mean(frames ** 2, axis=1)), 1e-10))
    floor = threshold_db if threshold_db is not None else float(db.max()) - 30.0
    speech = db[db > floor]
    return round(float(np.median(speech)), 1) if len(speech) >= 10 else None


def pitch_st(x: np.ndarray, ref_f0: float, sr: int = SR) -> float | None:
    try:
        import parselmouth
    except ImportError:  # pragma: no cover - analysis machine has it (arl prosody)
        return None
    if len(x) < sr // 2:
        return None
    p = parselmouth.Sound(np.asarray(x, dtype=np.float64), sampling_frequency=sr).to_pitch(
        time_step=FRAME, pitch_floor=60.0, pitch_ceiling=400.0)
    f0 = p.selected_array["frequency"]
    f0 = f0[f0 > 0]
    if len(f0) < 10:
        return None
    return round(float(12.0 * np.log2(np.median(f0) / ref_f0)), 1)


def measure(x: np.ndarray, *, ref_f0: float | None, threshold_db: float | None, sr: int = SR) -> Voice:
    return Voice(level_db(x, sr, threshold_db), pitch_st(x, ref_f0, sr) if ref_f0 else None)


def meter(read_audio: Callable[[float, float], np.ndarray], *, ref_f0: float | None,
          threshold_db: float | None) -> Callable[[float, float], Voice]:
    """(a, b) source seconds → Voice of that stretch. read_audio: local/align.ffmpeg_reader."""
    def at(a: float, b: float) -> Voice:
        if b - a < 0.5:
            return Voice(None, None)
        try:
            x = read_audio(a, b - a)
        except Exception:   # noqa: BLE001 — a seam note is never worth failing the apply
            return Voice(None, None)
        return measure(x, ref_f0=ref_f0, threshold_db=threshold_db)
    return at
