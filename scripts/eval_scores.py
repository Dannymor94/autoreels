#!/usr/bin/env python3
"""Evaluate heuristic score correlation with human labels.

By default uses only rows labeled by the owner (labeler="owner" or no labeler field).
Pass --include-assistant to include all rows.
"""
import argparse
import json
import pathlib
import statistics
import sys


def load_rows(ds_dir: pathlib.Path, include_assistant: bool) -> list[dict]:
    rows = []
    for f in sorted(ds_dir.glob("*.jsonl")):
        for line in f.read_text("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            labeler = r.get("labeler", "owner")
            if not include_assistant and labeler != "owner":
                continue
            if "human_score" not in r or "heuristic_score" not in r:
                continue
            rows.append(r)
    return rows


def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return float("nan")
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sx = statistics.stdev(xs)
    sy = statistics.stdev(ys)
    if sx == 0 or sy == 0:
        return float("nan")
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / ((n - 1) * sx * sy)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "ds_dir",
        nargs="?",
        default="data/blocks_dataset",
        help="blocks_dataset directory (default: data/blocks_dataset)",
    )
    parser.add_argument(
        "--include-assistant",
        action="store_true",
        help="include rows labeled by the assistant (excluded by default)",
    )
    args = parser.parse_args()

    ds_dir = pathlib.Path(args.ds_dir)
    if not ds_dir.is_dir():
        print(f"error: {ds_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    rows = load_rows(ds_dir, args.include_assistant)
    if not rows:
        print("no rows found", file=sys.stderr)
        sys.exit(1)

    label = "owner+assistant" if args.include_assistant else "owner"
    print(f"rows: {len(rows)} ({label})")

    by_source: dict[str, list[dict]] = {}
    for r in rows:
        by_source.setdefault(r.get("source", "?"), []).append(r)

    human = [r["human_score"] for r in rows]
    heur = [r["heuristic_score"] for r in rows]
    r_all = pearson(human, heur)
    print(f"\nall sources  n={len(rows):4d}  pearson={r_all:+.3f}")
    print(f"  human  mean={statistics.mean(human):.1f}  sd={statistics.stdev(human):.1f}")
    print(f"  heur   mean={statistics.mean(heur):.1f}  sd={statistics.stdev(heur):.1f}")
    print()

    for src, src_rows in sorted(by_source.items()):
        h = [r["human_score"] for r in src_rows]
        s = [r["heuristic_score"] for r in src_rows]
        r_src = pearson(h, s)
        print(f"  {src:<40s}  n={len(src_rows):3d}  pearson={r_src:+.3f}")


if __name__ == "__main__":
    main()
