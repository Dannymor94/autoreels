#!/usr/bin/env python3
"""Transfer legacy human scores to current blocks by time overlap.

A score is transferred when the overlap covers >= 80% of BOTH the legacy block
and the current block. For spliced legacy clips (block_ids spanning >1 block)
the same rule applies to the splice's full [start, end] range.

Writes: data/transferred_scores.jsonl  (never overwrites existing rows).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATASET_DIR = REPO / "data" / "blocks_dataset"
MANIFESTS_DIR = REPO / "manifests"
OUT = REPO / "data" / "transferred_scores.jsonl"
THRESHOLD = 0.80


def overlap_ratios(ls: float, le: float, cs: float, ce: float) -> tuple[float, float]:
    """Return (overlap/legacy_dur, overlap/current_dur)."""
    ov = max(0.0, min(le, ce) - max(ls, cs))
    r_leg = ov / (le - ls) if le > ls else 0.0
    r_cur = ov / (ce - cs) if ce > cs else 0.0
    return r_leg, r_cur


def transfer_source(
    source: str,
    legacy_rows: list[dict],
    current_blocks: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Return (transferred, skipped_with_reason)."""
    transferred: list[dict] = []
    skipped: list[dict] = []

    for row in legacy_rows:
        ls, le = row["start"], row["end"]
        matched: list[tuple[dict, float, float]] = []

        for b in current_blocks:
            cs, ce = b.get("start", 0.0), b.get("end", 0.0)
            r_leg, r_cur = overlap_ratios(ls, le, cs, ce)
            if r_leg >= THRESHOLD and r_cur >= THRESHOLD:
                matched.append((b, r_leg, r_cur))

        if matched:
            for b, r_leg, r_cur in matched:
                transferred.append({
                    "source": source,
                    "block_id": b["id"],
                    "start": b["start"],
                    "end": b["end"],
                    "duration": b["end"] - b["start"],
                    "human_score": row["human_score"],
                    "heuristic_score": b.get("heuristic_score", 0.0),
                    "features": {},
                    "origin": "transferred",
                    "legacy_block_id": row["block_id"],
                    "overlap_legacy": round(r_leg, 4),
                    "overlap_current": round(r_cur, 4),
                })
        else:
            skipped.append({
                "legacy_block_id": row["block_id"],
                "start": ls,
                "end": le,
                "reason": _skip_reason(ls, le, current_blocks),
            })

    return transferred, skipped


def _skip_reason(ls: float, le: float, blocks: list[dict]) -> str:
    best = 0.0
    for b in blocks:
        cs, ce = b.get("start", 0.0), b.get("end", 0.0)
        r_leg, r_cur = overlap_ratios(ls, le, cs, ce)
        best = max(best, min(r_leg, r_cur))
    if best == 0.0:
        return "no overlap"
    return f"best_min_ratio={best:.2f} < {THRESHOLD}"


def main() -> None:
    # Load already-transferred (source, block_id) pairs for idempotency
    existing: set[tuple[str, str]] = set()
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            line = line.strip()
            if line:
                r = json.loads(line)
                existing.add((r["source"], r["block_id"]))

    all_new: list[dict] = []

    pxl_files = sorted(f for f in DATASET_DIR.glob("*.jsonl") if f.stem.startswith("PXL_20260729"))
    other_files = sorted(f for f in DATASET_DIR.glob("*.jsonl") if f not in pxl_files)

    print("Transfer report:")
    for jsonl_path in pxl_files + other_files:
        source = jsonl_path.stem
        rows = [json.loads(l) for l in jsonl_path.open(encoding="utf-8") if l.strip()]
        legacy_rows = [r for r in rows if r.get("legacy") and r.get("human_score") is not None]

        if not legacy_rows:
            print(f"  {source}: 0 legacy rows — skipped")
            continue

        blocks_path = MANIFESTS_DIR / f"{source}.blocks.json"
        if not blocks_path.exists():
            print(f"  {source}: {len(legacy_rows)} legacy rows, no blocks.json — skipped")
            continue

        current_blocks = json.loads(blocks_path.read_text(encoding="utf-8"))
        transferred, skipped = transfer_source(source, legacy_rows, current_blocks)

        new_rows = [t for t in transferred if (t["source"], t["block_id"]) not in existing]
        all_new.extend(new_rows)

        skip_reasons: dict[str, int] = {}
        for s in skipped:
            skip_reasons[s["reason"]] = skip_reasons.get(s["reason"], 0) + 1
        skip_str = "; ".join(f"{v}× '{k}'" for k, v in skip_reasons.items()) if skipped else "none"

        print(
            f"  {source}: legacy={len(legacy_rows)}, transferred={len(transferred)}, "
            f"skipped={len(skipped)} ({skip_str})"
        )

    if all_new:
        with OUT.open("a", encoding="utf-8") as f:
            for row in all_new:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"\nWrote {len(all_new)} transferred rows → {OUT.relative_to(REPO)}")
    else:
        print("\nNo new transferred rows.")


if __name__ == "__main__":
    main()
