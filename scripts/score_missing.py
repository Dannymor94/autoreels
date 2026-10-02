#!/usr/bin/env python3
"""Score blocks missing from llm_scores_cache.json and add them to the cache.

Uses the same prompt / temperature=0 as eval_scores.py.
Stops immediately on quota exhaustion (ValueError from provider).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

DATASET_DIR = REPO / "data" / "blocks_dataset"
TRANSFERRED_FILE = REPO / "data" / "transferred_scores.jsonl"
CACHE_FILE = REPO / "data" / "llm_scores_cache.json"
TRANSCRIPT_CACHE = Path("/Users/danny/Documents/autoreels/data/cache")

SOURCE_TRANSCRIPTS: dict[str, str] = {
    "2026-08-08 09h 33m 14s": "1e0411048f8473fc16e751fd0d867fcdcc21b99dca5d2fb53ec4765f8498b265.84b62c5276da.transcript.json",
    "2026-08-08 11h 42m 49s": "1ce8e4bb59457f6dd9ee1123e82434588b09e1a2861023974e5300bf62c1bb9b.84b62c5276da.transcript.json",
    "IMG_6848": "f4c1351fe015d10963ec8980f637b4c5f24b121742f6c9b4a45f6fe7bb69d2a9.84b62c5276da.transcript.json",
    "PXL_20260729_085910095_34f06abf": "72a9c86750fd1c5f01b1c84cbb574c8b4c9dfcd4b8f532aa0973c5087c0fea0f.84b62c5276da.transcript.json",
    "Pxl 20260621 112938952": "7e7d7bdcf9abdf1902d56dc59d751f3ebe5be07bd5502b277fc9d9b50d128538.84b62c5276da.transcript.json",
    "Pxl 20260621 122006193": "68052c97ab31af254fca037f7be12277cdf853877fd33a583741b5edda673d6a.84b62c5276da.transcript.json",
}


def _load_words(src: str) -> list[dict]:
    fname = SOURCE_TRANSCRIPTS.get(src)
    if not fname:
        return []
    path = TRANSCRIPT_CACHE / fname
    if not path.exists():
        return []
    tr = json.loads(path.read_text(encoding="utf-8"))
    return tr.get("words", [])


def _extract_text(words: list[dict], start: float, end: float) -> str:
    span = [w["word"] for w in words if w["t0"] >= start - 0.3 and w["t1"] <= end + 0.3]
    return " ".join(span).strip()


def _load_missing_blocks(cache: dict) -> list[dict]:
    rows: list[dict] = []
    # clean rows
    for jsonl in sorted(DATASET_DIR.glob("*.jsonl")):
        for line in jsonl.open(encoding="utf-8"):
            line = line.strip()
            if line:
                r = json.loads(line)
                if r.get("human_score") is not None and not r.get("legacy"):
                    rows.append(r)
    # transferred rows (deduplicated)
    existing_ids = {r["block_id"] for r in rows}
    if TRANSFERRED_FILE.exists():
        for line in TRANSFERRED_FILE.open(encoding="utf-8"):
            line = line.strip()
            if line:
                r = json.loads(line)
                if r["block_id"] not in existing_ids:
                    rows.append(r)

    missing = [r for r in rows if r["block_id"] not in cache]

    # Fill text for rows that lack it (transferred rows)
    words_cache: dict[str, list[dict]] = {}
    for r in missing:
        if not r.get("text"):
            src = r["source"]
            if src not in words_cache:
                words_cache[src] = _load_words(src)
            r["text"] = _extract_text(words_cache[src], r["start"], r["end"])

    return missing


def main() -> None:
    # Load .env
    env_file = REPO / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("ERROR: GROQ_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    cache: dict[str, float] = {}
    if CACHE_FILE.exists():
        cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    print(f"Cache: {len(cache)} entries before scoring")

    missing = _load_missing_blocks(cache)
    print(f"Blocks to score: {len(missing)}")
    if not missing:
        print("Nothing to do.")
        return

    # Check texts
    no_text = [r for r in missing if not r.get("text")]
    if no_text:
        print(f"WARNING: {len(no_text)} blocks have no text, will be skipped by scorer:")
        for r in no_text:
            print(f"  {r['block_id']}  {r['source']}")

    import autoreels.cloud.providers as _prov_mod
    _prov_mod._POOL_BUDGET_SEC = 1800.0

    from autoreels.cloud.blocks import CandidateBlock
    from autoreels.cloud.providers import build_pool
    from autoreels.cloud.score_blocks import SCORE_BATCH_K, score_blocks_batch
    from autoreels.cloud.select import _extract_prompt_body
    from autoreels.core.config import load_r0_config

    r0_cfg = load_r0_config(REPO / "config" / "r0.yaml")
    system_text = _extract_prompt_body((REPO / "prompts" / "score_system.md").read_text(encoding="utf-8"))
    fewshot_examples = json.loads((REPO / "prompts" / "score_fewshot.json").read_text(encoding="utf-8")).get("examples", [])
    provider = build_pool(r0_cfg)

    blocks = []
    for r in missing:
        if not r.get("text"):
            continue
        b = CandidateBlock(
            id=r["block_id"],
            start=r["start"],
            end=r["end"],
            duration=r["duration"],
            text=r["text"],
            boundary_reason="sentence",
        )
        b.heuristic_score = r.get("heuristic_score", 0.0)
        blocks.append(b)

    n_batches = (len(blocks) + SCORE_BATCH_K - 1) // SCORE_BATCH_K
    print(f"Scoring {len(blocks)} blocks in {n_batches} batches (k={SCORE_BATCH_K}, temperature=0)...")

    new_scores: dict[str, int] = {}
    for i in range(0, len(blocks), SCORE_BATCH_K):
        batch = blocks[i : i + SCORE_BATCH_K]
        batch_num = i // SCORE_BATCH_K + 1
        print(f"  batch {batch_num}/{n_batches}: {len(batch)} blocks ... ", end="", flush=True)
        try:
            scores = score_blocks_batch(
                batch,
                provider=provider,
                system_text=system_text,
                fewshot_examples=fewshot_examples,
                temperature=0.0,
            )
            new_scores.update(scores)
            missing_ids = [b.id for b in batch if b.id not in scores]
            suffix = f" (missing: {missing_ids})" if missing_ids else ""
            print(f"{len(scores)}/{len(batch)} scored{suffix}", flush=True)
        except ValueError as e:
            print(f"QUOTA/ERROR: {e}", flush=True)
            print("STOPPING — quota exhausted.")
            break

    if new_scores:
        cache.update({k: float(v) for k, v in new_scores.items()})
        CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nAdded {len(new_scores)} scores to cache ({len(cache)} total)")
    else:
        print("\nNo scores obtained.")


if __name__ == "__main__":
    main()
