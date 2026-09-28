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

TRANSCRIPT_CACHE = Path("/Users/danny/Documents/autoreels/data/cache")

# transcript filename for each source (located by source_sha256 or content match)
SOURCE_TRANSCRIPTS: dict[str, str] = {
    "2026-08-08 09h 33m 14s": "1e0411048f8473fc16e751fd0d867fcdcc21b99dca5d2fb53ec4765f8498b265.84b62c5276da.transcript.json",
    "2026-08-08 11h 42m 49s": "1ce8e4bb59457f6dd9ee1123e82434588b09e1a2861023974e5300bf62c1bb9b.84b62c5276da.transcript.json",
    "IMG_6848": "f4c1351fe015d10963ec8980f637b4c5f24b121742f6c9b4a45f6fe7bb69d2a9.84b62c5276da.transcript.json",
    "PXL_20260729_085910095_34f06abf": "72a9c86750fd1c5f01b1c84cbb574c8b4c9dfcd4b8f532aa0973c5087c0fea0f.84b62c5276da.transcript.json",
    "Pxl 20260621 112938952": "7e7d7bdcf9abdf1902d56dc59d751f3ebe5be07bd5502b277fc9d9b50d128538.84b62c5276da.transcript.json",
    "Pxl 20260621 122006193": "68052c97ab31af254fca037f7be12277cdf853877fd33a583741b5edda673d6a.84b62c5276da.transcript.json",
}


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
    """ROC AUC via trapezoid rule. labels: 1=positive, 0=negative."""
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


def _load_transcripts() -> dict[str, list[dict]]:
    """Return {source: [word_dict, ...]} for all sources with a known transcript."""
    result: dict[str, list[dict]] = {}
    for src, fname in SOURCE_TRANSCRIPTS.items():
        path = TRANSCRIPT_CACHE / fname
        if not path.exists():
            print(f"  WARNING: transcript not found for {src}: {fname}")
            continue
        tr = json.loads(path.read_text(encoding="utf-8"))
        result[src] = tr.get("words", [])
    return result


def _extract_block_text(words: list[dict], start: float, end: float) -> str:
    """Join word text for words overlapping [start, end]."""
    span = [w["word"] for w in words if w["t0"] >= start - 0.3 and w["t1"] <= end + 0.3]
    return " ".join(span).strip()


def _overlap_fraction(s1: float, e1: float, s2: float, e2: float) -> float:
    """Fraction of [s1,e1] that overlaps [s2,e2]."""
    dur = e1 - s1
    if dur <= 0:
        return 0.0
    overlap = max(0.0, min(e1, e2) - max(s1, s2))
    return overlap / dur


def _load_unscored_blocks(
    dataset_rows: list[dict],
    transcripts: dict[str, list[dict]],
) -> tuple[list[dict], int]:
    """Load unscored blocks from manifests/*.blocks.json, extract text, filter splices.

    Returns (unscored_rows, n_splice_excluded).
    A block is considered a splice component if >50% of its duration overlaps with
    any scored block from the same source.
    """
    ds_ids = {r["block_id"] for r in dataset_rows}

    # Build scored intervals per source for splice detection
    scored_intervals: dict[str, list[tuple[float, float]]] = {}
    for r in dataset_rows:
        scored_intervals.setdefault(r["source"], []).append((r["start"], r["end"]))

    manifests_dir = REPO / "manifests"
    sources = sorted(set(r["source"] for r in dataset_rows))

    unscored: list[dict] = []
    n_splice = 0
    n_no_text = 0

    for src in sources:
        bfile = manifests_dir / f"{src}.blocks.json"
        if not bfile.exists():
            continue
        blocks = json.loads(bfile.read_text(encoding="utf-8"))
        words = transcripts.get(src, [])
        src_intervals = scored_intervals.get(src, [])

        for b in blocks:
            if b["id"] in ds_ids:
                continue
            bstart, bend = b.get("start", 0.0), b.get("end", 0.0)
            # Splice filter: skip if >50% covered by a scored block
            max_overlap = max(
                (_overlap_fraction(bstart, bend, s, e) for s, e in src_intervals),
                default=0.0,
            )
            if max_overlap > 0.5:
                n_splice += 1
                continue
            # Extract text from transcript
            text = _extract_block_text(words, bstart, bend) if words else ""
            if not text:
                n_no_text += 1
                continue
            unscored.append({
                "source": src,
                "block_id": b["id"],
                "start": bstart,
                "end": bend,
                "duration": bend - bstart,
                "text": text,
                "human_score": 0,
                "heuristic_score": b.get("heuristic_score", 0.0),
                "features": {},
            })

    if n_splice:
        print(f"  Splice-filtered (overlap >50% with scored block): {n_splice}")
    if n_no_text:
        print(f"  Dropped (no text extracted): {n_no_text}")
    return unscored, n_splice


def _print_metrics(
    label: str,
    rows: list[dict],
    llm_scores: dict[str, int] | None = None,
    *,
    scored_only_label: str = "human>=80",
    also_any_scored: bool = False,
) -> None:
    n = len(rows)
    human = [float(r["human_score"]) for r in rows]
    heur = [r["heuristic_score"] for r in rows]
    pos80 = [1 if r["human_score"] >= 80 else 0 for r in rows]
    k80 = sum(pos80)

    print(f"\n--- {label} (n={n}, human>=80: {k80}) ---")

    heur_spear = _spearman(heur, human)
    heur_auc80 = _roc_auc(heur, pos80)
    heur_p80 = _precision_at_k(heur, pos80, k80)
    print(f"  Heuristic  Spearman r={heur_spear:+.3f}  AUC(>=80)={heur_auc80:.3f}  P@{k80}={heur_p80:.2f}")

    if also_any_scored:
        pos_any = [1 if r["human_score"] > 0 else 0 for r in rows]
        heur_auc_any = _roc_auc(heur, pos_any)
        print(f"  Heuristic  AUC(any scored vs unscored)={heur_auc_any:.3f}")

    if llm_scores is not None:
        llm = [float(llm_scores.get(r["block_id"], 0)) for r in rows]
        llm_spear = _spearman(llm, human)
        llm_auc80 = _roc_auc(llm, pos80)
        llm_p80 = _precision_at_k(llm, pos80, k80)
        print(f"  LLM        Spearman r={llm_spear:+.3f}  AUC(>=80)={llm_auc80:.3f}  P@{k80}={llm_p80:.2f}")

        if also_any_scored:
            pos_any = [1 if r["human_score"] > 0 else 0 for r in rows]
            llm_auc_any = _roc_auc(llm, pos_any)
            print(f"  LLM        AUC(any scored vs unscored)={llm_auc_any:.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="skip LLM calls")
    parser.add_argument("--record-fixture", action="store_true", help="save first batch raw response")
    args = parser.parse_args()

    rows = _load_dataset()
    sources = sorted(set(r["source"] for r in rows))
    print(f"Dataset: {len(rows)} blocks with human scores across {len(sources)} sources")

    from collections import Counter
    dist = Counter(r["human_score"] for r in rows)
    dist_str = "  ".join(f"{s}:{c}" for s, c in sorted(dist.items()))
    print(f"  Score distribution: {dist_str}")
    print(f"  Range: {min(dist)} – {max(dist)}  (NO zeros / unscored in dataset)")
    above80 = sum(1 for r in rows if r["human_score"] >= 80)
    print(f"  human>=80: {above80}  total: {len(rows)}")
    print("  NOTE: dataset is TRUNCATED — only blocks human chose to score are present.")

    print("\nLoading transcripts and unscored blocks...")
    transcripts = _load_transcripts()
    unscored, n_splice = _load_unscored_blocks(rows, transcripts)

    scored_by_src = Counter(r["source"] for r in rows)
    unscored_by_src = Counter(r["source"] for r in unscored)
    for src in sources:
        bfile = REPO / "manifests" / f"{src}.blocks.json"
        status = "no blocks.json" if not bfile.exists() else f"scored={scored_by_src[src]}, unscored_kept={unscored_by_src.get(src, 0)}"
        print(f"  {src}: {status}")

    v2_rows = rows + unscored
    print(f"\nVariant 2 total: {len(v2_rows)} ({len(rows)} scored + {len(unscored)} unscored)")
    print(f"  splice-excluded: {n_splice}")

    if args.dry_run:
        print("\n(--dry-run: heuristic metrics only)")
        _print_metrics("Variant 1: scored only", rows)
        _print_metrics("Variant 2: scored + unscored (heuristic)", v2_rows, also_any_scored=True)
        return

    # Load API key
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

    def _to_blocks(row_list: list[dict]) -> list[CandidateBlock]:
        blocks = []
        for r in row_list:
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
        return blocks

    def _score_all(
        blocks: list[CandidateBlock],
        label: str,
        first_batch_raw_holder: list,
    ) -> dict[str, int]:
        all_scores: dict[str, int] = {}
        n_batches = (len(blocks) + SCORE_BATCH_K - 1) // SCORE_BATCH_K
        print(f"\n{label}: {len(blocks)} blocks in {n_batches} batches...")
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
            if not first_batch_raw_holder:
                first_batch_raw_holder.append(raw)
            est = len(raw) // 4
            print(f"~{est} tok")
            try:
                entries = parse_score_response(raw)
                all_scores.update({e["id"]: e["score"] for e in entries if "id" in e and "score" in e})
            except ValueError as e:
                print(f"  parse error: {e}")
        return all_scores

    first_batch_raw: list[str] = []

    # Score both scored blocks AND unscored blocks
    scored_blocks = _to_blocks(rows)
    unscored_blocks = _to_blocks(unscored)

    llm_scored = _score_all(scored_blocks, "Scoring scored blocks (v1)", first_batch_raw)
    llm_unscored = _score_all(unscored_blocks, "Scoring unscored blocks (v2)", first_batch_raw)

    if args.record_fixture and first_batch_raw:
        fixture_path = REPO / "tests" / "fixtures" / "score_blocks_response.json"
        fixture_data = {
            "_comment": f"Real LLM response from M1.6 stage 4 scoring call. Model: {r0_cfg.model}.",
            "raw": first_batch_raw[0],
        }
        fixture_path.write_text(json.dumps(fixture_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nFixture saved: {fixture_path}")

    apply_llm_scores(scored_blocks, llm_scored)
    apply_llm_scores(unscored_blocks, llm_unscored)

    # Merge scores for variant 2
    all_llm_scores = {**llm_scored, **llm_unscored}

    print(f"\nLLM returned scores for {len(llm_scored)}/{len(rows)} scored blocks (omitted=0)")
    print(f"LLM returned scores for {len(llm_unscored)}/{len(unscored)} unscored blocks (omitted=0)")

    # Variant 1: scored only
    _print_metrics("Variant 1: scored only", rows, llm_scored)

    # Variant 2: scored + unscored (LLM called on both)
    _print_metrics(
        "Variant 2: scored + unscored (real LLM calls on both)",
        v2_rows,
        all_llm_scores,
        also_any_scored=True,
    )

    # 10 largest LLM vs human disagreements (scored blocks)
    matched = [r for r in rows if r["block_id"] in llm_scored]
    print(f"\n--- 10 largest LLM vs human disagreements (n_matched={len(matched)}) ---")
    for r in sorted(matched, key=lambda r: abs(llm_scored[r["block_id"]] - r["human_score"]), reverse=True)[:10]:
        bid = r["block_id"]
        diff = llm_scored[bid] - r["human_score"]
        excerpt = r["text"][:80].replace("\n", " ")
        print(f"  Δ{diff:+4d}  llm={llm_scored[bid]:3d} human={r['human_score']:3d}  {excerpt!r}")

    # Top-10 highest LLM scores among unscored blocks (false positives or worth a second look)
    scored_unscored = [(r, llm_unscored[r["block_id"]]) for r in unscored if r["block_id"] in llm_unscored]
    scored_unscored.sort(key=lambda x: -x[1])
    print(f"\n--- Top-10 highest LLM scores among unscored blocks ({len(scored_unscored)} LLM-scored) ---")
    for r, score in scored_unscored[:10]:
        excerpt = r["text"][:80].replace("\n", " ")
        print(f"  llm={score:3d} heur={r['heuristic_score']:.0f}  {excerpt!r}")

    # Verdict
    v2_pos80 = [1 if r["human_score"] >= 80 else 0 for r in v2_rows]
    v2_heur = [r["heuristic_score"] for r in v2_rows]
    v2_llm = [float(all_llm_scores.get(r["block_id"], 0)) for r in v2_rows]
    heur_auc2 = _roc_auc(v2_heur, v2_pos80)
    llm_auc2 = _roc_auc(v2_llm, v2_pos80)

    print(f"\n--- Verdict (Variant 2 ROC AUC, human>=80 vs all negatives) ---")
    if llm_auc2 > 0.75 and llm_auc2 > heur_auc2 + 0.10:
        verdict = f"LLM STRONG (AUC {llm_auc2:.2f} vs heuristic {heur_auc2:.2f}): use LLM scoring, DROP heuristic."
    elif llm_auc2 > 0.65 and llm_auc2 > heur_auc2:
        verdict = f"LLM BETTER (AUC {llm_auc2:.2f} vs heuristic {heur_auc2:.2f}): use LLM scoring, REWEIGHT heuristic."
    elif heur_auc2 > llm_auc2 + 0.05:
        verdict = f"HEURISTIC BETTER (AUC {heur_auc2:.2f} vs LLM {llm_auc2:.2f}): keep heuristic, LLM optional."
    else:
        verdict = f"COMPARABLE (LLM AUC {llm_auc2:.2f}, heuristic {heur_auc2:.2f}): keep both, monitor."
    print(f"  {verdict}")


if __name__ == "__main__":
    main()
