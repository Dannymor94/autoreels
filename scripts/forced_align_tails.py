#!/usr/bin/env python3
"""Forced-alignment spike for tail-placement benchmark.

For each case in benchmarks/tails/answers.csv:
  1. Extract audio window (last_word_t0 ± 10 s) from source video.
  2. Align the Whisper transcript words in that window using
     jonatasgrosman/wav2vec2-large-xlsr-53-russian (CPU).
  3. Record the aligned end time of the last word → candidate C.
  4. Update answers.csv with C_s column.
  5. Re-inject click C into the WAV (calls make_tail_benchmark --rebuild-c).

Reports:
  - Per-case C value and delta vs A and B
  - Words that could not be aligned (numbers, symbols, etc.)
  - Runtime per minute of aligned audio

Usage:
  .venv/bin/python scripts/forced_align_tails.py
  .venv/bin/python scripts/forced_align_tails.py --case pxl0729_r01   # single case
"""
from __future__ import annotations
import argparse, csv, json, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from autoreels.core.models import Manifest
from autoreels.local.render import resolve_source

TAILS_DIR = ROOT / "benchmarks" / "tails"
ANSWERS_CSV = TAILS_DIR / "answers.csv"
MANIFESTS_DIR = ROOT / "manifests"
TRANSCRIPTS_DIR = ROOT / "transcripts"
INPUTS_DIR = ROOT / "inputs-archive"

ALIGN_MODEL = "jonatasgrosman/wav2vec2-large-xlsr-53-russian"
ALIGN_LANGUAGE = "ru"
WINDOW_SEC = 10.0   # ±10 s around last word t0
SR_ALIGN = 16000    # wav2vec2 expects 16 kHz

STEM_MAP = {
    "pxl0729": "PXL_20260729_085910095_34f06abf",
    "lec1142": "2026-08-08 11h 42m 49s",
    "img6848": "IMG_6848",
    "lec0933": "2026-08-08 09h 33m 14s",
}


def _load_whisper_words(stem: str) -> list[dict]:
    """Load word-level timestamps from transcripts/<stem>.txt JSON or speechmap."""
    # Try .txt first (Whisper JSON saved by autoreels)
    txt_path = TRANSCRIPTS_DIR / f"{stem}.txt"
    if not txt_path.exists():
        return []
    data = json.loads(txt_path.read_text())
    words: list[dict] = []
    for seg in data.get("segments", []):
        for w in seg.get("words", []):
            if w.get("word", "").strip():
                words.append({
                    "word": w["word"].strip(),
                    "start": w.get("start", 0.0),
                    "end": w.get("end", 0.0),
                })
    return words


def _extract_wav(source: Path, t_start: float, t_end: float, out_path: Path) -> None:
    dur = max(t_end - t_start, 0.1)
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", f"{t_start:.6f}", "-t", f"{dur:.6f}",
            "-i", str(source),
            "-vn", "-ac", "1", "-ar", str(SR_ALIGN), str(out_path),
        ],
        capture_output=True, check=True,
    )


def _align_window(audio_path: Path, words_in_window: list[dict],
                   window_start: float) -> tuple[list[dict], list[str]]:
    """Run whisperx forced alignment. Returns (aligned_words, unaligned_word_texts)."""
    import whisperx

    model, meta = whisperx.load_align_model(
        language_code=ALIGN_LANGUAGE,
        device="cpu",
        model_name=ALIGN_MODEL,
    )
    audio = whisperx.load_audio(str(audio_path))

    # Build transcript segments in whisperx format (times relative to window)
    # whisperx.align expects segments with word-level 'start'/'end' relative to audio
    rel_words = [
        {
            "word": w["word"],
            "start": max(0.0, w["start"] - window_start),
            "end": max(0.0, w["end"] - window_start),
        }
        for w in words_in_window
    ]
    segments = [{
        "start": rel_words[0]["start"] if rel_words else 0.0,
        "end": rel_words[-1]["end"] if rel_words else 1.0,
        "text": " ".join(w["word"] for w in rel_words),
        "words": rel_words,
    }]

    result = whisperx.align(segments, model, meta, audio, device="cpu",
                            return_char_alignments=False)

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


def run(only_case: str | None = None) -> None:
    if not ANSWERS_CSV.exists():
        print("answers.csv not found — run make_tail_benchmark.py first")
        sys.exit(1)

    rows = list(csv.DictReader(open(ANSWERS_CSV)))
    updated: list[dict] = []
    all_unaligned: list[str] = []
    total_audio_sec = 0.0
    total_wall_sec = 0.0

    for row in rows:
        case_id = row["case"]
        if only_case and case_id != only_case:
            updated.append(row)
            continue

        short_id = row["stem"]
        reel_id = row["reel"]
        stem = STEM_MAP.get(short_id)
        if not stem:
            print(f"  skip {case_id}: unknown stem {short_id!r}")
            updated.append(row)
            continue

        A_s = row.get("A_s", "").strip()
        if not A_s:
            print(f"  skip {case_id}: no A_s (Whisper t1)")
            updated.append(row)
            continue

        last_word_time = float(A_s)
        manifest_path = MANIFESTS_DIR / f"{stem}.json"
        smap_path = TRANSCRIPTS_DIR / f"{stem}.speechmap.json"

        try:
            manifest = Manifest.model_validate_json(manifest_path.read_text())
            source = resolve_source(manifest, INPUTS_DIR)
        except Exception as e:
            print(f"  skip {case_id}: {e}")
            updated.append(row)
            continue

        reel = next((r for r in manifest.reels if r.id == reel_id), None)
        if reel is None:
            print(f"  skip {case_id}: reel not found")
            updated.append(row)
            continue

        subs = reel.subtitles or []
        if not subs:
            print(f"  skip {case_id}: no subtitles")
            updated.append(row)
            continue

        # Gather Whisper words in alignment window
        t_win_start = max(0.0, last_word_time - WINDOW_SEC)
        t_win_end = last_word_time + WINDOW_SEC
        all_words = _load_whisper_words(stem)
        window_words = [w for w in all_words
                        if w["end"] >= t_win_start and w["start"] <= t_win_end]

        if not window_words:
            print(f"  skip {case_id}: no Whisper words in ±{WINDOW_SEC}s window")
            updated.append(row)
            continue

        print(f"  {case_id}: aligning {len(window_words)} words in "
              f"{t_win_start:.1f}–{t_win_end:.1f}s ...", flush=True)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            tmp_wav = Path(tf.name)

        try:
            _extract_wav(source, t_win_start, t_win_end, tmp_wav)
            audio_dur = t_win_end - t_win_start
            total_audio_sec += audio_dur

            t0_wall = time.monotonic()
            aligned_words, unaligned = _align_window(tmp_wav, window_words, t_win_start)
            elapsed = time.monotonic() - t0_wall
            total_wall_sec += elapsed

            all_unaligned.extend(unaligned)

            # Find the last subtitle word in the aligned results
            last_sub = subs[-1]
            last_word_text = last_sub.word.strip().lower().rstrip(".,!?")
            C_val: float | None = None

            # Match by normalized text
            for aw in reversed(aligned_words):
                if aw["word"].strip().lower().rstrip(".,!?") == last_word_text:
                    C_val = aw["end"]
                    break

            # Fallback: use the last aligned word if text matching fails
            if C_val is None and aligned_words:
                C_val = aligned_words[-1]["end"]
                print(f"    WARNING: text match failed for '{last_sub.word}', "
                      f"using last aligned word end {C_val:.3f}")

            if C_val is not None:
                row = dict(row)
                row["C_s"] = f"{C_val:.3f}"
                A_delta = (C_val - float(A_s)) * 1000 if A_s else None
                B_s = row.get("B_s", "").strip()
                B_delta = (C_val - float(B_s)) * 1000 if B_s else None
                print(f"    C={C_val:.3f}s  ΔA={A_delta:+.0f}ms  "
                      f"ΔB={B_delta:+.0f}ms  [{elapsed:.1f}s wall / {audio_dur/60*elapsed:.1f}s per min]",
                      flush=True)
            else:
                print(f"    WARNING: no aligned result for {case_id}")

        except Exception as e:
            print(f"    ERROR: {e}")
        finally:
            tmp_wav.unlink(missing_ok=True)

        updated.append(row)

    # Write updated CSV
    fieldnames = list(rows[0].keys()) if rows else []
    if "C_s" not in fieldnames:
        fieldnames = [f if f != "B_s" else "B_s" for f in fieldnames]
        # C_s should already be in the CSV from make_tail_benchmark

    with open(ANSWERS_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(updated)

    # Summary
    print(f"\n--- Alignment summary ---")
    if total_audio_sec > 0 and total_wall_sec > 0:
        rtf = total_wall_sec / total_audio_sec
        print(f"Audio aligned: {total_audio_sec:.0f} s")
        print(f"Wall time:     {total_wall_sec:.1f} s")
        print(f"RTF:           {rtf:.2f}x  ({total_wall_sec / (total_audio_sec / 60):.1f} s/min)")

    if all_unaligned:
        from collections import Counter
        counts = Counter(all_unaligned)
        print(f"\nUnaligned words ({len(all_unaligned)} total, {len(counts)} unique):")
        for w, n in counts.most_common(20):
            print(f"  {n:3d}×  {w!r}")
    else:
        print("No unaligned words.")

    print(f"\nanswers.csv updated with C_s column → {ANSWERS_CSV}")
    print("Run 'python scripts/make_tail_benchmark.py --rebuild-c' to inject C clicks into WAVs.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", help="Only process this case id (e.g. pxl0729_r01)")
    args = parser.parse_args()
    run(only_case=args.case)
