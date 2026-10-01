#!/usr/bin/env python3
"""Generate tail-placement benchmark: audio windows with click markers.

Produces:
  benchmarks/tails/<stem_short>_<reel>.wav   — mono 22050Hz window + click tones
  benchmarks/tails/<stem_short>_<reel>.txt   — sidecar listing click times
  benchmarks/tails/answers.csv               — table for owner annotation

Candidates injected as click tones:
  A = Whisper t1  (523 Hz, C5)
  B = smap audible_end after residue chaining  (880 Hz, A5)
  C = forced-alignment end  (1047 Hz, C6) — added in Part 2 via --rebuild-c

Usage:
  .venv/bin/python scripts/make_tail_benchmark.py
  .venv/bin/python scripts/make_tail_benchmark.py --no-audio   # CSV only
  .venv/bin/python scripts/make_tail_benchmark.py --rebuild-c  # re-inject C after Part 2
"""
from __future__ import annotations
import argparse, csv, json, struct, subprocess, sys, wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from autoreels.core.models import Manifest
from autoreels.local.render import resolve_source

ROOT = Path(__file__).parent.parent
TAILS_DIR = ROOT / "benchmarks" / "tails"
MANIFESTS_DIR = ROOT / "manifests"
TRANSCRIPTS_DIR = ROOT / "transcripts"
INPUTS_DIR = ROOT / "inputs-archive"
ANSWERS_CSV = TAILS_DIR / "answers.csv"

SR = 22050          # output sample rate
CLICK_DUR = 0.05    # seconds per click tone
CLICK_AMP = 0.35    # amplitude relative to int16 max
PRE_PAD = 1.0       # seconds before last_word_t0
POST_PAD = 0.8      # seconds after max candidate

CUT_PAUSE_MIN = 0.35
_TAIL_PAD = 0.10

# (stem_long, short_id, reel_ids)
CASES_DEF: list[tuple[str, str, list[str]]] = [
    ("PXL_20260729_085910095_34f06abf", "pxl0729", [f"r{i:02d}" for i in range(1, 11)]),
    ("2026-08-08 11h 42m 49s",          "lec1142", [f"r{i:02d}" for i in range(1, 6)]),
    ("IMG_6848",                         "img6848", [f"r{i:02d}" for i in range(1, 11)]),
    ("2026-08-08 09h 33m 14s",          "lec0933", ["r01", "r02", "r03"]),
]

CLICK_FREQS = {"A": 523.0, "B": 880.0, "C": 1047.0}


# ---------------------------------------------------------------------------
# smap helpers (residue-chaining logic, mirrored from render.py)
# ---------------------------------------------------------------------------

def _smap_lookup(smap: dict) -> dict[int, tuple[int, dict]]:
    return {round(w["t0"] * 1000): (i, w) for i, w in enumerate(smap["words"])}


def _smap_ae_after_residue(last_t0: float, last_t1: float | None,
                            smap: dict, lookup: dict) -> tuple[float | None, int]:
    """Return (audible_end after residue chaining, final word_idx).

    Mirrors the residue-attribution block in _tail_from_smap.
    """
    key = round(last_t0 * 1000)
    if key not in lookup:
        return None, -1
    word_idx, word_entry = lookup[key]
    audible_end: float = word_entry["audible_end"]
    words = smap["words"]
    if last_t1 is not None:
        while word_idx + 1 < len(words):
            nxt = words[word_idx + 1]
            if not (nxt["t0"] <= last_t1
                    and nxt.get("audible_start", nxt["t0"]) < audible_end + 0.04):
                break
            word_idx += 1
            audible_end = max(audible_end, words[word_idx]["audible_end"])
    return audible_end, word_idx


def _next_speech_onset(word_idx: int, smap: dict) -> float | None:
    words = smap["words"]
    boundaries = smap.get("boundaries", [])
    onset: float | None = None
    if word_idx < len(boundaries):
        bnd = boundaries[word_idx]
        untr = bnd.get("untranscribed_speech", [])
        if untr:
            onset = untr[0][0]
    if word_idx + 1 < len(words):
        nxt_as = words[word_idx + 1]["audible_start"]
        if onset is None or nxt_as < onset:
            onset = nxt_as
    return onset


def _smap_render_end(audible_end: float, next_onset: float | None) -> float:
    """Compute what _tail_from_smap would return (silence / speech-next rule)."""
    if next_onset is None:
        return audible_end + _TAIL_PAD
    gap = next_onset - audible_end
    if gap >= CUT_PAUSE_MIN:
        cap = max(audible_end + 0.04, next_onset - _TAIL_PAD)
        return min(audible_end + _TAIL_PAD, cap)
    else:
        new_end = next_onset - _TAIL_PAD
        new_end = max(new_end, audible_end + 0.04)
        return min(new_end, next_onset)


# ---------------------------------------------------------------------------
# Audio utilities
# ---------------------------------------------------------------------------

def _extract_pcm(source: Path, t_start: float, t_end: float) -> np.ndarray:
    """Extract mono 16-bit PCM from source at SR sample rate."""
    dur = max(t_end - t_start, 0.1)
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", f"{t_start:.6f}", "-t", f"{dur:.6f}",
            "-i", str(source),
            "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "pipe:1",
        ],
        capture_output=True, check=True,
    )
    return np.frombuffer(result.stdout, dtype=np.int16).copy()


def _add_click(audio: np.ndarray, t_offset: float, freq: float) -> None:
    """Mix a sine-tone click into audio at t_offset seconds (in-place)."""
    if t_offset < 0:
        return
    n = int(CLICK_DUR * SR)
    t = np.arange(n) / SR
    fade = max(1, int(0.005 * SR))
    env = np.ones(n, dtype=np.float32)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    click = (CLICK_AMP * 32767 * env * np.sin(2 * np.pi * freq * t)).astype(np.int32)

    start = int(t_offset * SR)
    end = min(start + n, len(audio))
    n_actual = end - start
    if start >= len(audio) or n_actual <= 0:
        return
    audio[start:end] = np.clip(
        audio[start:end].astype(np.int32) + click[:n_actual], -32768, 32767
    ).astype(np.int16)


def _write_wav(path: Path, audio: np.ndarray) -> None:
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(SR)
        wf.writeframes(audio.tobytes())


# ---------------------------------------------------------------------------
# Case data extraction
# ---------------------------------------------------------------------------

def _collect_case_data(stem: str, reel_id: str, smap: dict, manifest: Manifest,
                       source: Path) -> dict:
    """Return all fields needed for one benchmark case."""
    reel = next(r for r in manifest.reels if r.id == reel_id)
    subs = reel.subtitles or []
    if not subs:
        raise ValueError(f"{stem}/{reel_id}: no subtitles")

    last_sub = subs[-1]
    last_t0: float = last_sub.t0
    last_t1: float = last_sub.t1

    # Candidate A: raw Whisper t1 — from the subtitle word, which inherits it from the
    # transcript cache (data/cache/*.transcript.json).  tail_last_word_end is smap-based
    # (map audible_end) and equals B in most cases; we must NOT use it for A.
    A = last_t1

    # Candidate B: smap audible_end after residue chaining
    lkp = _smap_lookup(smap)
    ae_B, w_idx = _smap_ae_after_residue(last_t0, last_t1, smap, lkp)
    B = ae_B  # None if word not found in smap

    next_onset = _next_speech_onset(w_idx, smap) if w_idx >= 0 else None

    # Current render-end rule
    render_end = _smap_render_end(ae_B, next_onset) if ae_B is not None else None

    # Gap classification
    if ae_B is not None and next_onset is not None:
        gap = next_onset - ae_B
        gap_type = "silence" if gap >= CUT_PAUSE_MIN else "speech_next"
    elif ae_B is not None:
        gap_type = "silence_last"
    else:
        gap_type = "smap_miss"

    return {
        "last_word": last_sub.word,
        "last_t0": last_t0,
        "last_t1": last_t1,
        "A": A,
        "B": B,
        "C": None,
        "render_end": render_end,
        "next_onset": next_onset,
        "gap_type": gap_type,
        "source": source,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(no_audio: bool = False, rebuild_c: bool = False) -> None:
    TAILS_DIR.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []

    for stem, short_id, reel_ids in CASES_DEF:
        manifest_path = MANIFESTS_DIR / f"{stem}.json"
        if not manifest_path.exists():
            print(f"  skip {stem}: no manifest", flush=True)
            continue

        smap_path = TRANSCRIPTS_DIR / f"{stem}.speechmap.json"
        if not smap_path.exists():
            print(f"  skip {stem}: no speechmap", flush=True)
            continue

        manifest = Manifest.model_validate_json(manifest_path.read_text())
        smap = json.loads(smap_path.read_text())

        try:
            source = resolve_source(manifest, INPUTS_DIR)
        except Exception:
            # Fallback: try main-repo inputs-archive
            alt_inputs = ROOT.parent / "autoreels" / "inputs-archive"
            try:
                source = resolve_source(manifest, alt_inputs)
            except Exception as e:
                print(f"  skip {stem}: {e}", flush=True)
                continue

        manifest_reel_ids = {r.id for r in manifest.reels}
        for reel_id in reel_ids:
            if reel_id not in manifest_reel_ids:
                print(f"  skip {short_id}_{reel_id}: reel not in manifest", flush=True)
                continue

            case_id = f"{short_id}_{reel_id}"
            try:
                d = _collect_case_data(stem, reel_id, smap, manifest, source)
            except Exception as e:
                print(f"  skip {case_id}: {e}", flush=True)
                continue

            A, B, C = d["A"], d["B"], d["C"]
            render_end = d["render_end"]
            last_t0 = d["last_t0"]

            # Window: last_word_t0 - PRE_PAD  →  max_candidate + POST_PAD
            candidates = [x for x in (A, B, C, render_end) if x is not None]
            t_start = max(0.0, last_t0 - PRE_PAD)
            t_end = max(candidates) + POST_PAD if candidates else last_t0 + 2.0

            # Check for existing C in answers.csv (for --rebuild-c)
            existing_c = None
            if rebuild_c and ANSWERS_CSV.exists():
                with open(ANSWERS_CSV) as f:
                    for row in csv.DictReader(f):
                        if row["case"] == case_id and row.get("C_s", "").strip():
                            try:
                                existing_c = float(row["C_s"])
                            except ValueError:
                                pass
            if existing_c is not None:
                C = d["C"] = existing_c
                t_end = max(t_end, C + POST_PAD)

            wav_path = TAILS_DIR / f"{case_id}.wav"
            txt_path = TAILS_DIR / f"{case_id}.txt"

            if not no_audio:
                print(f"  {case_id}: extract {t_start:.2f}–{t_end:.2f}s ...", flush=True)
                try:
                    audio = _extract_pcm(d["source"], t_start, t_end)
                except subprocess.CalledProcessError as e:
                    print(f"    ERROR: {e}", flush=True)
                    continue

                for label, val in (("A", A), ("B", B), ("C", C)):
                    if val is None:
                        continue
                    offset = val - t_start
                    _add_click(audio, offset, CLICK_FREQS[label])

                _write_wav(wav_path, audio)

            # Sidecar
            lines = [
                f"case: {case_id}",
                f"last_word: {d['last_word']}",
                f"window: {t_start:.3f} – {t_end:.3f} s (source time)",
                "",
                f"A (Whisper t1)         = {A:.3f} s  [offset +{A - t_start:.3f} s]  — 523 Hz" if A else "A = N/A",
                f"B (smap audible_end)   = {B:.3f} s  [offset +{B - t_start:.3f} s]  — 880 Hz" if B else "B = N/A",
                f"C (forced alignment)   = {C:.3f} s  [offset +{C - t_start:.3f} s]  — 1047 Hz" if C else "C = not yet",
                "",
                f"render_end (current)   = {render_end:.3f} s" if render_end else "render_end = N/A",
                f"next_onset             = {d['next_onset']:.3f} s" if d['next_onset'] else "next_onset = none",
                f"gap_type               = {d['gap_type']}",
            ]
            txt_path.write_text("\n".join(lines) + "\n")

            rows.append({
                "case": case_id,
                "stem": short_id,
                "reel": reel_id,
                "last_word": d["last_word"],
                "A_s": f"{A:.3f}" if A is not None else "",
                "B_s": f"{B:.3f}" if B is not None else "",
                "C_s": f"{C:.3f}" if C is not None else "",
                "render_end_s": f"{render_end:.3f}" if render_end is not None else "",
                "next_onset_s": f"{d['next_onset']:.3f}" if d["next_onset"] is not None else "",
                "gap_type": d["gap_type"],
                "owner_choice": "",
                "notes": "",
            })

    # Write answers.csv (merge owner_choice from existing if present)
    existing_choices: dict[str, tuple[str, str]] = {}
    if ANSWERS_CSV.exists():
        with open(ANSWERS_CSV) as f:
            for row in csv.DictReader(f):
                if row.get("owner_choice") or row.get("notes"):
                    existing_choices[row["case"]] = (
                        row.get("owner_choice", ""), row.get("notes", "")
                    )
    for row in rows:
        if row["case"] in existing_choices:
            row["owner_choice"], row["notes"] = existing_choices[row["case"]]

    with open(ANSWERS_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "case", "stem", "reel", "last_word",
            "A_s", "B_s", "C_s", "render_end_s", "next_onset_s",
            "gap_type", "owner_choice", "notes",
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n{len(rows)} cases written → {TAILS_DIR}", flush=True)
    print(f"answers.csv → {ANSWERS_CSV}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-audio", action="store_true",
                        help="Generate CSV/sidecar only, skip audio extraction")
    parser.add_argument("--rebuild-c", action="store_true",
                        help="Re-inject C clicks from existing answers.csv C_s column")
    args = parser.parse_args()
    run(no_audio=args.no_audio, rebuild_c=args.rebuild_c)
