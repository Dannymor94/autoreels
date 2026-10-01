#!/usr/bin/env python3
"""Forced-alignment spike for tail-placement benchmark (Part 2).

Uses torchaudio MMS_FA (Meta Massively Multilingual Speech) + Uroman romanization
to align existing Whisper transcript words and find accurate acoustic word-end
times (candidate C) for each tail case.

MODEL NOTE: MMS_FA model is ~1.26 GB. First run downloads it to
~/.cache/torch/hub/checkpoints/ (one-time cost, ~90 min at 200 KB/s).
After download, each 20s window takes ~2-5 s on CPU.

Alternative model: jonatasgrosman/wav2vec2-large-xlsr-53-russian via transformers
  → same size, faster download via HuggingFace CDN.  Pass --backend=hf to use it.

Produces:
  - answers.csv updated with C_s column
  - WAV files updated with click C (1047 Hz, C6) via make_tail_benchmark.py --rebuild-c

Usage:
  .venv/bin/python3.11 scripts/forced_align_tails.py
  .venv/bin/python3.11 scripts/forced_align_tails.py --case pxl0729_r01
  .venv/bin/python3.11 scripts/forced_align_tails.py --dry-run   # check setup, no alignment

Run with .venv/bin/python3.11 (not python3.13) — torchaudio installs under 3.11.
"""
from __future__ import annotations
import argparse, csv, json, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).parent.parent

TAILS_DIR = ROOT / "benchmarks" / "tails"
ANSWERS_CSV = TAILS_DIR / "answers.csv"
MANIFESTS_DIR = ROOT / "manifests"
TRANSCRIPTS_DIR = ROOT / "transcripts"
INPUTS_DIR = ROOT / "inputs-archive"


def _resolve_source(manifest_data: dict) -> Path:
    """Find source video file: try source_path, then INPUTS_DIR/<source> field."""
    sp = manifest_data.get("source_path", "")
    if sp:
        p = Path(sp)
        if p.exists():
            return p
    src = manifest_data.get("source", "")
    if src:
        cand = INPUTS_DIR / src
        if cand.exists():
            return cand
    raise FileNotFoundError(f"Source not found: source_path={sp!r}, source={src!r}")

ALIGN_LANGUAGE = "ru"
WINDOW_SEC = 10.0   # ±10 s around last word t0
SR_ALIGN = 16000

STEM_MAP = {
    "pxl0729": "PXL_20260729_085910095_34f06abf",
    "lec1142": "2026-08-08 11h 42m 49s",
    "img6848": "IMG_6848",
    "lec0933": "2026-08-08 09h 33m 14s",
}


# ---------------------------------------------------------------------------
# Model setup
# ---------------------------------------------------------------------------

def _load_mms_model():
    """Load torchaudio MMS_FA model. Downloads on first call (~1.26 GB)."""
    import torchaudio
    bundle = torchaudio.pipelines.MMS_FA
    model = bundle.get_model()
    model.eval()
    return bundle, model


def _load_hf_model():
    """Fallback: load jonatasgrosman/wav2vec2-large-xlsr-53-russian via transformers."""
    from transformers import Wav2Vec2Processor, Wav2Vec2ForCTC
    import torch

    model_id = "jonatasgrosman/wav2vec2-large-xlsr-53-russian"
    processor = Wav2Vec2Processor.from_pretrained(model_id)
    model = Wav2Vec2ForCTC.from_pretrained(model_id)
    model.eval()
    return processor, model


# ---------------------------------------------------------------------------
# Alignment
# ---------------------------------------------------------------------------

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


def _align_with_mms(bundle, model, wav_path: Path, words_in_window: list[dict],
                    window_start: float) -> tuple[list[dict], list[str]]:
    """Align words using MMS_FA + Uroman romanization.

    Returns (aligned_words_with_abs_times, list_of_unaligned_word_texts).
    """
    import torch, torchaudio
    from torchaudio.functional import forced_align
    import ctc_forced_aligner

    waveform, sr = torchaudio.load(str(wav_path))
    if sr != bundle.sample_rate:
        waveform = torchaudio.functional.resample(waveform, sr, bundle.sample_rate)

    with torch.inference_mode():
        emission, _ = model(waveform)

    # Romanize Russian text
    word_texts = [w["word"] for w in words_in_window]
    all_text = " ".join(word_texts)
    tokens, romanized_words = ctc_forced_aligner.preprocess_text(
        all_text, romanize=True, language=ALIGN_LANGUAGE, split_size="word"
    )

    # Map romanized tokens to MMS_FA label indices
    labels = bundle.get_labels(star=None)
    label_dict = {c: i for i, c in enumerate(labels)}
    token_ids: list[list[int]] = []
    for tok in tokens:
        if tok in ("<star>",):
            continue  # skip star tokens used as separators
        ids = [label_dict[c] for c in tok.split() if c in label_dict]
        if ids:
            token_ids.extend(ids)

    if not token_ids:
        return [], [w["word"] for w in words_in_window]

    token_tensor = torch.tensor([token_ids])
    token_lengths = torch.tensor([len(token_ids)])
    emission_lengths = torch.tensor([emission.shape[1]])

    # forced_align returns (alignments, scores)
    aligned_tokens, scores = forced_align(
        emission, token_tensor, emission_lengths, token_lengths,
        blank=0
    )
    # Convert frame positions to times
    # MMS_FA stride = model's output rate (320 samples/frame at 16kHz → 20ms/frame)
    frame_dur = 0.02  # seconds per frame for MMS_FA

    # Map token-level back to word-level using character positions
    # This is a simplified version: find token boundaries per word
    aligned: list[dict] = []
    unaligned: list[str] = []
    aligned_flat = aligned_tokens[0].tolist()

    # Use ctc_forced_aligner's span logic for word segmentation
    tokenizer = ctc_forced_aligner.Tokenizer(ctc_forced_aligner.VOCAB_DICT)
    # Build emissions array for ctc_forced_aligner from our emission
    import numpy as np
    em_np = emission[0].cpu().numpy()  # shape: [T, V]
    # get_alignments expects (T, V) emissions
    aligns, ctc_scores = ctc_forced_aligner.get_alignments(em_np, tokens, tokenizer)
    spans = ctc_forced_aligner.get_spans(tokens, aligns)
    stamps = ctc_forced_aligner.get_word_stamps(
        spans, ctc_scores, stride=frame_dur,
        t_overlap=window_start, merge_words=False
    )
    for stamp in stamps:
        aligned.append({
            "word": stamp["word"],
            "start": stamp["start"],
            "end": stamp["end"],
        })

    return aligned, unaligned


def _align_with_hf(processor, model, wav_path: Path, words_in_window: list[dict],
                    window_start: float) -> tuple[list[dict], list[str]]:
    """Fallback alignment via wav2vec2-large-xlsr-53-russian + torchaudio.forced_align."""
    import torch, torchaudio
    from torchaudio.functional import forced_align

    waveform, sr = torchaudio.load(str(wav_path))
    if sr != SR_ALIGN:
        waveform = torchaudio.functional.resample(waveform, sr, SR_ALIGN)

    inputs = processor(waveform.squeeze(), sampling_rate=SR_ALIGN, return_tensors="pt")
    with torch.no_grad():
        logits = model(**inputs).logits  # (1, T, V)

    vocab = processor.tokenizer.get_vocab()
    # Build token sequence from word texts
    unaligned: list[str] = []
    token_ids: list[int] = []
    word_boundaries: list[tuple[int, int, str]] = []  # (start_idx, end_idx, word)

    for w in words_in_window:
        text = w["word"].strip().lower()
        ids = []
        for char in text:
            if char in vocab:
                ids.append(vocab[char])
            else:
                unaligned.append(w["word"])
                break
        else:
            word_boundaries.append((len(token_ids), len(token_ids) + len(ids), w["word"]))
            token_ids.extend(ids)

    if not token_ids or not word_boundaries:
        return [], [w["word"] for w in words_in_window]

    token_tensor = torch.tensor([token_ids])
    token_lengths = torch.tensor([len(token_ids)])
    emission_lengths = torch.tensor([logits.shape[1]])

    aligned_tokens, scores = forced_align(
        logits, token_tensor, emission_lengths, token_lengths, blank=0
    )
    aligned_flat = aligned_tokens[0].tolist()

    frame_dur = 1.0 / (logits.shape[1] / (waveform.shape[-1] / SR_ALIGN))
    aligned: list[dict] = []
    for start_idx, end_idx, word in word_boundaries:
        word_frames = [i for i, t in enumerate(aligned_flat) if start_idx <= t - 1 < end_idx]
        if word_frames:
            start_s = window_start + word_frames[0] * frame_dur
            end_s = window_start + (word_frames[-1] + 1) * frame_dur
            aligned.append({"word": word, "start": start_s, "end": end_s})
        else:
            unaligned.append(word)

    return aligned, unaligned


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(only_case: str | None = None, backend: str = "mms", dry_run: bool = False) -> None:
    if not ANSWERS_CSV.exists():
        print("answers.csv not found — run make_tail_benchmark.py first")
        sys.exit(1)

    rows = list(csv.DictReader(open(ANSWERS_CSV)))

    if dry_run:
        print("DRY RUN: checking setup (no alignment will run)")
        try:
            import torchaudio
            import ctc_forced_aligner
            print(f"  torchaudio {torchaudio.__version__}: OK")
            ckpt_dir = Path.home() / ".cache" / "torch" / "hub" / "checkpoints"
            partial = list(ckpt_dir.glob("model.pt*.partial"))
            if partial:
                done = partial[0].stat().st_size
                total = 1262047414
                pct = 100 * done / total
                eta = (total - done) / (200 * 1024)  # assume 200 KB/s
                print(f"  MMS_FA model: downloading {done//1024//1024} MB / "
                      f"{total//1024//1024} MB ({pct:.0f}%) — ETA {eta/60:.0f} min")
            else:
                full = ckpt_dir / "model.pt"
                if full.exists():
                    print(f"  MMS_FA model: cached ({full.stat().st_size//1024//1024} MB)")
                else:
                    print("  MMS_FA model: not cached — will download on first alignment")
        except ImportError as e:
            print(f"  ERROR: {e}")
        return

    # Load model
    print(f"Loading {backend} model ...", flush=True)
    t0 = time.monotonic()
    if backend == "hf":
        proc_or_bundle, model = _load_hf_model()
        align_fn = lambda wav, words, t_start: _align_with_hf(proc_or_bundle, model, wav, words, t_start)
    else:
        bundle, model = _load_mms_model()
        align_fn = lambda wav, words, t_start: _align_with_mms(bundle, model, wav, words, t_start)
    print(f"Model loaded in {time.monotonic()-t0:.1f}s", flush=True)

    # Load Whisper words once per stem
    _whisper_words_cache: dict[str, list[dict]] = {}

    def _get_whisper_words(stem: str) -> list[dict]:
        if stem not in _whisper_words_cache:
            txt_path = TRANSCRIPTS_DIR / f"{stem}.txt"
            if not txt_path.exists():
                _whisper_words_cache[stem] = []
            else:
                data = json.loads(txt_path.read_text())
                words = []
                for seg in data.get("segments", []):
                    for w in seg.get("words", []):
                        if w.get("word", "").strip():
                            words.append({
                                "word": w["word"].strip(),
                                "start": w.get("start", 0.0),
                                "end": w.get("end", 0.0),
                            })
                _whisper_words_cache[stem] = words
        return _whisper_words_cache[stem]

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
            updated.append(row)
            continue

        A_s = row.get("A_s", "").strip()
        if not A_s:
            updated.append(row)
            continue

        last_word_time = float(A_s)
        manifest_path = MANIFESTS_DIR / f"{stem}.json"
        try:
            manifest_data = json.loads(manifest_path.read_text())
            source = _resolve_source(manifest_data)
        except Exception as e:
            print(f"  skip {case_id}: {e}")
            updated.append(row)
            continue

        reel_data = next((r for r in manifest_data.get("reels", []) if r.get("id") == reel_id), None)
        subtitles = (reel_data or {}).get("subtitles", [])
        if reel_data is None or not subtitles:
            updated.append(row)
            continue

        # Alignment window
        t_win_start = max(0.0, last_word_time - WINDOW_SEC)
        t_win_end = last_word_time + WINDOW_SEC
        window_words = [w for w in _get_whisper_words(stem)
                        if w["end"] >= t_win_start and w["start"] <= t_win_end]

        if not window_words:
            print(f"  skip {case_id}: no words in window")
            updated.append(row)
            continue

        print(f"  {case_id}: aligning {len(window_words)} words …", flush=True)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            tmp_wav = Path(tf.name)

        C_val: float | None = None
        try:
            _extract_wav(source, t_win_start, t_win_end, tmp_wav)
            audio_dur = t_win_end - t_win_start
            total_audio_sec += audio_dur

            t1 = time.monotonic()
            aligned_words, unaligned = align_fn(tmp_wav, window_words, t_win_start)
            elapsed = time.monotonic() - t1
            total_wall_sec += elapsed
            all_unaligned.extend(unaligned)

            last_sub = subtitles[-1]
            target = last_sub.get("word", "").strip().lower().rstrip(".,!?")
            for aw in reversed(aligned_words):
                if aw["word"].strip().lower().rstrip(".,!?") == target:
                    C_val = aw["end"]
                    break
            if C_val is None and aligned_words:
                C_val = aligned_words[-1]["end"]
                print(f"    WARNING: text match failed for '{last_sub.get('word', '?')}', "
                      f"using last aligned end {C_val:.3f}s")

            if C_val is not None:
                row = dict(row)
                row["C_s"] = f"{C_val:.3f}"
                A_d = (C_val - float(A_s)) * 1000
                B_s = row.get("B_s", "").strip()
                B_d = (C_val - float(B_s)) * 1000 if B_s else None
                rtf = elapsed / audio_dur
                print(f"    C={C_val:.3f}s  ΔA={A_d:+.0f}ms"
                      + (f"  ΔB={B_d:+.0f}ms" if B_d is not None else "")
                      + f"  RTF={rtf:.2f}x", flush=True)
            else:
                print(f"    no aligned result for {case_id}")
        except Exception as e:
            print(f"    ERROR: {e}")
        finally:
            tmp_wav.unlink(missing_ok=True)

        updated.append(row)

    # Write CSV
    fieldnames = list(rows[0].keys()) if rows else []
    with open(ANSWERS_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(updated)

    # Summary
    print(f"\n--- Alignment summary ---")
    if total_audio_sec > 0:
        print(f"Audio: {total_audio_sec:.0f}s, wall: {total_wall_sec:.1f}s, "
              f"RTF: {total_wall_sec/total_audio_sec:.2f}x "
              f"({total_wall_sec/(total_audio_sec/60):.1f}s/min)")
    if all_unaligned:
        from collections import Counter
        print(f"Unaligned words ({len(all_unaligned)} total):")
        for w, n in Counter(all_unaligned).most_common(20):
            print(f"  {n}× {w!r}")
    else:
        print("No unaligned words.")

    print(f"\nanswers.csv → {ANSWERS_CSV}")
    print("Run 'python3.11 scripts/make_tail_benchmark.py --rebuild-c' to re-inject C clicks.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--case", help="Only this case (e.g. pxl0729_r01)")
    parser.add_argument("--backend", choices=["mms", "hf"], default="mms",
                        help="mms=torchaudio MMS_FA (default), hf=wav2vec2-xlsr-ru via transformers")
    parser.add_argument("--dry-run", action="store_true",
                        help="Check setup, show model download progress, don't run alignment")
    args = parser.parse_args()
    run(only_case=args.case, backend=args.backend, dry_run=args.dry_run)
