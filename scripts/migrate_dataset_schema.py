"""Migrate existing data/blocks_dataset/*.jsonl to the new schema (v2).

New fields per row:
  block_ids      list[str]         constituent block IDs (1 for single; >1 for splice)
  block_durations dict[str,float]  each constituent block's own duration
  segmentation_fingerprint str|null  _block_fingerprint(kept) at time of review export
  legacy         bool              True when fingerprint can't be verified (exclude from eval)

Migration rules:
  - block_id found in current blocks.json AND source has 100% ID overlap → clean
  - block_id found in current blocks.json but source has partial overlap → partial
      (scored block is from correct segmentation, but unscored set may be contaminated)
  - block_id NOT in current blocks.json (splice/merge) → legacy=True
  - PXL_20260729: all legacy (segmentation was regenerated, 33% overlap)

Run once; safe to re-run (idempotent — only adds missing fields, does not overwrite existing).
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).parent.parent
DS_DIR = REPO / "data" / "blocks_dataset"
MANIFESTS = REPO / "manifests"


def _blocks_fingerprint(block_ids: list[str]) -> str:
    import hashlib
    data = "|".join(block_ids).encode()
    return hashlib.sha1(data).hexdigest()[:16]


def _load_blocks_json(stem: str) -> dict[str, dict] | None:
    """Return {block_id: row} from <stem>.blocks.json, or None if not found."""
    path = MANIFESTS / f"{stem}.blocks.json"
    if not path.exists():
        return None
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {r["id"]: r for r in rows}


def _compute_fingerprint(blocks: dict[str, dict], verdict_filter="KEPT") -> str:
    kept_ids = [b["id"] for b in sorted(blocks.values(), key=lambda x: x["start"])
                if b.get("verdict", "KEPT") == verdict_filter or verdict_filter is None]
    return _blocks_fingerprint(kept_ids)


# Source → stem in manifests/  (dataset stem → blocks.json stem)
_SOURCE_TO_BJ_STEM: dict[str, str] = {
    "2026-08-08 09h 33m 14s": "2026-08-08 09h 33m 14s",
    "2026-08-08 11h 42m 49s": "2026-08-08 11h 42m 49s",
    "IMG_6848": "IMG_6848",
    "Pxl 20260621 112938952": "Pxl 20260621 112938952",
    "Pxl 20260621 122006193": "Pxl 20260621 122006193",
    "PXL_20260729_085910095_34f06abf": "PXL_20260729_085910095_34f06abf",
}

# Sources where the blocks.json segmentation is known to match what the human saw.
# Verified by 100% block ID overlap between dataset and current blocks.json.
_CLEAN_SOURCES = {"2026-08-08 09h 33m 14s"}

# Sources where segmentation was regenerated (low overlap → all rows legacy).
_FULLY_LEGACY_SOURCES = {"PXL_20260729_085910095_34f06abf"}


def migrate_file(jsonl_path: Path, dry_run: bool = False) -> tuple[int, int, int]:
    """Migrate one .jsonl file. Returns (total, updated, legacy)."""
    source_stem = jsonl_path.stem
    bj_stem = _SOURCE_TO_BJ_STEM.get(source_stem)
    blocks_map = _load_blocks_json(bj_stem) if bj_stem else None

    # Compute fingerprint from KEPT blocks only
    fp: str | None = None
    if blocks_map:
        kept_ids = [v["id"] for v in sorted(blocks_map.values(), key=lambda x: x["start"])
                    if v.get("verdict", "KEPT") == "KEPT"]
        fp = _blocks_fingerprint(kept_ids)

    rows = [json.loads(l) for l in jsonl_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    total = len(rows)
    updated = 0
    legacy_count = 0

    out_rows = []
    for row in rows:
        changed = False
        bid = row["block_id"]

        # Skip rows that already have the new schema
        if "block_ids" not in row:
            row["block_ids"] = [bid]
            changed = True

        if "block_durations" not in row:
            # Try to get individual duration from blocks.json
            if blocks_map and bid in blocks_map:
                bj_row = blocks_map[bid]
                ind_dur = round(bj_row["end"] - bj_row["start"], 3)
            else:
                ind_dur = row["duration"]  # best we have (may be spliced)
            row["block_durations"] = {bid: ind_dur}
            changed = True

        if "segmentation_fingerprint" not in row:
            row["segmentation_fingerprint"] = fp
            changed = True

        if "legacy" not in row:
            is_fully_legacy = source_stem in _FULLY_LEGACY_SOURCES
            id_found_in_bj = blocks_map is not None and bid in blocks_map
            is_splice = not id_found_in_bj and blocks_map is not None
            row["legacy"] = is_fully_legacy or is_splice
            changed = True

        if row.get("legacy"):
            legacy_count += 1
        if changed:
            updated += 1

        out_rows.append(row)

    if not dry_run and updated > 0:
        with jsonl_path.open("w", encoding="utf-8") as f:
            for r in out_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    return total, updated, legacy_count


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    jsonl_files = sorted(DS_DIR.glob("*.jsonl"))
    if not jsonl_files:
        print("No .jsonl files found in", DS_DIR)
        return

    grand_total = grand_updated = grand_legacy = 0
    for path in jsonl_files:
        total, updated, legacy = migrate_file(path, dry_run=args.dry_run)
        tag = "(dry)" if args.dry_run else ""
        print(f"  {path.stem}: {total} rows, {updated} updated{tag}, {legacy} legacy")
        grand_total += total
        grand_updated += updated
        grand_legacy += legacy

    print(f"\nTotal: {grand_total} rows, {grand_updated} updated, {grand_legacy} legacy")
    if args.dry_run:
        print("(dry run — no files written)")


if __name__ == "__main__":
    main()
