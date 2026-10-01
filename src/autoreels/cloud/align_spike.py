"""Forced-alignment spike — NOT wired into the pipeline.

Wraps whisperx forced alignment (jonatasgrosman/wav2vec2-large-xlsr-53-russian)
for the tail-placement benchmark only.

Install: pip install 'autoreels[align]'
Model cache: ~/.cache/huggingface/hub/  (downloaded on first call, never committed)
"""
from __future__ import annotations
from pathlib import Path

ALIGN_MODEL = "jonatasgrosman/wav2vec2-large-xlsr-53-russian"
ALIGN_LANGUAGE = "ru"


def align_words(
    audio_path: Path,
    words: list[dict],
    window_start: float = 0.0,
    *,
    device: str = "cpu",
) -> tuple[list[dict], list[str]]:
    """Align transcript words to audio via wav2vec2 forced alignment.

    Args:
        audio_path: 16 kHz mono WAV containing the audio window.
        words: Whisper-format dicts with keys ``word``, ``start``, ``end``
               (absolute source times in seconds).
        window_start: absolute start of the audio window (seconds) — used
                      to convert relative per-frame times back to absolute.
        device: "cpu" (default) or "cuda".

    Returns:
        (aligned_words, unaligned_texts)
        aligned_words: list of {"word", "start", "end"} with absolute times.
        unaligned_texts: words whisperx could not align (numbers, symbols, etc.).
    """
    import whisperx  # optional dep; raises ImportError with helpful message

    model, meta = whisperx.load_align_model(
        language_code=ALIGN_LANGUAGE,
        device=device,
        model_name=ALIGN_MODEL,
    )
    audio = whisperx.load_audio(str(audio_path))

    rel_words = [
        {
            "word": w["word"],
            "start": max(0.0, w["start"] - window_start),
            "end": max(0.0, w["end"] - window_start),
        }
        for w in words
    ]
    if not rel_words:
        return [], []

    segments = [{
        "start": rel_words[0]["start"],
        "end": rel_words[-1]["end"],
        "text": " ".join(w["word"] for w in rel_words),
        "words": rel_words,
    }]

    result = whisperx.align(
        segments, model, meta, audio, device=device, return_char_alignments=False
    )

    aligned: list[dict] = []
    unaligned: list[str] = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            if w.get("start") is not None:
                aligned.append({
                    "word": w["word"],
                    "start": window_start + w["start"],
                    "end": window_start + w["end"],
                })
            else:
                unaligned.append(w.get("word", "?"))

    return aligned, unaligned


def find_last_word_end(
    aligned: list[dict],
    target_word: str,
) -> float | None:
    """Return the aligned end time of the last occurrence of *target_word*.

    Normalises by stripping punctuation and lowercasing before comparison.
    Falls back to the last aligned word's end if no match found.
    """
    norm = target_word.strip().lower().rstrip(".,!?;:")
    for w in reversed(aligned):
        if w["word"].strip().lower().rstrip(".,!?;:") == norm:
            return w["end"]
    return aligned[-1]["end"] if aligned else None
