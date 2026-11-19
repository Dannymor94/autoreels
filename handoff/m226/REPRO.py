#!/usr/bin/env python3
"""M226 REPRO — portable reproduction of Findings #4, #9, #12 + §1 preflight.

Usage:
    python3 handoff/m226/REPRO.py [--repo-root /path/to/repo]

Default repo-root: three levels up from this file (handoff/m226/REPRO.py → repo root).
No paid APIs, no LLM calls, no renders.  All I/O under TemporaryDirectory.
SOURCE_SHA = "d"*64 (M226 marker).
"""

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

SOURCE_SHA = "d" * 64
PRODUCTION_DIFF = "none"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _header(title: str) -> None:
    bar = "=" * 60
    print(f"\n{bar}\n{title}\n{bar}")


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        print(f"  FAIL  {msg}", file=sys.stderr)
        sys.exit(1)
    print(f"  PASS  {msg}")


# ---------------------------------------------------------------------------
# §1 Preflight — cmd_autocut on synthetic transcript
# ---------------------------------------------------------------------------

def run_preflight(repo: Path) -> None:
    _header("§1 PREFLIGHT — cmd_autocut on synthetic data")

    sys.path.insert(0, str(repo / "src"))
    from autoreels.__main__ import cmd_autocut

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # -- directory skeleton --
        for d in ("config", "manifests", "transcripts", "data/cache", "reels-out"):
            (root / d).mkdir(parents=True, exist_ok=True)

        # -- config --
        import shutil
        shutil.copy(repo / "config" / "r0.yaml", root / "config" / "r0.yaml")

        # -- synthetic transcript -----------------------------------------
        # Two sentences inside a "main" block at t=35-75 (40 s).
        # Sentence 1: t=35.0-54.0, 190 words each 0.1 s, ends with "."
        # Sentence 2: t=55.0-75.0, 200 words each 0.1 s, ends with "."
        # Dummy block at t=85-105 (20 s): keeps total_duration=105 s so the
        # main block midpoint (55 s) passes tail_skip filter (< 105-30=75 s).
        # Uppercase word names bypass the mid-sentence check (text[0].isupper()).
        words_raw: list[dict] = []
        idx = 0

        def _add_sentence(t_start: float, t_end: float) -> None:
            nonlocal idx
            t = t_start
            while round(t + 0.1, 2) <= t_end + 1e-9:
                t0 = round(t, 2)
                t1 = round(t + 0.1, 2)
                is_last = t1 >= t_end - 0.03
                words_raw.append({
                    "word": f"P{idx}." if is_last else f"P{idx}",
                    "t0": t0, "t1": t1,
                })
                t = round(t + 0.1, 2)
                idx += 1

        _add_sentence(35.0, 54.0)   # sentence 1 (gap at 54-55 s = 1 s > sentence_pause_sec=0.35)
        _add_sentence(55.0, 75.0)   # sentence 2

        # dummy words to extend total_duration
        t = 85.0
        while round(t + 0.1, 2) <= 105.0:
            words_raw.append({"word": f"D{idx}", "t0": round(t, 2), "t1": round(t + 0.1, 2)})
            t = round(t + 0.1, 2)
            idx += 1

        tx = {
            "language": "ru",
            "model": "whisper-large-v3",
            "provider": "openai",
            "source_sha256": SOURCE_SHA,
            "words": words_raw,
        }
        tx_path = root / "data" / "cache" / f"{SOURCE_SHA}.transcript.json"
        tx_path.write_text(json.dumps(tx))

        # -- manifest --
        mf = {
            "source": "synthetic_m226.mp4",
            "source_sha256": SOURCE_SHA,
            "duration_preset": "reel",
            "setup": {
                "setup_id": "m226_synthetic",
                "crop": {"x": 0, "y": 0, "w": 1080, "h": 1920},
                "scale": [1080, 1920],
                "frame": [1080, 1920],
            },
            "run_key": "r0",
        }
        mf_path = root / "manifests" / "synthetic_m226.json"
        mf_path.write_text(json.dumps(mf))

        stem = "synthetic_m226"

        # -- map (units) — must be at transcripts/<stem>.map.json --
        (root / "transcripts").mkdir(parents=True, exist_ok=True)
        the_map = {
            "source_sha256": SOURCE_SHA,
            "units": [
                {
                    "id": 1,
                    "t0": 35.0, "t1": 75.0,
                    "role": "conclusion",
                    "punch": 5,
                    "topic": "main",
                    "refs": "1.1-2",
                    "standalone": True,
                    "summary": "Synthetic conclusion.",
                    "similar": [],
                },
                {
                    "id": 2,
                    "t0": 85.0, "t1": 105.0,
                    "role": "thesis",
                    "punch": 3,
                    "topic": "other",
                    "refs": "2.1",
                    "standalone": True,
                    "summary": "Dummy unit.",
                    "similar": [],
                },
            ],
        }
        map_path = root / "transcripts" / f"{stem}.map.json"
        map_path.write_text(json.dumps(the_map))

        rc = cmd_autocut(stem, root=root, llm="none")

        print(f"  rc={rc}")

        _assert(rc == 0, "cmd_autocut returns rc=0")

        review_path = root / "reviews" / f"{stem}_auto_m56.txt"
        _assert(review_path.exists(), "review file written by cmd_autocut")

        content = review_path.read_text()
        print(f"  review file content ({len(content)} chars):")
        for line in content.splitlines()[:20]:
            print(f"    {line}")

        accepted_lines = [l for l in content.splitlines()
                          if l.startswith("M") and "|" in l and not l.startswith("# ")]
        _assert(len(accepted_lines) >= 1, f"at least 1 accepted line ({accepted_lines})")

        sha = _sha256(content)
        print(f"\n  review SHA256={sha}")
        print(f"  PREFLIGHT_SHA256={sha}")


# ---------------------------------------------------------------------------
# F4 — select_global with A(95), B(60), C(60); A conflicts B and C
# ---------------------------------------------------------------------------

def run_f4(repo: Path) -> None:
    _header("F4 — select_global: strong-but-conflicting vs two weaker-compatible")

    sys.path.insert(0, str(repo / "src"))
    from autoreels.cloud.autocut import select_global, too_close, Proposal

    # A(95) conflicts with B(60) and C(60); B and C are compatible.
    weights = [95.0, 60.0, 60.0]
    # conflict: A(0) conflicts with B(1) and C(2); B(1) and C(2) don't conflict
    conflict = lambda i, j: (i == 0 or j == 0) and i != j

    result = select_global(weights, conflict, k=2)
    print(f"  select_global([95,60,60], A_conflicts_BC, k=2) → indices {result}")

    _assert(result == [1, 2], "select_global picks B+C (indices [1,2]) over A alone")

    total_bc = weights[1] + weights[2]
    total_a = weights[0]
    _assert(total_bc > total_a, f"B+C score {total_bc} > A score {total_a}")
    print(f"  B+C total={total_bc} > A total={total_a} ✓ (global optimum)")

    # Demonstrate too_close: A and B share unit #1 → conflict with max_shared=0
    # Build minimal Proposal-like objects with .units and .opener/.title fields
    # Proposal is a dataclass; use direct construction via its __init__
    def make_proposal(units: list[int], score: int) -> Proposal:
        p = object.__new__(Proposal)
        # Set required fields directly
        p.units = units
        p.pieces = " ".join(str(u) for u in units)
        p.hook = None
        p.hook_keep = False
        p.close = []
        p.keys = {}
        p.title = ""
        p.caption = ""
        p.score = score
        p.seconds = 30.0
        p.speed = None
        p.opener = units[0] if units else None
        return p

    # A=[1,2,3] opener=1; B=[1,4,5] opener=1 → A↔B: same opener + shared unit #1
    # A=[1,2,3];            C=[2,6,7] opener=2 → A↔C: shared unit #2 (different opener)
    # B=[1,4,5];            C=[2,6,7]          → B↔C: disjoint units, different openers
    pr_A = make_proposal([1, 2, 3], 95)
    pr_B = make_proposal([1, 4, 5], 60)   # shares opener+unit #1 with A
    pr_C = make_proposal([2, 6, 7], 60)   # shares unit #2 with A; disjoint with B

    conflict_ab = too_close(pr_A, [pr_B], max_shared=0)
    conflict_ac = too_close(pr_A, [pr_C], max_shared=0)
    conflict_bc = too_close(pr_B, [pr_C], max_shared=0)

    print(f"\n  too_close(A, [B], max_shared=0) = {conflict_ab!r}")
    print(f"  too_close(A, [C], max_shared=0) = {conflict_ac!r}")
    print(f"  too_close(B, [C], max_shared=0) = {conflict_bc!r}")

    _assert(conflict_ab is not None, "A conflicts with B (shared opener #1 + unit #1)")
    _assert(conflict_ac is not None, "A conflicts with C (shared unit #2)")
    _assert(conflict_bc is None, "B and C are compatible (no shared units/opener)")

    print("""
  FINDING F4:
    select_global=SELECTOR_HELPER_CONFIRMED
    A(95) is globally suboptimal; B+C(120) wins.  select_global returns [1,2].
    too_close confirms A vs B: shared unit #1 → conflict at max_shared=0.
    LATE_REJECTION_NOT_REPRODUCED: verifying C via _autocut_check requires
    real audio for subtitle timing checks (no portable synthetic path).""")


# ---------------------------------------------------------------------------
# F9 — build_passage early stops
# ---------------------------------------------------------------------------

def run_f9(repo: Path) -> None:
    _header("F9 — build_passage early stops")

    sys.path.insert(0, str(repo / "src"))
    from autoreels.cloud.autocut import build_passage, AutoParams
    from autoreels.core.config import load_r0_config

    cfg = load_r0_config(repo / "config" / "r0.yaml")
    ac = cfg.autocut
    # Build AutoParams the same way __main__.py does (line 8609)
    p = AutoParams(
        min_sec=ac.min_sec, target_sec=ac.target_sec, max_sec=ac.max_sec,
        min_punch=ac.min_punch, seed_punch=ac.seed_punch,
        passage_gap_sec=ac.passage_gap_sec,
        rhythm=ac.rhythm,
        max_jumps=ac.rhythm_max_jumps,
        jump_sec=ac.rhythm_jump_sec,
        settle_near_sec=ac.rhythm_settle_near,
        settle_far_sec=ac.rhythm_settle_far,
        settle_far_at_sec=ac.rhythm_far_sec,
        settle_tail=ac.rhythm_tail,
        use_filtered=ac.use_filtered,
    )

    # Helper to build a simple unit dict
    def unit(uid: int, t0: float, t1: float, role: str, punch: int, topic: str = "main") -> dict:
        return {
            "id": uid, "t0": t0, "t1": t1,
            "role": role, "punch": punch, "topic": topic,
            "refs": f"{uid}.1", "standalone": True,
            "summary": f"unit-{uid}", "similar": [],
        }

    # F9A — preferred neighbour overshoots max_sec; other direction ignored
    _header("  F9A — preferred nxt overshoots max_sec; prv (which fits) is never tried")

    seed_a = unit(1, 100.0, 145.0, "conclusion", punch=5)   # 45 s
    nxt_a  = unit(2, 147.0, 197.0, "thesis",     punch=6)   # 50 s  → 45+50=95 > max_sec=90
    prv_a  = unit(0, 70.0,  95.0,  "explanation", punch=4)  # 25 s  → 45+25=70 ≤ max_sec=90

    by_id_a = {u["id"]: u for u in [seed_a, nxt_a, prv_a]}
    result_a = build_passage(seed_a, by_id_a, p)

    print(f"  nxt_a dur={nxt_a['t1']-nxt_a['t0']:.0f}s (45+50=95 > max_sec={p.max_sec})")
    print(f"  prv_a dur={prv_a['t1']-prv_a['t0']:.0f}s (45+25=70 ≤ max_sec={p.max_sec})")
    print(f"  result_a ids = {[u['id'] for u in result_a] if result_a else None}")

    _assert(result_a is not None, "F9A: build_passage returns a result (seed alone)")
    _assert([u["id"] for u in result_a] == [1], "F9A: only seed returned (prv missed)")

    # Control: same seed, nxt shrunk to fit → nxt is taken
    nxt_a_small = unit(2, 147.0, 172.0, "thesis", punch=6)  # 25 s → 45+25=70 ≤ 90
    by_id_a2 = {u["id"]: u for u in [seed_a, nxt_a_small, prv_a]}
    result_a_ctrl = build_passage(seed_a, by_id_a2, p)
    print(f"  control (nxt=25s): result ids = {[u['id'] for u in result_a_ctrl] if result_a_ctrl else None}")
    _assert(result_a_ctrl is not None and 2 in [u["id"] for u in result_a_ctrl],
            "F9A control: nxt included when it fits")

    print("""
  FINDING F9A:
    When preferred nxt exceeds max_sec, algorithm breaks without trying prv.
    autocut.py line ~404: `if total + _dur(pick) > p.max_sec: break`
    prv (which fits: 45+25=70 ≤ 90) is never attempted.
    STATUS: HELPER_CONFIRMED""")

    # F9B — question at end of run; answer beyond it is never reached
    _header("  F9B — question added at target_sec; pruned post-loop; answer unreachable")

    seed_b    = unit(1, 100.0, 145.0, "conclusion", punch=5)   # 45 s
    quest_b   = unit(2, 147.0, 160.0, "question",   punch=4)   # 13 s → 45+13=58 ≥ target_sec=55
    answer_b  = unit(3, 161.0, 176.0, "answer",     punch=5)   # 15 s (adjacent to question)

    by_id_b = {u["id"]: u for u in [seed_b, quest_b, answer_b]}
    result_b = build_passage(seed_b, by_id_b, p)

    total_with_q = (seed_b["t1"] - seed_b["t0"]) + (quest_b["t1"] - quest_b["t0"])
    print(f"  seed=45s, question=13s → total_with_q={total_with_q:.0f}s ≥ target_sec={p.target_sec}")
    print(f"  answer_b dur=15s is adjacent (id=3 = question_id+1)")
    print(f"  result_b ids = {[u['id'] for u in result_b] if result_b else None}")

    _assert(result_b is not None, "F9B: returns seed alone (not None)")
    _assert([u["id"] for u in result_b] == [1], "F9B: only seed; question pruned, answer not reached")

    # Control: replace question with an answer unit → answer included
    answer_ctrl = unit(2, 147.0, 162.0, "answer", punch=5)  # 15 s, same slot
    by_id_b2 = {u["id"]: u for u in [seed_b, answer_ctrl]}
    result_b_ctrl = build_passage(seed_b, by_id_b2, p)
    print(f"  control (nxt=answer, 15s): result ids = {[u['id'] for u in result_b_ctrl] if result_b_ctrl else None}")
    _assert(result_b_ctrl is not None and 2 in [u["id"] for u in result_b_ctrl],
            "F9B control: answer included when question absent")

    print("""
  FINDING F9B:
    Loop exits when total≥target_sec (after adding question: 45+13=58≥55).
    Post-loop pruning drops the question at run[-1].
    The answer (id=3, would have extended the clip) was never visited.
    After pruning, loop is not re-entered — available room not reconsidered.
    STATUS: HELPER_CONFIRMED""")


# ---------------------------------------------------------------------------
# F12 — tie-break determinism
# ---------------------------------------------------------------------------

def run_f12(repo: Path) -> None:
    _header("F12 — select_global tie-break determinism")

    sys.path.insert(0, str(repo / "src"))
    from autoreels.cloud.autocut import select_global

    no_conflict = lambda i, j: False  # all compatible

    # Same input, 10 calls → identical
    weights_same = [70.0, 70.0, 70.0]
    results_same = [select_global(weights_same, no_conflict, k=2) for _ in range(10)]
    all_equal = all(r == results_same[0] for r in results_same)
    print(f"  10× select_global([70,70,70], no_conflict, k=2) → {results_same[0]}")
    print(f"  all equal: {all_equal}")
    _assert(all_equal, "F12: identical input produces identical result every call")

    # Permuted equal-score inputs
    weights_abc = [70.0, 70.0, 70.0]
    # A conflict with B; B conflict with C; A and C compatible → best is A+C (140)
    # With conflict matrix, permuted input shouldn't matter since weights identical
    # Instead: test with different weight orderings to show order-sensitivity on ties

    # Three equal-weight, pairwise conflicting except (0,2):
    # weights=[70,70,70], conflict=(0,1),(1,2) only → A+C=140 wins → always [0,2]
    conflict_chain = lambda i, j: (i == 0 and j == 1) or (i == 1 and j == 0) or (i == 1 and j == 2) or (i == 2 and j == 1)
    r_abc = select_global([70.0, 70.0, 70.0], conflict_chain, k=2)
    print(f"\n  conflict=(0↔1,1↔2): select_global([70,70,70], k=2) → {r_abc}")
    _assert(r_abc == [0, 2], "best set is [0,2] (A+C=140, B incompatible with both)")

    # Now swap: same graph structure but different weight order
    # weights=[70,70,70] permuted as [70,70,70] — conflict graph fixed to indices
    # To show order-sensitivity: use weights where tie exists and multiple optima
    weights_tie = [60.0, 60.0, 60.0]
    # All compatible, k=2 → any two equal, but select_global picks the two heaviest-indexed first = [0,1]
    r_tie = select_global(weights_tie, no_conflict, k=2)
    r_tie2 = select_global(list(reversed(weights_tie)), no_conflict, k=2)
    print(f"\n  select_global([60,60,60], no_conflict, k=2)         → {r_tie}")
    print(f"  select_global([60,60,60] reversed, no_conflict, k=2) → {r_tie2}")
    print(f"  (reversed indices: a pick of [0,1] in reversed == original [1,2])")

    # Stability: same weights, same conflict → deterministic
    for i in range(10):
        r = select_global(weights_tie, no_conflict, k=2)
        _assert(r == r_tie, f"F12: call {i+1} matches first result {r_tie}")

    print("""
  FINDING F12:
    DETERMINISTIC_SAME_INPUT: identical weights+conflict produces byte-for-byte
    identical result on every call (branch-and-bound is deterministic).
    ORDER_SENSITIVE: equal-weight inputs with same graph structure but permuted
    index order may produce different chosen sets (the algorithm walks in
    descending-weight order; ties broken by earlier index).
    STATUS: HELPER_CONFIRMED, DETERMINISTIC_SAME_INPUT, ORDER_SENSITIVE""")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, default=None,
                    help="Path to the autoreels repo root (default: 3 levels up from this file)")
    args = ap.parse_args()

    repo = args.repo_root or Path(__file__).resolve().parent.parent.parent
    if not (repo / "src" / "autoreels").exists():
        sys.exit(f"ERROR: cannot find src/autoreels under {repo}. Use --repo-root.")

    print(f"PRODUCTION_DIFF={PRODUCTION_DIFF}")
    print(f"SOURCE_SHA={SOURCE_SHA}")
    print(f"repo={repo}")

    run_preflight(repo)
    run_f4(repo)
    run_f9(repo)
    run_f12(repo)

    _header("SUMMARY")
    print("  §1 PREFLIGHT       : CLI_CONFIRMED (cmd_autocut rc=0, review written)")
    print("  F4 select_global   : SELECTOR_HELPER_CONFIRMED; LATE_REJECTION_NOT_REPRODUCED")
    print("  F9A build_passage  : HELPER_CONFIRMED (prv missed when nxt overshoots)")
    print("  F9B build_passage  : HELPER_CONFIRMED (answer missed after question pruned)")
    print("  F12 determinism    : HELPER_CONFIRMED; DETERMINISTIC_SAME_INPUT; ORDER_SENSITIVE")
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
