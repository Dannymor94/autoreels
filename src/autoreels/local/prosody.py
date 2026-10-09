"""Sentence-end intonation (M2.2): does the voice FINISH at a full stop, or say "to be continued"?

Why: a full stop in the transcript is not an ending. IMG_6848 r01 ended on «Вот так родился я как
психолог.» — the owner: «он не закончил говорить». The voice stayed high (82nd percentile of the
speaker's pitch); every ending he accepted either fell to the bottom of his range or faded into
creak (no measurable pitch). Measured on all 332 sentence ends of IMG_6848 (diagnostic M26):
owner verdicts 10/10 separated by the rule below; about a third of the text's full stops are
spoken as "to be continued".

Per aligned word (forced-alignment times, transcripts/<stem>.align.json):
  v        voiced 10 ms pitch frames inside the word;
  end_pct  where the pitch of the word's last 120 ms sits among ALL voiced frames of the source
           (0 = the speaker's lowest, 100 = highest).
A sentence end is
  final    — the last word ends low (end_pct ≤ final_pct_max) or fades out without pitch
             (v ≤ creak_voiced_max over a word of ≥ min_word_sec: creak / falling-off voice);
  open     — end_pct ≥ open_pct_min: the voice stays up, the speaker goes on;
  unsure   — in between.

Output: transcripts/<stem>.prosody.json
    {"version": 1, "source_sha256": "...", "align_transcript": {...}, "ref_f0": 96.6,
     "words": [{"t0": <whisper t0>, "v": 27, "end_pct": 3.9, "dur": 0.42}, ...]}
parselmouth (Praat) is imported only by the pitch tracker (analysis machine). The rest is pure.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

PROSODY_VERSION = 1
SR = 16000
FRAME = 0.01


@dataclass(frozen=True)
class ToneParams:
    final_pct_max: float = 30.0     # every accepted ending ≤ 26 (IMG_6848); the rejected ones 50, 82
    open_pct_min: float = 60.0
    creak_voiced_max: int = 3       # ≤ 3 voiced frames over the whole word = no pitch = fades out
    min_word_sec: float = 0.15      # shorter words are too short to judge by missing pitch
    tail_sec: float = 0.12          # "end" of the word = its last 120 ms


def word_tones(t: np.ndarray, f0: np.ndarray, spans: Sequence[tuple[float, float]],
               *, tail_sec: float = 0.12) -> tuple[list[dict], float]:
    """Per-word voicing and end-pitch percentile. `t`, `f0`: pitch track (s, Hz; 0 = unvoiced).
    Returns (entries in `spans` order, speaker median f0)."""
    t = np.asarray(t, dtype=float)
    f0 = np.asarray(f0, dtype=float)
    voiced = f0 > 0
    ref = float(np.median(f0[voiced])) if voiced.any() else 100.0
    st = np.where(voiced, 12.0 * np.log2(np.maximum(f0, 1e-6) / ref), np.nan)
    allv = np.sort(st[voiced])
    out = []
    for a, b in spans:
        m = (t >= a) & (t < b) & voiced
        e: dict = {"v": int(m.sum()), "end_pct": None, "dur": round(float(b - a), 3)}
        if m.sum() >= 4 and len(allv):
            tt, ss = t[m], st[m]
            tail = ss[tt >= b - tail_sec]
            if len(tail) < 2:
                tail = ss[-3:]
            e["end_pct"] = round(100.0 * float(np.searchsorted(allv, float(np.median(tail)))) / len(allv), 1)
        out.append(e)
    return out, ref


def classify(entry: dict | None, p: ToneParams = ToneParams()) -> str | None:
    """'final' | 'open' | 'unsure' for one word entry; None = no data / too short to judge."""
    if not entry:
        return None
    pct = entry.get("end_pct")
    if pct is not None:
        if pct <= p.final_pct_max:
            return "final"
        if pct >= p.open_pct_min:
            return "open"
        return "unsure"
    if entry.get("v", 0) <= p.creak_voiced_max and entry.get("dur", 0.0) >= p.min_word_sec:
        return "final"
    return None


def describe(entry: dict, tone: str) -> str:
    if entry.get("end_pct") is not None:
        return f"{tone} (end pitch {entry['end_pct']:.0f}/100 in the speaker's range)"
    return f"{tone} (voice fades out, no pitch)"


def compute_prosody(align: dict, t: np.ndarray, f0: np.ndarray) -> dict:
    """The .prosody.json payload (no sha) for every aligned word of `align`."""
    ws = [w for w in align.get("words", []) if w.get("start") is not None]
    entries, ref = word_tones(t, f0, [(w["start"], w["end"]) for w in ws])
    return {"version": PROSODY_VERSION, "align_transcript": align.get("transcript"),
            "ref_f0": round(ref, 2),
            "words": [dict(t0=w["t0"], **e) for w, e in zip(ws, entries)]}


def pitch_track(read_audio: Callable[[float, float], np.ndarray], total: float, *,
                chunk: float = 120.0, progress: Callable[[float], None] | None = None):
    """Praat pitch (Hz, 0 = unvoiced) every 10 ms over the whole source, chunk by chunk."""
    try:
        import parselmouth
    except ImportError as e:  # pragma: no cover - analysis machine only
        raise RuntimeError("интонация требует praat-parselmouth: "
                           ".venv/bin/python -m pip install praat-parselmouth") from e
    T, F = [], []
    t0 = 0.0
    while t0 < total:
        x = read_audio(t0, min(chunk + 1.0, total - t0))
        if len(x) < SR // 2:
            break
        snd = parselmouth.Sound(np.asarray(x, dtype=np.float64), sampling_frequency=SR)
        p = snd.to_pitch(time_step=FRAME, pitch_floor=60.0, pitch_ceiling=400.0)
        keep = p.xs() < chunk
        T.append(p.xs()[keep] + t0)
        F.append(p.selected_array["frequency"][keep])
        t0 += chunk
        if progress is not None:
            progress(min(t0, total))
    if not T:
        return np.zeros(0), np.zeros(0)
    return np.concatenate(T), np.concatenate(F)


def write_prosody(path: Path, payload: dict, source_sha256: str) -> None:
    data = dict(payload)
    data["source_sha256"] = source_sha256
    Path(path).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def load_prosody(path, source_sha256: str | None = None, align: dict | None = None) -> dict | None:
    """transcripts/<stem>.prosody.json or None when missing, of another source, or computed from
    another alignment (stale: word times changed)."""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("version") != PROSODY_VERSION:
        return None
    if source_sha256 and data.get("source_sha256") and data["source_sha256"] != source_sha256:
        return None
    if align is not None and data.get("align_transcript") != align.get("transcript"):
        return None
    return data


def tone_lookup(prosody: dict | None, p: ToneParams = ToneParams()) -> Callable | None:
    """word → (tone, description) | None, matched by Whisper t0 (like the alignment)."""
    if not prosody:
        return None
    idx = {round(float(w["t0"]) * 1000): w for w in prosody.get("words", [])}

    def tone(word) -> tuple[str, str] | None:
        e = idx.get(round(float(word.t0) * 1000))
        c = classify(e, p)
        return None if c is None else (c, describe(e, c))
    return tone
