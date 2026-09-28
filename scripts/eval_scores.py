#!/usr/bin/env python3
"""Evaluate LLM scoring (M1.6 stage 4) against human-scored blocks in data/blocks_dataset/.

Usage:
    python scripts/eval_scores.py [--dry-run] [--record-fixture]

--dry-run        skip LLM calls, print dataset stats and heuristic metrics only
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
            avg_rank = (i + j + 2) / 2.0
            for k in range(i, j + 1):
                ranks[order[k]] = avg_rank
            i = j + 1
        return ranks

    rx, ry = _rank(x), _rank(y)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    den = ((sum((rx[i] - mx) ** 2 for i in range(n))) * (sum((ry[i] - my) ** 2 for i in range(n)))) ** 0.5
    return num / den if den > 0 else 0.0


def _roc_auc(scores: list[float], labels: list[int]) -> float:
    """ROC AUC via trapezoid rule. labels: 1=positive (human>=80), 0=negative."""
    pos = sum(labels)
    neg = len(labels) - pos
    if pos == 0 or neg == 0:
        return float("nan")
    pairs = sorted(zip(scores, labels), key=lambda x: -x[0])
    tp = fp = prev_tp = prev_fp = 0
    prev_s: float | None = None
    auc = 0.0
    for s, lbl in pairs:
        if s != prev_s and prev_s is not None:
            auc += (fp - prev_fp) * (tp + prev_tp) / 2.0
            prev_fp, prev_tp = fp, tp
        if lbl:
            tp += 1
        else:
            fp += 1
        prev_s = s
    auc += (fp - prev_fp) * (tp + prev_tp) / 2.0
    return auc / (pos * neg)


def _precision_at_k(scores: list[float], labels: list[int], k: int) -> float:
    """Fraction of top-K items (by score) that are positive."""
    if k == 0:
        return float("nan")
    top = sorted(zip(scores, labels), key=lambda x: -x[0])[:k]
    return sum(lbl for _, lbl in top) / k


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


def _load_unscored_from_blocks_json(dataset_rows: list[dict]) -> list[dict]:
    """Return blocks from manifests/*.blocks.json not present in dataset (human_score=0)."""
    ds_ids = {r["block_id"] for r in dataset_rows}
    unscored: list[dict] = []
    manifests_dir = REPO / "manifests"
    sources = sorted(set(r["source"] for r in dataset_rows))
    for src in sources:
        bfile = manifests_dir / f"{src}.blocks.json"
        if not bfile.exists():
            continue
        blocks = json.loads(bfile.read_text(encoding="utf-8"))
        new = 0
        for b in blocks:
            if b["id"] not in ds_ids:
                unscored.append({
                    "source": src,
                    "block_id": b["id"],
                    "start": b.get("start", 0.0),
                    "end": b.get("end", 0.0),
                    "duration": b.get("end", 0.0) - b.get("start", 0.0),
                    "text": "",
                    "human_score": 0,
                    "heuristic_score": b.get("heuristic_score", 0.0),
                    "features": {},
                })
                new += 1
    return unscored


def _print_metrics(label: str, rows: list[dict], llm_scores: dict[str, int] | None = None) -> None:
    n = len(rows)
    human = [float(r["human_score"]) for r in rows]
    heur = [r["heuristic_score"] for r in rows]
    pos_labels = [1 if r["human_score"] >= 80 else 0 for r in rows]
    k = sum(pos_labels)

    print(f"\n--- {label} (n={n}, positives=human>=80: {k}) ---")

    # Heuristic
    heur_spear = _spearman(heur, human)
    heur_auc = _roc_auc(heur, pos_labels)
    heur_p_at_k = _precision_at_k(heur, pos_labels, k)
    print(f"  Heuristic  Spearman r={heur_spear:+.3f}  ROC AUC={heur_auc:.3f}  P@{k}={heur_p_at_k:.2f}")

    if llm_scores is not None:
        llm = [float(llm_scores.get(r["block_id"], 0)) for r in rows]
        llm_spear = _spearman(llm, human)
        llm_auc = _roc_auc(llm, pos_labels)
        llm_p_at_k = _precision_at_k(llm, pos_labels, k)
        print(f"  LLM        Spearman r={llm_spear:+.3f}  ROC AUC={llm_auc:.3f}  P@{k}={llm_p_at_k:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="skip LLM calls")
    parser.add_argument("--record-fixture", action="store_true", help="save first batch raw response")
    args = parser.parse_args()

    rows = _load_dataset()
    sources = sorted(set(r["source"] for r in rows))
    print(f"Dataset: {len(rows)} blocks with human scores across {len(sources)} sources")

    # Distribution
    from collections import Counter
    dist = Counter(r["human_score"] for r in rows)
    dist_str = "  ".join(f"{s}:{c}" for s, c in sorted(dist.items()))
    print(f"  Score distribution: {dist_str}")
    print(f"  Range: {min(dist)} – {max(dist)}  (NO zeros / unscored in dataset)")
    above80 = sum(1 for r in rows if r["human_score"] >= 80)
    above65 = sum(1 for r in rows if r["human_score"] >= 65)
    print(f"  human>=80: {above80}  human>=65: {above65}  total: {len(rows)}")
    print("  NOTE: dataset is TRUNCATED — only blocks human chose to score are present.")
    print("        Near-zero Spearman on scored-only is expected (narrow, high-value range).")

    # Unscored blocks
    unscored = _load_unscored_from_blocks_json(rows)
    print(f"\nUnscored blocks from blocks.json: {len(unscored)} total")
    unscored_by_src = Counter(r["source"] for r in unscored)
    scored_by_src = Counter(r["source"] for r in rows)
    for src in sources:
        bfile = REPO / "manifests" / f"{src}.blocks.json"
        status = "no blocks.json" if not bfile.exists() else f"scored={scored_by_src[src]}, unscored={unscored_by_src.get(src, 0)}"
        print(f"  {src}: {status}")

    v2_rows = rows + unscored
    print(f"\nVariant 2 total: {len(v2_rows)} ({len(rows)} scored + {len(unscored)} unscored as human=0)")

    if args.dry_run:
        print("\n(--dry-run: showing heuristic metrics only)")
        _print_metrics("Variant 1: scored only", rows)
        _print_metrics("Variant 2: scored + unscored (heuristic only)", v2_rows)
        return

    # Load API key from .env if present
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

    from autoreels.cloud.blocks import CandidateBlock
    from autoreels.cloud.providers import GroqLLM
    from autoreels.cloud.score_blocks import (
        SCORE_BATCH_K,
        SCORE_MAX_OUTPUT_TOKENS,
        build_score_messages,
        parse_score_response,
        apply_llm_scores,
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

    all_llm_scores: dict[str, int] = {}
    first_batch_raw: str | None = None
    n_batches = (len(blocks) + SCORE_BATCH_K - 1) // SCORE_BATCH_K

    print(f"\nScoring {len(blocks)} blocks in {n_batches} batches of {SCORE_BATCH_K} (max_output_tokens={SCORE_MAX_OUTPUT_TOKENS})...")
    for i in range(0, len(blocks), SCORE_BATCH_K):
        batch = blocks[i: i + SCORE_BATCH_K]
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
                f"Real LLM response from M1.6 stage 4 scoring call. "
                f"Recorded by eval_scores.py --record-fixture. "
                f"Model: {r0_cfg.model}."
            ),
            "raw": first_batch_raw,
        }
        fixture_path.write_text(json.dumps(fixture_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nFixture saved: {fixture_path}")

    apply_llm_scores(blocks, all_llm_scores)
    print(f"\nLLM returned scores for {len(all_llm_scores)} / {len(rows)} blocks (omitted = LLM score 0)")

    # Variant 1: scored only
    _print_metrics("Variant 1: scored only", rows, all_llm_scores)

    # Variant 2: scored + unscored (unscored get LLM=0 since LLM omits them)
    # LLM scores for unscored blocks = 0 (not in all_llm_scores → defaults to 0)
    _print_metrics("Variant 2: scored + unscored (LLM=0 for unscored)", v2_rows, all_llm_scores)

    # 10 largest LLM vs human disagreements (scored blocks with text)
    matched_rows = [r for r in rows if r["block_id"] in all_llm_scores]
    print(f"\n--- 10 largest LLM vs human disagreements (n_matched={len(matched_rows)}) ---")
    disagreements = sorted(
        matched_rows,
        key=lambda r: abs(all_llm_scores[r["block_id"]] - r["human_score"]),
        reverse=True,
    )[:10]
    for r in disagreements:
        bid = r["block_id"]
        llm_s = all_llm_scores[bid]
        hum_s = r["human_score"]
        diff = llm_s - hum_s
        excerpt = r["text"][:80].replace("\n", " ")
        print(f"  Δ{diff:+4d}  llm={llm_s:3d} human={hum_s:3d}  {excerpt!r}")

    # Verdict based on variant 2 ROC AUC (the fairer metric)
    v2_pos = [1 if r["human_score"] >= 80 else 0 for r in v2_rows]
    v2_heur = [r["heuristic_score"] for r in v2_rows]
    v2_llm = [float(all_llm_scores.get(r["block_id"], 0)) for r in v2_rows]
    heur_auc2 = _roc_auc(v2_heur, v2_pos)
    llm_auc2 = _roc_auc(v2_llm, v2_pos)

    print(f"\n--- Verdict (based on Variant 2 ROC AUC) ---")
    if llm_auc2 > 0.75 and llm_auc2 > heur_auc2 + 0.10:
        verdict = f"LLM STRONG (AUC {llm_auc2:.2f} vs heuristic {heur_auc2:.2f}): use LLM scoring, DROP heuristic."
    elif llm_auc2 > 0.65 and llm_auc2 > heur_auc2:
        verdict = f"LLM BETTER (AUC {llm_auc2:.2f} vs heuristic {heur_auc2:.2f}): use LLM scoring, REWEIGHT heuristic."
    elif heur_auc2 > llm_auc2 + 0.05:
        verdict = f"HEURISTIC BETTER (AUC {heur_auc2:.2f} vs LLM {llm_auc2:.2f}): keep heuristic, LLM scoring optional."
    else:
        verdict = f"COMPARABLE (LLM AUC {llm_auc2:.2f}, heuristic {heur_auc2:.2f}): keep both, monitor."
    print(f"  {verdict}")


if __name__ == "__main__":
    main()
