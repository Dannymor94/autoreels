#!/usr/bin/env python3
"""Feature audit for M1.6: univariate AUC, gate proposals, LLM+gate/blend simulation.

Usage:
    python scripts/feature_audit.py                    # parts 1 & 2 only
    python scripts/feature_audit.py --llm              # all parts (calls LLM, caches)
    python scripts/feature_audit.py --llm-cache FILE   # part 3 from saved scores JSON
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

TRANSCRIPT_CACHE = Path("/Users/danny/Documents/autoreels/data/cache")
LLM_CACHE_DEFAULT = REPO / "data" / "llm_scores_cache.json"

SOURCE_TRANSCRIPTS: dict[str, str] = {
    "2026-08-08 09h 33m 14s":         "1e0411048f8473fc16e751fd0d867fcdcc21b99dca5d2fb53ec4765f8498b265.84b62c5276da.transcript.json",
    "2026-08-08 11h 42m 49s":         "1ce8e4bb59457f6dd9ee1123e82434588b09e1a2861023974e5300bf62c1bb9b.84b62c5276da.transcript.json",
    "IMG_6848":                        "f4c1351fe015d10963ec8980f637b4c5f24b121742f6c9b4a45f6fe7bb69d2a9.84b62c5276da.transcript.json",
    "PXL_20260729_085910095_34f06abf": "72a9c86750fd1c5f01b1c84cbb574c8b4c9dfcd4b8f532aa0973c5087c0fea0f.84b62c5276da.transcript.json",
    "Pxl 20260621 112938952":          "7e7d7bdcf9abdf1902d56dc59d751f3ebe5be07bd5502b277fc9d9b50d128538.84b62c5276da.transcript.json",
    "Pxl 20260621 122006193":          "68052c97ab31af254fca037f7be12277cdf853877fd33a583741b5edda673d6a.84b62c5276da.transcript.json",
}

# ──────────────────────────────────────────────────── shared utils

_WORD_RE = re.compile(r"\w+", re.UNICODE)
_TRAILING = "»\"')]"


def _roc_auc(scores: list[float], labels: list[int]) -> float:
    pos, neg = sum(labels), len(labels) - sum(labels)
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


# ──────────────────────────────────────────────────── data loading

def _load_dataset(clean_only: bool = False) -> list[dict]:
    rows = []
    for jsonl in sorted((REPO / "data" / "blocks_dataset").glob("*.jsonl")):
        for line in jsonl.open(encoding="utf-8"):
            line = line.strip()
            if line:
                r = json.loads(line)
                if r.get("human_score") is not None:
                    if clean_only and r.get("legacy"):
                        continue
                    rows.append(r)
    return rows


def _load_transcripts() -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for src, fname in SOURCE_TRANSCRIPTS.items():
        path = TRANSCRIPT_CACHE / fname
        if path.exists():
            result[src] = json.loads(path.read_text(encoding="utf-8")).get("words", [])
    return result


def _extract_block_text(words: list[dict], start: float, end: float) -> str:
    span = [w["word"] for w in words if w["t0"] >= start - 0.3 and w["t1"] <= end + 0.3]
    return " ".join(span).strip()


def _overlap_frac(s1: float, e1: float, s2: float, e2: float) -> float:
    dur = e1 - s1
    if dur <= 0:
        return 0.0
    return max(0.0, min(e1, e2) - max(s1, s2)) / dur


def _load_unscored_blocks(
    dataset_rows: list[dict],
    transcripts: dict[str, list[dict]],
    *,
    clean_only: bool = False,
) -> tuple[list[dict], int]:
    ds_ids = {r["block_id"] for r in dataset_rows}
    # For clean_only: also exclude any constituent block IDs (splice members)
    if clean_only:
        for r in dataset_rows:
            ds_ids.update(r.get("block_ids") or [])

    scored_intervals: dict[str, list[tuple[float, float]]] = {}
    for r in dataset_rows:
        scored_intervals.setdefault(r["source"], []).append((r["start"], r["end"]))

    # When clean_only: only use sources where we can verify the segmentation fingerprint.
    # A source is "clean" when at least one non-legacy scored row has a fingerprint that
    # matches the current blocks.json (i.e. the segmentation the human saw is unchanged).
    if clean_only:
        import hashlib as _hl
        clean_sources: set[str] = set()
        fp_by_source: dict[str, str | None] = {}
        for r in dataset_rows:
            if not r.get("legacy"):
                fp_by_source[r["source"]] = r.get("segmentation_fingerprint")
        for src, stored_fp in fp_by_source.items():
            bfile = REPO / "manifests" / f"{src}.blocks.json"
            if not bfile.exists() or stored_fp is None:
                continue
            bj = json.loads(bfile.read_text(encoding="utf-8"))
            kept_ids = [b["id"] for b in sorted(bj, key=lambda x: x["start"])
                        if b.get("verdict", "KEPT") == "KEPT"]
            current_fp = _hl.sha1("|".join(kept_ids).encode()).hexdigest()[:16]
            if current_fp == stored_fp:
                clean_sources.add(src)
        sources_iter = sorted(clean_sources)
    else:
        sources_iter = sorted(set(r["source"] for r in dataset_rows))

    unscored: list[dict] = []
    n_splice = 0
    for src in sources_iter:
        bfile = REPO / "manifests" / f"{src}.blocks.json"
        if not bfile.exists():
            continue
        words = transcripts.get(src, [])
        for b in json.loads(bfile.read_text(encoding="utf-8")):
            if b["id"] in ds_ids:
                continue
            if b.get("verdict", "KEPT") != "KEPT":
                continue
            bs, be = b.get("start", 0.0), b.get("end", 0.0)
            if max((_overlap_frac(bs, be, s, e) for s, e in scored_intervals.get(src, [])), default=0.0) > 0.5:
                n_splice += 1
                continue
            text = _extract_block_text(words, bs, be) if words else ""
            if not text:
                continue
            unscored.append({
                "source": src, "block_id": b["id"],
                "start": bs, "end": be, "duration": be - bs,
                "text": text, "human_score": 0,
                "heuristic_score": b.get("heuristic_score", 0.0), "features": {},
                "segmentation_fingerprint": b.get("segmentation_fingerprint"),
                "legacy": False,
            })
    return unscored, n_splice


# ──────────────────────────────────────────────────── feature extractors

_BAD_OPEN = frozenset([
    "и", "из", "но", "или", "поэтому", "потому", "однако", "ведь", "значит",
    "тоже", "также", "зато", "впрочем", "итак", "следовательно", "таким",
    "он", "она", "они", "оно", "его", "её", "их", "им", "ей",
    "тот", "та", "те", "этот", "эта", "эти", "этим",
])
_DANGLING_MULTI = [
    "но вот ", "ну и ", "и вот ", "ну вот ", "а значит ", "а поэтому ",
    "потому что ", "для того ", "в связи с ", "вместе с тем ", "при этом ",
    "кроме того ", "более того ", "но при этом ", "который ", "которая ",
    "которые ", "которого ", "которому ", "которой ", "которых ",
]
_BACK_REF = [
    "как я говорил", "как мы говорили", "как я уже говорил", "как уже говорил",
    "как уже сказал", "в прошлый раз", "ранее мы", "ранее говорили",
    "напомню что", "напомним", "помните как", "вернёмся к", "вернемся к",
    "как мы уже", "о чём я говорил", "о чем я говорил",
]
_ENUM_KEYS = [
    "во-первых", "во первых", "во-вторых", "во вторых", "в-третьих", "в третьих",
    "первое —", "первое:", "первый момент", "пункт первый",
]
_ENUM_CONCLUDE = [
    "таким образом", "итого", "в заключение", "в итоге",
    "подводя итог", "резюмируя", "в общем и целом",
]
_CONTRARIAN = [
    "на самом деле", "наоборот", "а вот и нет", "что интересно",
    "однако", "но дело в том", "интересно то", "всё дело в",
    "парадокс в том", "на самом же деле",
]
_DANGLING_PRON = frozenset([
    "он", "она", "они", "оно", "его", "её", "их", "им", "ей",
    "тот", "та", "те", "этот", "эта", "эти", "этим",
])
_TAG_Q = ["понятно?", " да?", " нет?", "правильно?", "согласны?", "верно?", " так?", "ведь?"]


def _ends_terminal(text: str) -> bool:
    s = text.rstrip(_TRAILING)
    return bool(s) and s[-1] in ".?!…"


def _dangling_start(text: str) -> bool:
    c = text.lstrip("—– \t").lower()
    m = _WORD_RE.match(c)
    if m and m.group() in _BAD_OPEN:
        return True
    return any(c.startswith(p) for p in _DANGLING_MULTI)


def _qa_inside(text: str) -> bool:
    lq = text.rfind("?")
    if lq < 0:
        return False
    return len(text[lq + 1:].strip().rstrip(_TRAILING)) >= 5


def _lexical_div(text: str) -> float:
    words = _WORD_RE.findall(text.lower())
    return len(set(words)) / len(words) if words else 0.0


def _speech_rate(text: str, dur: float) -> float:
    return len(_WORD_RE.findall(text)) / dur if dur > 0 else 0.0


def _dangling_density(text: str) -> float:
    end = next((i for i, c in enumerate(text) if c in ".?!…"), -1)
    first = text.lower()[:end] if end > 0 else text.lower()
    words = _WORD_RE.findall(first)
    return sum(1 for w in words if w in _DANGLING_PRON) / len(words) if words else 0.0


def compute_features(row: dict) -> dict[str, float]:
    text, dur = row["text"], row["duration"]
    return {
        "duration":         dur,
        "speech_rate":      _speech_rate(text, dur),
        "lexical_div":      _lexical_div(text),
        "dangling_density": _dangling_density(text),
        "heuristic_score":  row["heuristic_score"],
        "ends_terminal":    float(_ends_terminal(text)),
        "ends_tag_q":       float(any(text.strip().rstrip(_TRAILING).lower().endswith(tq.strip()) for tq in _TAG_Q)),
        "good_open":        float(not _dangling_start(text)),
        "dangling_start":   float(_dangling_start(text)),
        "has_question":     float("?" in text),
        "qa_inside":        float(_qa_inside(text)),
        "has_contrarian":   float(any(m in text.lower() for m in _CONTRARIAN)),
        "back_ref":         float(any(p in text.lower() for p in _BACK_REF)),
        "enum_open":        float(any(m in text.lower() for m in _ENUM_KEYS) and not any(m in text.lower() for m in _ENUM_CONCLUDE)),
        "speaker_change":   float(bool(re.search(r"[.!?…]\s*[—–]", text))),
    }


# ──────────────────────────────────────────────────── stats helpers

def _mean_std(vals: list[float]) -> tuple[float, float]:
    if not vals:
        return 0.0, 1.0
    m = sum(vals) / len(vals)
    v = sum((x - m) ** 2 for x in vals) / max(len(vals) - 1, 1)
    return m, max(math.sqrt(v), 1e-9)


def _normalize_zscore(vals: list[float]) -> list[float]:
    m, s = _mean_std(vals)
    return [(x - m) / s for x in vals]


def _auc_table(rows: list[dict], feats: list[dict]) -> list[tuple]:
    labels80  = [1 if r["human_score"] >= 80 else 0 for r in rows]
    labels_any = [1 if r["human_score"] > 0 else 0 for r in rows]
    binary = {"ends_terminal", "ends_tag_q", "good_open", "dangling_start",
               "has_question", "qa_inside", "has_contrarian", "back_ref",
               "enum_open", "speaker_change"}
    results = []
    for name in feats[0]:
        vals = [f[name] for f in feats]
        n_fires = sum(1 for v in vals if v > 0) if name in binary else None
        results.append((name, _roc_auc(vals, labels80), _roc_auc(vals, labels_any), n_fires))
    return results


def _gate_stats(rows: list[dict], feats: list[dict], name: str, threshold: float, direction: str) -> tuple[int, int, int]:
    n_excl = n_good = n_unc = 0
    for r, f in zip(rows, feats):
        fires = (f[name] > threshold) if direction == "gt" else (f[name] < threshold)
        if fires:
            n_excl += 1
            if r["human_score"] >= 80:
                n_good += 1
            elif r["human_score"] == 0:
                n_unc += 1
    return n_excl, n_good, n_unc


# ──────────────────────────────────────────────────── LLM scoring

def _run_llm_scoring(rows: list[dict], cache_path: Path) -> dict[str, float]:
    env_file = REPO / ".env"
    if env_file.exists():
        for ln in env_file.read_text().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, _, v = ln.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("  GROQ_API_KEY not set — skipping LLM", file=sys.stderr)
        return {}

    from autoreels.cloud.blocks import CandidateBlock
    from autoreels.cloud.providers import GroqLLM
    from autoreels.cloud.score_blocks import SCORE_BATCH_K, SCORE_MAX_OUTPUT_TOKENS, build_score_messages, parse_score_response
    from autoreels.cloud.select import _extract_prompt_body
    from autoreels.core.config import load_r0_config

    r0_cfg = load_r0_config(REPO / "config" / "r0.yaml")
    system_text = _extract_prompt_body((REPO / "prompts" / "score_system.md").read_text(encoding="utf-8"))
    fewshot_examples = json.loads((REPO / "prompts" / "score_fewshot.json").read_text(encoding="utf-8")).get("examples", [])
    provider = GroqLLM(model=r0_cfg.model, api_key=api_key,
                       max_output_tokens=SCORE_MAX_OUTPUT_TOKENS, reasoning_effort="none")

    blocks = [CandidateBlock(id=r["block_id"], start=r["start"], end=r["end"],
                             duration=r["duration"], text=r["text"], boundary_reason="sentence")
              for r in rows]
    all_scores: dict[str, float] = {}
    n_batches = (len(blocks) + SCORE_BATCH_K - 1) // SCORE_BATCH_K
    print(f"\nScoring {len(blocks)} blocks in {n_batches} batches...")
    for i in range(0, len(blocks), SCORE_BATCH_K):
        batch = blocks[i: i + SCORE_BATCH_K]
        bn = i // SCORE_BATCH_K + 1
        print(f"  batch {bn}/{n_batches} ...", end="", flush=True)
        try:
            raw = provider.complete(build_score_messages(batch, system_text=system_text, fewshot_examples=fewshot_examples))
            for e in parse_score_response(raw):
                if "id" in e and "score" in e:
                    all_scores[e["id"]] = float(e["score"])
            print(f" ok ({sum(1 for e in parse_score_response(raw) if 'id' in e)})")
        except Exception as ex:
            print(f" ERROR: {ex}")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(all_scores, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"LLM scores cached → {cache_path}")
    return all_scores


# ──────────────────────────────────────────────────── main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--llm", action="store_true", help="run LLM scoring if no cache")
    ap.add_argument("--llm-cache", type=Path, default=LLM_CACHE_DEFAULT)
    ap.add_argument("--clean-only", action="store_true",
                    help="use only non-legacy rows and same-fingerprint unscored blocks")
    args = ap.parse_args()

    # ── load V2 dataset
    print("Loading dataset...", flush=True)
    scored = _load_dataset(clean_only=args.clean_only)
    transcripts = _load_transcripts()
    unscored, n_splice = _load_unscored_blocks(scored, transcripts, clean_only=args.clean_only)
    rows = scored + unscored
    feats = [compute_features(r) for r in rows]

    sources = sorted(set(r["source"] for r in rows))
    labels80   = [1 if r["human_score"] >= 80 else 0 for r in rows]
    labels_any = [1 if r["human_score"] > 0 else 0 for r in rows]
    n80 = sum(labels80)

    mode = "clean-only" if args.clean_only else "all"
    print(f"  mode={mode}, scored={len(scored)}, unscored={len(unscored)}, splice_excl={n_splice}, total={len(rows)}")
    print(f"  n per source:")
    from collections import Counter
    src_scored = Counter(r["source"] for r in scored)
    src_unscored = Counter(r["source"] for r in unscored)
    for src in sorted(set(src_scored) | set(src_unscored)):
        sc = src_scored.get(src, 0)
        un = src_unscored.get(src, 0)
        legacy_n = sum(1 for r in scored if r["source"] == src and r.get("legacy"))
        legacy_tag = f"  [{legacy_n} legacy]" if legacy_n else ""
        print(f"    {src}: scored={sc}, unscored={un}{legacy_tag}")

    # ══════════════════════════════════════════════════════ PART 1: univariate AUC

    binary = {"ends_terminal", "ends_tag_q", "good_open", "dangling_start",
               "has_question", "qa_inside", "has_contrarian", "back_ref",
               "enum_open", "speaker_change"}

    table = _auc_table(rows, feats)
    table_sorted = sorted(table, key=lambda x: abs(x[1] - 0.5) if x[1] == x[1] else 0, reverse=True)

    print("\n" + "═" * 74)
    print("PART 1 — Univariate ROC AUC  (V2: n=284, human≥80 vs unscored | any vs unscored)")
    print("═" * 74)
    print(f"  {'Feature':<22}  {'AUC(≥80)':<9}  {'AUC(any)':<9}  {'n_fires':>7}  fire%")
    print("  " + "-" * 66)
    for name, a80, a_any, n_fires in table_sorted:
        a80s  = f"{a80:.3f}" if a80 == a80 else " nan "
        aas   = f"{a_any:.3f}" if a_any == a_any else " nan "
        if n_fires is not None:
            fs = f"{n_fires:6d} ({100*n_fires/len(rows):4.1f}%)"
        else:
            fs = "     —      —  "
        flag = "  ▲" if a80 >= 0.60 else ("  ▼" if a80 <= 0.40 else "   ")
        print(f"  {name:<22}  {a80s}    {aas}    {fs}{flag}")

    # ── Per-source breakdown (Part 1)
    print("\n  Per-source  AUC(≥80): LLM will fill in later; heuristic + text features now:")
    print(f"  {'Source':<38}  {'n_sc':>4}  {'n_un':>4}  {'heur_auc80':>10}  {'dur_auc80':>9}")
    print("  " + "-" * 72)
    for src in sources:
        src_rows  = [r for r in rows if r["source"] == src]
        src_feats = [feats[i] for i, r in enumerate(rows) if r["source"] == src]
        sl80 = [1 if r["human_score"] >= 80 else 0 for r in src_rows]
        sl0  = [1 if r["human_score"] == 0  else 0 for r in src_rows]
        n_sc = sum(1 for r in src_rows if r["human_score"] > 0)
        n_un = sum(sl0)
        heur = [f["heuristic_score"] for f in src_feats]
        dur  = [f["duration"] for f in src_feats]
        ha = _roc_auc(heur, sl80)
        da = _roc_auc(dur,  sl80)
        has = f"{ha:.3f}" if ha == ha else " nan"
        das = f"{da:.3f}" if da == da else " nan"
        print(f"  {src:<38}  {n_sc:4d}  {n_un:4d}  {has:>10}  {das:>9}")

    # ══════════════════════════════════════════════════════ PART 2: terminal-punct density + gate

    print("\n" + "═" * 74)
    print("PART 2a — Terminal-punctuation density per source")
    print("═" * 74)
    src_density: dict[str, float] = {}
    for src in sources:
        src_rows  = [r for r in rows if r["source"] == src]
        src_feats = [feats[i] for i, r in enumerate(rows) if r["source"] == src]
        n_tot = len(src_rows)
        n_term = sum(f["ends_terminal"] for f in src_feats)
        src_density[src] = n_term / n_tot if n_tot else 0.0

    thresholds = [0.75, 0.85, 0.90]
    header = f"  {'Source':<38}  {'n_total':>7}  {'term%':>6}" + "".join(f"  ≥{int(t*100)}%" for t in thresholds)
    print(header)
    print("  " + "-" * 70)
    for src in sources:
        src_rows  = [r for r in rows if r["source"] == src]
        n_tot = len(src_rows)
        d = src_density[src]
        marks = "".join(f"  {'✓':>4}" if d >= t else f"  {'✗':>4}" for t in thresholds)
        print(f"  {src:<38}  {n_tot:7d}  {100*d:5.1f}%{marks}")

    TERM_DENSITY_THRESHOLD = 0.75   # chosen threshold
    gate_eligible_sources = {s for s, d in src_density.items() if d >= TERM_DENSITY_THRESHOLD}
    print(f"\n  Chosen threshold={TERM_DENSITY_THRESHOLD:.0%}: gate eligible sources: {len(gate_eligible_sources)}/{len(sources)}")
    print(f"  (All sources pass ≥75%; raise to ≥85% to drop lowest-density 3 sources)")

    print("\n" + "═" * 74)
    print("PART 2b — Hard pre-LLM gates  (per-block; shows harm on human≥80)")
    print("═" * 74)
    print(f"  {'Gate':<38}  {'excl':>6}  {'drop≥80':>8}  {'rm_unc':>7}  note")
    print("  " + "-" * 72)

    def _show(label: str, feat: str, thr: float, direction: str, note: str = "") -> None:
        n_excl, n_good, n_unc = _gate_stats(rows, feats, feat, thr, direction)
        if n_excl == 0:
            return
        pct_e = 100 * n_excl / len(rows)
        pct_g = 100 * n_good / n80 if n80 else 0
        pct_u = 100 * n_unc  / sum(1 for r in rows if r["human_score"] == 0)
        harm  = "⚠" if n_good > 3 else " "
        print(f"  {label:<38}  {n_excl:3d}({pct_e:4.1f}%)  {n_good:3d}({pct_g:4.1f}%)  {n_unc:3d}({pct_u:4.1f}%)  {harm}{note}")

    _show("ends_terminal=0  (all sources)",   "ends_terminal", 0.5, "lt", "no terminal punct")

    # Source-filtered version of the gate
    eligible_rows  = [r for r in rows if r["source"] in gate_eligible_sources]
    eligible_feats = [feats[i] for i, r in enumerate(rows) if r["source"] in gate_eligible_sources]
    if eligible_rows:
        n_excl_e = sum(1 for r, f in zip(eligible_rows, eligible_feats) if f["ends_terminal"] < 0.5)
        n_good_e = sum(1 for r, f in zip(eligible_rows, eligible_feats) if f["ends_terminal"] < 0.5 and r["human_score"] >= 80)
        n_unc_e  = sum(1 for r, f in zip(eligible_rows, eligible_feats) if f["ends_terminal"] < 0.5 and r["human_score"] == 0)
        pct_e = 100 * n_excl_e / len(rows)
        pct_g = 100 * n_good_e / n80 if n80 else 0
        n_unc_total = sum(1 for r in rows if r["human_score"] == 0)
        pct_u = 100 * n_unc_e / n_unc_total if n_unc_total else 0
        harm = "⚠" if n_good_e > 3 else " "
        label = f"ends_terminal=0  (eligible srcs only)"
        print(f"  {label:<38}  {n_excl_e:3d}({pct_e:4.1f}%)  {n_good_e:3d}({pct_g:4.1f}%)  {n_unc_e:3d}({pct_u:4.1f}%)  {harm}density≥{TERM_DENSITY_THRESHOLD:.0%}")

    _show("duration < 18s",                    "duration",      18.0, "lt")
    _show("speech_rate < 1.0 w/s",             "speech_rate",    1.0, "lt")
    _show("speaker_change = 1",                "speaker_change", 0.5, "gt")
    _show("dangling_start = 1  (FYI)",         "dangling_start", 0.5, "gt", "high harm")
    _show("back_ref = 1  (FYI)",               "back_ref",       0.5, "gt", "high harm")

    # ══════════════════════════════════════════════════════ PART 3: LLM + gates + blends

    llm_scores: dict[str, float] | None = None
    if args.llm_cache.exists():
        llm_scores = {k: float(v) for k, v in json.loads(args.llm_cache.read_text()).items()}
        n_nonzero = sum(1 for v in llm_scores.values() if v > 0)
        print(f"\nLLM cache loaded: {len(llm_scores)} entries, {n_nonzero} non-zero")
        # cross-check: expected ~76 scored + ~53 unscored non-zero from prev run
    elif args.llm:
        llm_scores = _run_llm_scoring(rows, args.llm_cache)
    else:
        print(f"\n(Parts 3 & 4 skipped — no LLM cache; use --llm to compute)")

    if llm_scores is None:
        return

    llm_vals = [llm_scores.get(r["block_id"], 0.0) for r in rows]
    auc_base = _roc_auc(llm_vals, labels80)
    pk_base  = _precision_at_k(llm_vals, labels80, n80)
    n_nonzero_matched = sum(1 for r in rows if llm_scores.get(r["block_id"], 0.0) > 0)
    print(f"  non-zero LLM scores on these 284 blocks: {n_nonzero_matched}")
    print(f"  prev run: 76+53=129 non-zero expected")

    print("\n" + "═" * 74)
    print(f"PART 3 — LLM + gates / blends  (V2 baseline: AUC(≥80)={auc_base:.3f}  P@{n80}={pk_base:.2f})")
    print("═" * 74)

    # z-score normalize duration and lexical_div for blending
    dur_z  = _normalize_zscore([f["duration"]    for f in feats])
    lex_z  = _normalize_zscore([f["lexical_div"] for f in feats])
    sr_z   = _normalize_zscore([f["speech_rate"] for f in feats])

    def _blend(alpha_dur: float, alpha_lex: float, alpha_sr: float = 0.0) -> list[float]:
        # lex is inverted (lower is better)
        return [llm + alpha_dur * d - alpha_lex * l + alpha_sr * s
                for llm, d, l, s in zip(llm_vals, dur_z, lex_z, sr_z)]

    def _apply_gate_filter(
        gate_fn,  # (row, feat) -> bool: True = KEEP
    ) -> tuple[list[float], list[int]]:
        """Apply gate; excluded blocks get llm=0, survive get their real llm score."""
        scores = [
            llm_scores.get(r["block_id"], 0.0) if gate_fn(r, f) else 0.0
            for r, f in zip(rows, feats)
        ]
        return scores, labels80

    print(f"\n  {'Variant':<42}  {'AUC(≥80)':>9}  {'P@{n80}':>7}  {'ΔAUC':>6}")
    print("  " + "-" * 68)

    def _row(label: str, scores: list[float]) -> None:
        auc = _roc_auc(scores, labels80)
        pk  = _precision_at_k(scores, labels80, n80)
        delta = auc - auc_base
        ds = f"{delta:+.3f}" if auc == auc else "  nan"
        marker = " ▲" if delta > 0.005 else (" ▼" if delta < -0.005 else "  ")
        print(f"  {label:<42}  {auc:.3f}     {pk:.2f}   {ds}{marker}")

    _row(f"LLM alone (baseline)",              llm_vals)
    _row("LLM + dur prior (α=5)",              _blend(5.0, 0.0))
    _row("LLM + dur prior (α=10)",             _blend(10.0, 0.0))
    _row("LLM − lex_div (β=5)",               _blend(0.0, 5.0))
    _row("LLM − lex_div (β=10)",              _blend(0.0, 10.0))
    _row("LLM + dur(5) − lex(5)",             _blend(5.0, 5.0))
    _row("LLM + dur(10) − lex(10)",           _blend(10.0, 10.0))
    _row("LLM + dur(10) − lex(5) + sr(3)",    _blend(10.0, 5.0, 3.0))

    # Gate variants: excluded blocks get score 0
    gate_no_term = lambda r, f: f["ends_terminal"] > 0.5
    gate_no_term_eligible = lambda r, f: (r["source"] not in gate_eligible_sources) or (f["ends_terminal"] > 0.5)
    gate_dur = lambda r, f: f["duration"] >= 18.0
    gate_sr  = lambda r, f: f["speech_rate"] >= 1.0
    gate_sc  = lambda r, f: f["speaker_change"] < 0.5
    gate_conservative = lambda r, f: (
        f["speaker_change"] < 0.5 and
        f["duration"] >= 18.0 and
        f["speech_rate"] >= 1.0
    )

    _row("gate: ends_terminal=0 (all srcs)",   _apply_gate_filter(gate_no_term)[0])
    _row("gate: ends_terminal=0 (elig srcs)",  _apply_gate_filter(gate_no_term_eligible)[0])
    _row("gate: duration<18",                  _apply_gate_filter(gate_dur)[0])
    _row("gate: speech_rate<1",                _apply_gate_filter(gate_sr)[0])
    _row("gate: speaker_change",               _apply_gate_filter(gate_sc)[0])
    _row("gate: conservative combo",           _apply_gate_filter(gate_conservative)[0])

    # Best blend + best gate
    best_blend = _blend(10.0, 5.0)
    best_blend_gate = [s if gate_no_term_eligible(r, f) else 0.0
                       for s, r, f in zip(best_blend, rows, feats)]
    _row("gate(elig) + LLM+dur(10)−lex(5)",   best_blend_gate)

    # ══════════════════════════════════════════════════════ PART 4: per-source breakdown


    print("\n" + "═" * 74)
    print("PART 4 — Per-source breakdown  (LLM AUC and P@K)")
    print("═" * 74)
    print(f"  {'Source':<38}  {'n_sc':>4}  {'n_un':>4}  {'n≥80':>4}  {'llm_auc80':>9}  {'llm_P@K':>7}  {'heur_auc80':>10}")
    print("  " + "-" * 80)
    for src in sources:
        sr_rows = [(r, f, llm_scores.get(r["block_id"], 0.0)) for r, f in zip(rows, feats) if r["source"] == src]
        n_sc = sum(1 for r, f, _ in sr_rows if r["human_score"] > 0)
        n_un = sum(1 for r, f, _ in sr_rows if r["human_score"] == 0)
        sl80 = [1 if r["human_score"] >= 80 else 0 for r, f, _ in sr_rows]
        kk   = sum(sl80)
        llmv = [s for _, _, s in sr_rows]
        heuv = [f["heuristic_score"] for _, f, _ in sr_rows]
        la  = _roc_auc(llmv, sl80)
        lp  = _precision_at_k(llmv, sl80, kk) if kk else float("nan")
        ha  = _roc_auc(heuv, sl80)
        las = f"{la:.3f}" if la == la else "  nan"
        lps = f"{lp:.2f}" if lp == lp else "  nan"
        has = f"{ha:.3f}" if ha == ha else "  nan"
        print(f"  {src:<38}  {n_sc:4d}  {n_un:4d}  {kk:4d}  {las:>9}  {lps:>7}  {has:>10}")

    # ══════════════════════════════════════════════════════ PART 5: LOSO
    _loso(rows, feats, llm_scores, sources)


def _loso(
    rows: list[dict],
    feats: list[dict],
    llm_scores: dict[str, float],
    sources: list[str],
) -> None:
    """Leave-one-source-out cross-validation.

    For each held-out source: grid-search α/β on training 5, evaluate on held-out.
    Variants: LLM alone | LLM+dur | LLM+dur−lex | gate(no_term)+blend.
    Duration confound note: scored blocks include spliced clips (longer than unscored);
    AUC from duration is partly a splice-length effect. LOSO will show whether it generalises.
    """
    print("\n" + "═" * 74)
    print("PART 5 — LOSO cross-validation  (tune α/β on 5 sources, eval on held-out)")
    print("  NOTE: duration is CONFOUNDED (scored=spliced clips, unscored=single blocks)")
    print("═" * 74)

    alpha_grid = [0, 2, 5, 8, 10, 15, 20]
    beta_grid  = [0, 2, 5, 8, 10, 15, 20]

    def _blend_src(llm_v: list[float], dur_z: list[float], lex_z: list[float], a: float, b: float) -> list[float]:
        return [llm + a * d - b * l for llm, d, l in zip(llm_v, dur_z, lex_z)]

    results: dict[str, dict[str, float]] = {}  # source → {variant: auc}

    for held_src in sources:
        train_idx = [i for i, r in enumerate(rows) if r["source"] != held_src]
        held_idx  = [i for i, r in enumerate(rows) if r["source"] == held_src]

        if not train_idx or not held_idx:
            continue

        tr_rows  = [rows[i]  for i in train_idx]
        tr_feats = [feats[i] for i in train_idx]
        ho_rows  = [rows[i]  for i in held_idx]
        ho_feats = [feats[i] for i in held_idx]

        tr_labels80 = [1 if r["human_score"] >= 80 else 0 for r in tr_rows]
        ho_labels80 = [1 if r["human_score"] >= 80 else 0 for r in ho_rows]

        tr_llm  = [llm_scores.get(r["block_id"], 0.0) for r in tr_rows]
        ho_llm  = [llm_scores.get(r["block_id"], 0.0) for r in ho_rows]

        tr_dur_z = _normalize_zscore([f["duration"]    for f in tr_feats])
        tr_lex_z = _normalize_zscore([f["lexical_div"] for f in tr_feats])

        # For held-out, normalise using train stats to avoid leakage
        def _zscore_with_stats(vals: list[float], ref: list[float]) -> list[float]:
            m, s = _mean_std(ref)
            return [(x - m) / s for x in vals]

        tr_dur_raw = [f["duration"]    for f in tr_feats]
        tr_lex_raw = [f["lexical_div"] for f in tr_feats]
        ho_dur_raw = [f["duration"]    for f in ho_feats]
        ho_lex_raw = [f["lexical_div"] for f in ho_feats]
        ho_dur_z = _zscore_with_stats(ho_dur_raw, tr_dur_raw)
        ho_lex_z = _zscore_with_stats(ho_lex_raw, tr_lex_raw)

        # Grid search on train for LLM+dur only (α alone)
        best_a_dur, best_auc_dur = 0.0, _roc_auc(tr_llm, tr_labels80)
        for a in alpha_grid[1:]:
            auc = _roc_auc(_blend_src(tr_llm, tr_dur_z, tr_lex_z, a, 0.0), tr_labels80)
            if auc > best_auc_dur:
                best_auc_dur, best_a_dur = auc, float(a)

        # Grid search on train for LLM+dur−lex (α,β)
        best_a_both, best_b_both = 0.0, 0.0
        best_auc_both = _roc_auc(tr_llm, tr_labels80)
        for a in alpha_grid:
            for b in beta_grid:
                auc = _roc_auc(_blend_src(tr_llm, tr_dur_z, tr_lex_z, a, b), tr_labels80)
                if auc > best_auc_both:
                    best_auc_both, best_a_both, best_b_both = auc, float(a), float(b)

        # Evaluate on held-out
        ho_term = [f["ends_terminal"] for f in ho_feats]
        ho_gate = [s if t > 0.5 else 0.0 for s, t in zip(ho_llm, ho_term)]
        ho_gate_blend = [s if t > 0.5 else 0.0
                         for s, t in zip(_blend_src(ho_llm, ho_dur_z, ho_lex_z, best_a_both, best_b_both), ho_term)]

        kk = sum(ho_labels80)
        results[held_src] = {
            "n_total":    len(ho_rows),
            "n80":        kk,
            "llm":        _roc_auc(ho_llm, ho_labels80),
            "llm+dur":    _roc_auc(_blend_src(ho_llm, ho_dur_z, ho_lex_z, best_a_dur, 0.0), ho_labels80),
            "llm+dur-lex": _roc_auc(_blend_src(ho_llm, ho_dur_z, ho_lex_z, best_a_both, best_b_both), ho_labels80),
            "gate+blend": _roc_auc(ho_gate_blend, ho_labels80),
            "llm_p":      _precision_at_k(ho_llm, ho_labels80, kk) if kk else float("nan"),
            "blend_p":    _precision_at_k(ho_gate_blend, ho_labels80, kk) if kk else float("nan"),
            "best_a_dur": best_a_dur,
            "best_a":     best_a_both,
            "best_b":     best_b_both,
        }

    print(f"\n  {'Source':<38}  {'n':>4}  {'n≥80':>4}  {'α,β':>8}  {'LLM':>6}  {'LLM+dur':>8}  {'LLM+d-l':>8}  {'gate+bl':>8}")
    print("  " + "-" * 88)
    totals = {"llm": [], "llm+dur": [], "llm+dur-lex": [], "gate+blend": []}
    for src in sources:
        if src not in results:
            continue
        r = results[src]
        a_str = f"α{r['best_a']:.0f}β{r['best_b']:.0f}"
        def _f(v: float) -> str:
            return f"{v:.3f}" if v == v else "  nan"
        print(f"  {src:<38}  {r['n_total']:4d}  {r['n80']:4d}  {a_str:>8}  "
              f"{_f(r['llm']):>6}  {_f(r['llm+dur']):>8}  {_f(r['llm+dur-lex']):>8}  {_f(r['gate+blend']):>8}")
        for k in totals:
            if r[k] == r[k]:
                totals[k].append(r[k])

    print("  " + "-" * 88)
    n_src = len(sources)
    def _mean(vals: list[float]) -> str:
        return f"{sum(vals)/len(vals):.3f}" if vals else "  nan"
    print(f"  {'MEAN (out-of-sample)':<38}  {'':>4}  {'':>4}  {'':>8}  "
          f"{_mean(totals['llm']):>6}  {_mean(totals['llm+dur']):>8}  {_mean(totals['llm+dur-lex']):>8}  {_mean(totals['gate+blend']):>8}")


if __name__ == "__main__":
    main()
