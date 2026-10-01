#!/usr/bin/env python3
"""Score tail-placement methods against owner-annotated answers.

Reads benchmarks/tails/answers.csv (filled by owner: owner_choice column).
Computes per-method statistics:
  - mean / median |error| in ms
  - share within 50 / 100 / 200 ms
  - how many cases each method would CUT (end before true end) vs leave extra
  - cases where method has no value (smap miss, etc.)

owner_choice format (from owner_choice column):
  "A"           — the click labelled A is the true end
  "B"           — click B
  "C"           — click C
  "1250"        — explicit ms offset from window start (or absolute source time if > 10000)
  "+120"        — true end is 120 ms AFTER the nearest known click (specify which in notes)
  "-80"         — 80 ms BEFORE nearest click
  ""            — no answer yet (row skipped)

Usage:
  .venv/bin/python scripts/eval_tails.py
  .venv/bin/python scripts/eval_tails.py --csv path/to/answers.csv
"""
from __future__ import annotations
import argparse, csv, statistics
from pathlib import Path

ROOT = Path(__file__).parent.parent
DEFAULT_CSV = ROOT / "benchmarks" / "tails" / "answers.csv"

METHODS = ["A", "B", "C", "render_end"]
METHOD_COLS = {"A": "A_s", "B": "B_s", "C": "C_s", "render_end": "render_end_s"}


def _parse_owner_choice(row: dict) -> float | None:
    """Parse owner_choice to absolute source-time seconds. Returns None if unclear."""
    choice = row.get("owner_choice", "").strip()
    if not choice:
        return None

    col_map = {"A": "A_s", "B": "B_s", "C": "C_s"}
    if choice.upper() in col_map:
        val = row.get(col_map[choice.upper()], "").strip()
        return float(val) if val else None

    try:
        return float(choice)
    except ValueError:
        return None


def _stats(errors_ms: list[float], cut_flags: list[bool]) -> dict:
    if not errors_ms:
        return {"n": 0, "mean": None, "median": None,
                "within_50": None, "within_100": None, "within_200": None,
                "cut": None, "extra": None}
    n = len(errors_ms)
    cuts = sum(cut_flags)
    return {
        "n": n,
        "mean": statistics.mean(errors_ms),
        "median": statistics.median(errors_ms),
        "within_50":  sum(e <= 50  for e in errors_ms) / n,
        "within_100": sum(e <= 100 for e in errors_ms) / n,
        "within_200": sum(e <= 200 for e in errors_ms) / n,
        "cut":   cuts,
        "extra": n - cuts,
    }


def run(csv_path: Path) -> None:
    if not csv_path.exists():
        print(f"answers.csv not found: {csv_path}")
        print("Run scripts/make_tail_benchmark.py first.")
        return

    rows = list(csv.DictReader(open(csv_path)))
    answered = [r for r in rows if _parse_owner_choice(r) is not None]

    print(f"Total cases: {len(rows)}")
    print(f"Answered:    {len(answered)}")
    if not answered:
        print("No answers yet — fill owner_choice column and re-run.")
        return

    method_errors: dict[str, list[float]] = {m: [] for m in METHODS}
    method_cuts:   dict[str, list[bool]]  = {m: [] for m in METHODS}
    method_missing: dict[str, int]        = {m: 0  for m in METHODS}

    for row in answered:
        true_end = _parse_owner_choice(row)
        for method in METHODS:
            col = METHOD_COLS[method]
            val_str = row.get(col, "").strip()
            if not val_str:
                method_missing[method] += 1
                continue
            pred = float(val_str)
            err_ms = abs(pred - true_end) * 1000
            method_errors[method].append(err_ms)
            method_cuts[method].append(pred < true_end)

    # Print table
    col_w = 14
    header = f"{'method':<12} {'n':>4} {'mean ms':>{col_w}} {'med ms':>{col_w}}"
    header += f" {'≤50ms':>{col_w}} {'≤100ms':>{col_w}} {'≤200ms':>{col_w}}"
    header += f" {'CUT':>5} {'extra':>5} {'miss':>5}"
    print()
    print(header)
    print("-" * len(header))

    for method in METHODS:
        s = _stats(method_errors[method], method_cuts[method])
        if s["n"] == 0:
            print(f"{method:<12} {'—':>4}")
            continue
        row_str = f"{method:<12} {s['n']:>4}"
        row_str += f" {s['mean']:>{col_w}.1f}"
        row_str += f" {s['median']:>{col_w}.1f}"
        row_str += f" {s['within_50']:>{col_w}.0%}"
        row_str += f" {s['within_100']:>{col_w}.0%}"
        row_str += f" {s['within_200']:>{col_w}.0%}"
        row_str += f" {s['cut']:>5}"
        row_str += f" {s['extra']:>5}"
        row_str += f" {method_missing[method]:>5}"
        print(row_str)

    print()
    print("CUT = method ends before true end (clips last word)")
    print("extra = method ends after true end (dead air)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=str(DEFAULT_CSV))
    args = parser.parse_args()
    run(Path(args.csv))
