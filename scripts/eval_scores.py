#!/usr/bin/env python3
"""Evaluate LLM scoring (M1.6 stage 4) against human-scored blocks in data/blocks_dataset/.

Usage:
    python scripts/eval_scores.py [--dry-run] [--record-fixture]

--dry-run        skip LLM calls, print dataset stats only
--record-fixture save first batch raw response to tests/fixtures/score_blocks_response.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def _spearman(x: list[float], y: list[float]) -> float:
    """Spearman rank correlation — no scipy required."""
    n = len(x)
    if n < 2:
        return float("nan")

    def _rank(vals: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: vals[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and vals[order[j + 1]] == vals[order[j]]:
                j += 1
            avg_rank = (i + j + 2) / 2.0  # 1-based
            for k in range(i, j + 1):
                ranks[order[k]] = avg_rank
            i = j + 1
        return ranks

    rx, ry = _rank(x), _rank(y)
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    den_x = sum((rx[i] - mx) ** 2 for i in range(n))
    den_y = sum((ry[i] - my) ** 2 for i in range(n))
    denom = (den_x * den_y) ** 0.5
    return num / denom if denom > 0 else 0.0


def _load_dataset() -> list[dict]:
    rows = []
    for jsonl in sorted((REPO / "data" / "blocks_dataset").glob("*.jsonl")):
        for line in jsonl.open(encoding="utf-8"):
            line = line.strip()
            if line:
                r = json.loads(line)
                if r.get("human_score") is not None:
                    rows.append(r)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="skip LLM calls")
    parser.add_argument("--record-fixture", action="store_true", help="save first batch raw response")
    args = parser.parse_args()

    rows = _load_dataset()
    print(f"Dataset: {len(rows)} blocks with human scores across {len(set(r['source'] for r in rows))} sources")
    score_counts = {}
    for r in rows:
        s = r["human_score"]
        score_counts[s] = score_counts.get(s, 0) + 1
    above80 = sum(1 for r in rows if r["human_score"] >= 80)
    above65 = sum(1 for r in rows if r["human_score"] >= 65)
    print(f"  human>=80: {above80}  human>=65: {above65}  total: {len(rows)}")

    # Heuristic correlation (no LLM needed — available for all rows)
    heur_corr = _spearman(
        [r["heuristic_score"] for r in rows],
        [float(r["human_score"]) for r in rows],
    )
    print(f"\nHeuristic vs human Spearman r = {heur_corr:.3f}  (n={len(rows)})")

    if args.dry_run:
        print("\n(--dry-run: skipping LLM calls)")
        return

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("ERROR: GROQ_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    from autoreels.cloud.blocks import CandidateBlock
    from autoreels.cloud.providers import GroqLLM
    from autoreels.cloud.score_blocks import (
        SCORE_BATCH_K,
        SCORE_MAX_OUTPUT_TOKENS,
        apply_llm_scores,
        build_score_messages,
        parse_score_response,
    )
    from autoreels.cloud.select import _extract_prompt_body
    from autoreels.core.config import load_r0_config

    r0_cfg = load_r0_config(REPO / "config" / "r0.yaml")
    system_text = _extract_prompt_body((REPO / "prompts" / "score_system.md").read_text(encoding="utf-8"))
    fewshot = json.loads((REPO / "prompts" / "score_fewshot.json").read_text(encoding="utf-8"))
    fewshot_examples = fewshot.get("examples", [])

    provider = GroqLLM(
        model=r0_cfg.model,
        api_key=api_key,
        max_output_tokens=SCORE_MAX_OUTPUT_TOKENS,
        reasoning_effort="none",
    )

    blocks = []
    for r in rows:
        b = CandidateBlock(
            id=r["block_id"],
            start=r["start"],
            end=r["end"],
            duration=r["duration"],
            text=r["text"],
            boundary_reason="sentence",
        )
        b.heuristic_score = r["heuristic_score"]
        blocks.append(b)

    id_to_human = {r["block_id"]: r["human_score"] for r in rows}

    all_llm_scores: dict[str, int] = {}
    first_batch_raw: str | None = None
    n_batches = (len(blocks) + SCORE_BATCH_K - 1) // SCORE_BATCH_K

    print(f"\nScoring {len(blocks)} blocks in {n_batches} batches of {SCORE_BATCH_K} (max_output_tokens={SCORE_MAX_OUTPUT_TOKENS})...")
    for i in range(0, len(blocks), SCORE_BATCH_K):
        batch = blocks[i : i + SCORE_BATCH_K]
        batch_num = i // SCORE_BATCH_K + 1
        msgs = build_score_messages(batch, system_text=system_text, fewshot_examples=fewshot_examples)
        print(f"  batch {batch_num}/{n_batches}: {len(batch)} blocks ... ", end="", flush=True)
        try:
            raw = provider.complete(msgs)
        except Exception as e:
            print(f"ERROR: {e}")
            continue
        if i == 0:
            first_batch_raw = raw
        estimated_out_tokens = len(raw) // 4
        print(f"~{estimated_out_tokens} output tokens")
        try:
            entries = parse_score_response(raw)
            scored = {e["id"]: e["score"] for e in entries if "id" in e and "score" in e}
            all_llm_scores.update(scored)
        except ValueError as e:
            print(f"  parse error: {e}")

    if args.record_fixture and first_batch_raw is not None:
        fixture_path = REPO / "tests" / "fixtures" / "score_blocks_response.json"
        fixture_data = {
            "_comment": (
                "Real LLM response from M1.6 stage 4 scoring call. "
                f"Recorded by eval_scores.py --record-fixture. "
                f"Model: {r0_cfg.model}."
            ),
            "raw": first_batch_raw,
        }
        fixture_path.write_text(json.dumps(fixture_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nFixture saved: {fixture_path}")

    apply_llm_scores(blocks, all_llm_scores)

    matched_rows = [r for r in rows if r["block_id"] in all_llm_scores]
    print(f"\nLLM scored {len(all_llm_scores)} / {len(rows)} blocks")

    if len(matched_rows) < 2:
        print("Not enough matched blocks for correlation.")
        return

    llm_scores_list = [float(all_llm_scores[r["block_id"]]) for r in matched_rows]
    human_scores_list = [float(r["human_score"]) for r in matched_rows]
    heur_scores_matched = [r["heuristic_score"] for r in matched_rows]

    llm_corr = _spearman(llm_scores_list, human_scores_list)
    heur_corr_matched = _spearman(heur_scores_matched, human_scores_list)

    print(f"\n--- Correlation (n={len(matched_rows)}) ---")
    print(f"LLM vs human       Spearman r = {llm_corr:.3f}")
    print(f"Heuristic vs human Spearman r = {heur_corr_matched:.3f}  (matched subset)")
    print(f"Heuristic vs human Spearman r = {heur_corr:.3f}  (all {len(rows)} blocks)")

    # Top-K overlap (per source, then aggregate)
    human_good = {r["block_id"] for r in rows if r["human_score"] >= 80}
    k = len(human_good)
    if k > 0:
        llm_topk = set(
            sorted(all_llm_scores, key=lambda bid: -all_llm_scores[bid])[:k]
        )
        heur_topk = set(
            sorted(rows, key=lambda r: -r["heuristic_score"])[:k]
        )
        heur_topk_ids = {r["block_id"] for r in sorted(rows, key=lambda r: -r["heuristic_score"])[:k]}
        llm_overlap = len(llm_topk & human_good) / k
        heur_overlap = len(heur_topk_ids & human_good) / k
        print(f"\n--- Top-{k} overlap (human>=80: {k} blocks) ---")
        print(f"LLM top-{k} overlap:       {llm_overlap:.2f}  ({len(llm_topk & human_good)}/{k})")
        print(f"Heuristic top-{k} overlap: {heur_overlap:.2f}  ({len(heur_topk_ids & human_good)}/{k})")

    # 10 largest disagreements
    disagreements = sorted(
        matched_rows,
        key=lambda r: abs(all_llm_scores[r["block_id"]] - r["human_score"]),
        reverse=True,
    )[:10]
    print(f"\n--- 10 largest LLM vs human disagreements ---")
    for r in disagreements:
        bid = r["block_id"]
        llm_s = all_llm_scores[bid]
        hum_s = r["human_score"]
        diff = llm_s - hum_s
        excerpt = r["text"][:80].replace("\n", " ")
        print(f"  Δ{diff:+4d}  llm={llm_s:3d} human={hum_s:3d}  {excerpt!r}")

    print(f"\n--- Verdict ---")
    if heur_corr < 0.2:
        verdict = "DROP heuristic: worse than random. Switch to LLM scoring."
    elif llm_corr > heur_corr + 0.15:
        verdict = "LLM beats heuristic by >0.15 — keep LLM scoring, REWEIGHT heuristic."
    elif llm_corr > heur_corr:
        verdict = "LLM slightly better — KEEP both, use LLM as primary."
    else:
        verdict = "Heuristic competitive — KEEP heuristic, LLM scoring optional."
    print(f"  {verdict}")


if __name__ == "__main__":
    main()
