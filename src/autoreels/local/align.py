"""Forced alignment of the transcript to the AUDIO (M2.1) — exact word boundaries.

Why: Whisper word times are off by up to 2 s at phrase ends — a final word is stretched over the
hesitation after it («жизнь.» 203.35–205.71 s; the word is 0.26 s, the rest is «а… о… ммм»), the
next word's start is guessed early or late. Cutting by those times produced every «обрыв фразы»,
«конец на ммм / ну», «начало с полуслова» of the IMG_6848 pilot (diagnostic M21).

How: torchaudio's MMS_FA (wav2vec2, multilingual, CTC) aligns the known text to the audio,
chunk by chunk (≤ max_chunk_sec of words + margin audio). A wildcard token "*" between words
absorbs speech that is NOT in the transcript (fillers, «ммм», «ну»); those spans, intersected with
the speech map's energy intervals, are stored as `untranscribed` speech — the plan never cuts
into them and never lets them into a clip edge.

Output: transcripts/<stem>.align.json
    {"version": 1, "model": "torchaudio.MMS_FA", "source_sha256": "...",
     "words": [{"t0": <whisper t0>, "start": s, "end": e, "score": p}, ...],
     "untranscribed": [[s, e], ...]}
Words are keyed by their Whisper t0 (round(t0*1000)), like the speech map.

torch/torchaudio are imported only by MMSBackend (analysis machine). Everything else is pure and
tested with a fake backend.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

import numpy as np

ALIGN_VERSION = 1
SR = 16000

_TR = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "zh", "з": "z",
       "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
       "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh",
       "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya"}


def romanize(word: str) -> str:
    """Lower-case a–z only (the MMS_FA dictionary); punctuation and digits dropped."""
    out = []
    for ch in word.lower():
        if ch in _TR:
            out.append(_TR[ch])
        elif "a" <= ch <= "z":
            out.append(ch)
    return "".join(out)


@dataclass
class Chunk:
    start: float            # audio region, source seconds
    end: float
    idx: list[int]          # word indices aligned in this chunk


def plan_chunks(spans: Sequence[tuple[float, float]], use: Sequence[bool], *, max_chunk_sec: float = 25.0,
                margin_sec: float = 1.5, total_sec: float | None = None,
                max_fill_sec: float = 10.0) -> list[Chunk]:
    """Group usable words (in order) into chunks whose Whisper span is ≤ max_chunk_sec."""
    chunks: list[Chunk] = []
    cur: list[int] = []
    for i, (t0, t1) in enumerate(spans):
        if not use[i]:
            continue
        if cur and t1 - spans[cur[0]][0] > max_chunk_sec:
            chunks.append(_mk_chunk(cur, spans, margin_sec, total_sec))
            cur = []
        cur.append(i)
    if cur:
        chunks.append(_mk_chunk(cur, spans, margin_sec, total_sec))
    # Close the audio gaps between chunks (up to max_fill_sec), so fillers in long pauses between
    # chunks are still seen by some chunk's wildcard.
    for a, b in zip(chunks, chunks[1:]):
        if b.start > a.end:
            a.end = min(b.start, a.end + max_fill_sec)
    return chunks


def _mk_chunk(idx, spans, margin, total) -> Chunk:
    a = max(0.0, spans[idx[0]][0] - margin)
    b = spans[idx[-1]][1] + margin
    if total is not None:
        b = min(b, total)
    return Chunk(a, max(b, a + 0.1), list(idx))


def untranscribed_speech(stars: Iterable[tuple[float, float]], energy: Sequence[Sequence[float]],
                         words: Iterable[tuple[float, float]], *, min_len: float = 0.08) -> list[list[float]]:
    """Speech that is in no transcript word: wildcard spans ∩ energy speech − aligned words."""
    iv = sorted((float(a), float(b)) for a, b in energy if b > a)
    wd = sorted((float(a), float(b)) for a, b in words if b > a)
    pieces: list[tuple[float, float]] = []
    for sa, sb in stars:
        for ea, eb in iv:
            if eb <= sa:
                continue
            if ea >= sb:
                break
            a, b = max(sa, ea), min(sb, eb)
            parts = [(a, b)]
            for wa, wb in wd:                       # subtract aligned words
                if wb <= a or wa >= b:
                    continue
                nxt = []
                for pa, pb in parts:
                    if wb <= pa or wa >= pb:
                        nxt.append((pa, pb))
                        continue
                    if wa > pa:
                        nxt.append((pa, wa))
                    if wb < pb:
                        nxt.append((wb, pb))
                parts = nxt
            pieces.extend(p for p in parts if p[1] - p[0] >= min_len)
    out: list[list[float]] = []
    for a, b in sorted(pieces):
        if out and a <= out[-1][1] + 1e-3:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([round(a, 3), round(b, 3)])
    return [[round(a, 3), round(b, 3)] for a, b in out]


class MMSBackend:
    """torchaudio MMS_FA. Downloads the model (~1.2 GB) on first use."""

    def __init__(self):
        try:
            import torch
            import torchaudio
        except ImportError as e:  # pragma: no cover - analysis machine only
            raise RuntimeError("выравнивание требует torch и torchaudio: "
                               ".venv/bin/pip install torch==2.8.0 torchaudio==2.8.0") from e
        self._torch = torch
        b = torchaudio.pipelines.MMS_FA
        self.model = b.get_model(with_star=True).eval()
        self.tokenizer = b.get_tokenizer()
        self.aligner = b.get_aligner()

    def align(self, audio: np.ndarray, seq: list[str]):  # pragma: no cover - needs the model
        torch = self._torch
        wav = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32)).unsqueeze(0)
        with torch.inference_mode():
            emission, _ = self.model(wav)
        spans = self.aligner(emission[0], self.tokenizer(seq))
        n_frames = emission.size(1)
        return n_frames, [[(s.start, s.end, float(s.score)) for s in sp] for sp in spans]


def align_transcript(words: Sequence, use: Sequence[bool], read_audio: Callable[[float, float], np.ndarray],
                     energy: Sequence[Sequence[float]], backend, *, max_chunk_sec: float = 25.0,
                     margin_sec: float = 1.5, max_shift_sec: float = 3.0, total_sec: float | None = None,
                     progress: Callable[[int, int], None] | None = None) -> dict:
    """Align `words` (objects with .word/.t0/.t1) to the audio. `use[i]` False = not aligned
    (credit hallucinations, punctuation-only tokens). Returns the .align.json payload (no sha)."""
    roman = [romanize(w.word) for w in words]
    # Tokens with digits («14-ти», «90-х») are spoken as numbers: their letters are not what is
    # heard — not aligned; their Whisper span is kept out of the untranscribed speech below.
    has_digit = [any(c.isdigit() for c in w.word) for w in words]
    usable = [bool(use[i]) and bool(roman[i]) and not has_digit[i] for i in range(len(words))]
    spans = [(float(w.t0), float(w.t1)) for w in words]
    chunks = plan_chunks(spans, usable, max_chunk_sec=max_chunk_sec, margin_sec=margin_sec, total_sec=total_sec)
    out_words: dict[int, dict] = {}
    stars: list[tuple[float, float]] = []
    failed: list[dict] = []
    for ci, ch in enumerate(chunks):
        if progress is not None:
            progress(ci, len(chunks))
        audio = read_audio(ch.start, ch.end - ch.start)
        if len(audio) < SR // 10:
            continue
        seq = ["*"]
        for i in ch.idx:
            seq += [roman[i], "*"]
        try:
            n_frames, tok_spans = backend.align(audio, seq)
        except Exception as e:  # one bad chunk must not lose a 30-minute run
            failed.append({"start": round(ch.start, 3), "end": round(ch.end, 3), "words": len(ch.idx),
                           "error": f"{type(e).__name__}: {e}"[:200]})
            continue
        ratio = len(audio) / max(1, n_frames) / SR
        k = 0
        for tok, sp in zip(seq, tok_spans):
            if not sp:
                continue
            st = ch.start + sp[0][0] * ratio
            en = ch.start + sp[-1][1] * ratio
            if tok == "*":
                if en - st >= 0.05:
                    stars.append((st, en))
                continue
            i = ch.idx[k]
            k += 1
            dur = sum(e - s for s, e, _ in sp)
            score = sum(sc * (e - s) for s, e, sc in sp) / max(1, dur)
            far = abs(st - spans[i][0]) > max_shift_sec
            out_words[i] = {"t0": spans[i][0], "start": None if far else round(st, 3),
                            "end": None if far else round(en, 3), "score": round(score, 3),
                            **({"far": True} if far else {})}
    words_out = [out_words[i] for i in sorted(out_words)]
    word_spans = [(w["start"], w["end"]) for w in words_out if w["start"] is not None]
    # words that are real speech but not aligned (numbers, far, failed chunk): their Whisper span
    # is not "untranscribed" speech
    not_aligned = [spans[i] for i in range(len(words)) if use[i] and (i not in out_words
                                                                      or out_words[i]["start"] is None)]
    return {"version": ALIGN_VERSION, "model": "torchaudio.MMS_FA",
            "transcript": transcript_identity(words),
            "words": words_out,
            "untranscribed": untranscribed_speech(stars, energy, word_spans + not_aligned),
            "failed_chunks": failed}


def transcript_identity(words: Sequence) -> dict:
    """Which transcript an alignment belongs to (words are matched by Whisper t0)."""
    import hashlib
    h = hashlib.sha256("|".join(f"{float(w.t0):.3f}" for w in words).encode()).hexdigest()[:16]
    return {"n_words": len(words), "t0_hash": h}


def ffmpeg_reader(src: Path, ffmpeg: str = "ffmpeg") -> Callable[[float, float], np.ndarray]:
    def read(start: float, dur: float) -> np.ndarray:
        cmd = [ffmpeg, "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
               "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "pipe:1"]
        raw = subprocess.run(cmd, capture_output=True, check=True).stdout
        return np.frombuffer(raw, dtype=np.float32).copy()
    return read


def write_alignment(path: Path, payload: dict, source_sha256: str) -> None:
    data = dict(payload)
    data["source_sha256"] = source_sha256
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
