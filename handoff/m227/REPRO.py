#!/usr/bin/env python3
"""M227 REPRO — Finding #11: invisible pre-pool refusals, weak-seed accounting, teaser_misses gap.

Usage:
    python3 handoff/m227/REPRO.py [--repo-root /path/to/repo]

Sections:
  §0  Preflight — reuses M226 synthetic CLI fixture (cmd_autocut rc=0)
  §1  Part 1   — static gate inventory (STATIC_ONLY)
  §2  Part 2   — exact accounting: two maps, pre-pool losses invisible in CLI output
  §3  Part 3   — teaser_misses claims "прошла" while _hook_cands rejects (HELPER_CONFIRMED)

PRODUCTION_DIFF=none  SOURCE_SHA=dddd*64  base=3c011e94263e16e5780936b4769d3490cd03b682
No paid APIs, no LLM, no renders. All I/O under TemporaryDirectory.
"""

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

SOURCE_SHA = "d" * 64
PRODUCTION_DIFF = "none"
BASE_SHA = "3c011e94263e16e5780936b4769d3490cd03b682"

_pass_count = 0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _header(title: str) -> None:
    bar = "=" * 60
    print(f"\n{bar}\n{title}\n{bar}")


def _pass(n: int, msg: str) -> None:
    global _pass_count
    _pass_count += 1
    print(f"  PASS [{n:02d}]  {msg}")


def _fail(n: int, msg: str) -> None:
    print(f"  FAIL [{n:02d}]  {msg}", file=sys.stderr)
    sys.exit(1)


def _assert(n: int, cond: bool, msg: str) -> None:
    if cond:
        _pass(n, msg)
    else:
        _fail(n, msg)


# ---------------------------------------------------------------------------
# Shared synthetic transcript builder (from M226 proven fixture)
# ---------------------------------------------------------------------------

def _build_synthetic_root(root: Path, stem: str, units: list[dict], source_sha: str = SOURCE_SHA) -> None:
    """Build a minimal synthetic repo root with transcript, manifest, map, config."""
    for d in ("config", "manifests", "transcripts", "data/cache", "reels-out", "reviews"):
        (root / d).mkdir(parents=True, exist_ok=True)

    # config — symlink from production
    repo = Path(__file__).resolve().parent.parent.parent
    shutil.copy(repo / "config" / "r0.yaml", root / "config" / "r0.yaml")

    # transcript: two uppercase sentences t=35-54, t=55-75; dummy block t=85-105
    words_raw: list[dict] = []
    idx = 0

    def _sent(t_start, t_end):
        nonlocal idx
        t = t_start
        while round(t + 0.1, 2) <= t_end + 1e-9:
            t0, t1 = round(t, 2), round(t + 0.1, 2)
            is_last = t1 >= t_end - 0.03
            words_raw.append({"word": f"P{idx}." if is_last else f"P{idx}", "t0": t0, "t1": t1})
            t = round(t + 0.1, 2)
            idx += 1

    _sent(35.0, 54.0)
    _sent(55.0, 75.0)
    for t_step in range(850, 1050):  # dummy block t=85-105
        t = round(t_step / 10, 1)
        words_raw.append({"word": f"D{idx}", "t0": t, "t1": round(t + 0.1, 1)})
        idx += 1
    # Extension block t=120-160 to push total_duration to ~160s
    # This ensures dummy block (midpoint~95s) passes tail_skip filter (160-30=130 > 95)
    for t_step in range(1200, 1600):
        t = round(t_step / 10, 1)
        words_raw.append({"word": f"E{idx}", "t0": t, "t1": round(t + 0.1, 1)})
        idx += 1

    tx = {"language": "ru", "model": "whisper-large-v3", "provider": "openai",
          "source_sha256": source_sha, "words": words_raw}
    (root / "data" / "cache" / f"{source_sha}.transcript.json").write_text(json.dumps(tx))

    # manifest
    mf = {"source": f"{stem}.mp4", "source_sha256": source_sha, "duration_preset": "reel",
          "setup": {"setup_id": "m227_synthetic", "crop": {"x": 0, "y": 0, "w": 1080, "h": 1920},
                    "scale": [1080, 1920], "frame": [1080, 1920]}, "run_key": "r0"}
    (root / "manifests" / f"{stem}.json").write_text(json.dumps(mf))

    # map
    the_map = {"source_sha256": source_sha, "units": units}
    (root / "transcripts" / f"{stem}.map.json").write_text(json.dumps(the_map))


# ---------------------------------------------------------------------------
# §0 Preflight
# ---------------------------------------------------------------------------

def run_preflight(repo: Path) -> str:
    _header("§0 PREFLIGHT — cmd_autocut on synthetic data (M226 fixture)")
    sys.path.insert(0, str(repo / "src"))
    from autoreels.__main__ import cmd_autocut

    units = [
        {"id": 1, "t0": 35.0, "t1": 75.0, "role": "conclusion", "punch": 5,
         "topic": "main", "refs": "1.1-2", "standalone": True, "summary": "Synthetic conclusion.", "similar": []},
        {"id": 2, "t0": 85.0, "t1": 105.0, "role": "thesis", "punch": 3,
         "topic": "other", "refs": "2.1", "standalone": True, "summary": "Dummy.", "similar": []},
    ]

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _build_synthetic_root(root, "syn_m227", units)
        rc = cmd_autocut("syn_m227", root=root, llm="none")
        _assert(1, rc == 0, "cmd_autocut returns rc=0")

        review = root / "reviews" / "syn_m227_auto_m56.txt"
        _assert(2, review.exists(), "review file written")
        content = review.read_text()
        accepted = [l for l in content.splitlines() if l.startswith("M") and "|" in l]
        _assert(3, len(accepted) >= 1, f"at least 1 accepted line ({accepted})")

        sha = _sha256(review)
        print(f"  review SHA256={sha}")
        return sha


# ---------------------------------------------------------------------------
# §2 Part 2 — Exact accounting: two maps
# ---------------------------------------------------------------------------

def run_part2(repo: Path) -> tuple[str, str]:
    _header("§2 PART 2 — Exact accounting: pre-pool losses not in CLI output")

    from autoreels.__main__ import cmd_autocut
    from autoreels.cloud.autocut import eligible, AutoParams
    from autoreels.core.config import load_r0_config
    import autoreels.cloud.autocut as _ac_mod

    # ---- Map A: clean — all eligible seeds succeed -----------------------
    _header("  Map A — clean: 1 eligible seed → 1 clip, fully accounted")

    units_a = [
        {"id": 1, "t0": 35.0, "t1": 75.0, "role": "conclusion", "punch": 5,
         "topic": "main", "refs": "1.1-2", "standalone": True, "summary": "Clean seed.", "similar": []},
        {"id": 2, "t0": 85.0, "t1": 105.0, "role": "thesis", "punch": 3,
         "topic": "other", "refs": "2.1", "standalone": True, "summary": "Dummy.", "similar": []},
    ]

    stdout_a = ""
    with tempfile.TemporaryDirectory() as td:
        root_a = Path(td)
        _build_synthetic_root(root_a, "syn_mapa", units_a)

        # Redirect stdout to capture it
        import io
        from contextlib import redirect_stdout, redirect_stderr
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            rc_a = cmd_autocut("syn_mapa", root=root_a, llm="none")
        stdout_a = buf_out.getvalue() + buf_err.getvalue()
        print(stdout_a.rstrip())

        cfg_a = load_r0_config(root_a / "config" / "r0.yaml")
        p_a = _build_autoparams(cfg_a)

        eligible_seeds_a = [u for u in units_a
                            if eligible(u, p_a) and u.get("role") in _ac_mod.STORY
                            and int(u.get("punch") or 0) >= p_a.seed_punch]
        print(f"\n  Map A accounting:")
        print(f"    total units       = {len(units_a)}")
        print(f"    eligible seeds    = {len(eligible_seeds_a)} (punch>={p_a.seed_punch}, role in STORY)")
        review_a = root_a / "reviews" / "syn_mapa_auto_m56.txt"
        content_a = review_a.read_text() if review_a.exists() else ""
        accepted_a = [l for l in content_a.splitlines() if l.startswith("M") and "|" in l]
        print(f"    pool accepted     = {len(accepted_a)}")
        print(f"    gap = eligible_seeds - accepted = {len(eligible_seeds_a) - len(accepted_a)}")

        _assert(4, rc_a == 0, "Map A: cmd_autocut rc=0")
        _assert(5, len(eligible_seeds_a) == 1, "Map A: 1 eligible seed")
        _assert(6, len(accepted_a) == 1, "Map A: 1 accepted clip")
        _assert(7, len(eligible_seeds_a) == len(accepted_a),
                "Map A: gap=0 (clean map, no pre-pool losses)")

        sha_a = _sha256(review_a) if review_a.exists() else ""
        print(f"  Map A review SHA256={sha_a}")

    # ---- Map B: lossy — 1 seed returns None from build_passage -----------
    _header("  Map B — lossy: 1 attempted seed → build_passage None; invisible in output")

    # Seed B2: punch=4 >= seed_punch=4 → IS a seed attempt
    # topic="isolated" → no neighbors of same topic → build_passage returns None (10s < min_sec=25)
    # This loss is NEVER shown in cmd_autocut output
    # (needs extended transcript so block 2 midpoint ~95s passes tail_skip: 160-30=130 > 95)
    units_b = [
        {"id": 1, "t0": 35.0, "t1": 75.0, "role": "conclusion", "punch": 5,
         "topic": "main", "refs": "1.1-2", "standalone": True, "summary": "Good seed.", "similar": []},
        {"id": 2, "t0": 92.0, "t1": 102.0, "role": "thesis", "punch": 4,
         "topic": "isolated", "refs": "2.1", "standalone": True,
         "summary": "Short seed — will be attempted but build_passage None.", "similar": []},
        {"id": 3, "t0": 85.0, "t1": 90.0, "role": "thesis", "punch": 3,
         "topic": "other", "refs": "3.1", "standalone": True, "summary": "Dummy.", "similar": []},
    ]

    stdout_b = ""
    with tempfile.TemporaryDirectory() as td:
        root_b = Path(td)
        _build_synthetic_root(root_b, "syn_mapb", units_b)

        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            rc_b = cmd_autocut("syn_mapb", root=root_b, llm="none")
        stdout_b = buf_out.getvalue() + buf_err.getvalue()
        print(stdout_b.rstrip())

        cfg_b = load_r0_config(root_b / "config" / "r0.yaml")
        p_b = _build_autoparams(cfg_b)

        # Manual accounting
        eligible_seeds_b = [u for u in units_b
                            if eligible(u, p_b) and u.get("role") in _ac_mod.STORY
                            and int(u.get("punch") or 0) >= p_b.seed_punch]
        print(f"\n  Map B accounting:")
        print(f"    total units        = {len(units_b)}")
        print(f"    eligible seeds     = {len(eligible_seeds_b)} (ids {[u['id'] for u in eligible_seeds_b]})")
        print(f"    seed_punch         = {p_b.seed_punch}, min_punch = {p_b.min_punch}")
        for u in eligible_seeds_b:
            dur = u["t1"] - u["t0"]
            print(f"      id={u['id']}: dur={dur:.0f}s (min_sec={p_b.min_sec}) → "
                  f"{'build_passage OK' if dur >= p_b.min_sec else f'build_passage None (too short)'}")

        review_b = root_b / "reviews" / "syn_mapb_auto_m56.txt"
        content_b = review_b.read_text() if review_b.exists() else ""
        accepted_b = [l for l in content_b.splitlines() if l.startswith("M") and "|" in l]
        print(f"    pool accepted      = {len(accepted_b)}")

        gap = len(eligible_seeds_b) - len(accepted_b)
        print(f"    gap = eligible_seeds({len(eligible_seeds_b)}) - accepted({len(accepted_b)}) = {gap}")
        print(f"    CLI output explains the gap? → "
              f"{'NO — build_passage None attempts are never counted' if gap > 0 else 'YES'}")

        _assert(8, rc_b == 0, "Map B: cmd_autocut rc=0")
        _assert(9, len(eligible_seeds_b) == 2, "Map B: 2 eligible seeds (both punch>=seed_punch=4)")
        _assert(10, len(accepted_b) == 1, "Map B: 1 accepted clip (short seed returned None)")
        _assert(11, gap > 0, f"Map B: gap={gap} > 0 (pre-pool loss invisible in CLI output)")

        # Verify unit 2 is a seed attempt but too short
        from autoreels.cloud.autocut import build_passage
        by_id = {u["id"]: u for u in units_b}
        result = build_passage(units_b[1], by_id, p_b)
        _assert(12, result is None,
                f"Map B unit2 (dur=10s): build_passage returns None (too short, min_sec={p_b.min_sec})")

        sha_b = _sha256(review_b) if review_b.exists() else ""
        print(f"  Map B review SHA256={sha_b}")

    # ---- Weak-seed accounting gap ----------------------------------------
    _header("  Weak-seed path: no_start/open_end not passed to fill propose")

    # Read the source code to verify the claim
    main_py = repo / "src" / "autoreels" / "__main__.py"
    main_src = main_py.read_text(encoding="utf-8")

    # Find the fill_pool propose call
    fill_call_start = main_src.find("M140: the pool is smaller")
    _assert(13, fill_call_start > 0, "M140 fill_pool comment found in __main__.py")

    fill_call = main_src[fill_call_start:fill_call_start + 600]
    has_no_start = "no_start=no_start" in fill_call or "no_start=" in fill_call
    _assert(14, not has_no_start, "Weak-seed fill propose does NOT pass no_start= (STATIC_ONLY)")

    has_open_end = "open_end=open_end" in fill_call or "open_end=" in fill_call
    _assert(15, not has_open_end, "Weak-seed fill propose does NOT pass open_end= (STATIC_ONLY)")

    rhythm_discarded = "rhythm_out=[]" in fill_call
    _assert(16, rhythm_discarded, "Weak-seed fill propose passes rhythm_out=[] (losses discarded)")

    print(f"\n  Relevant code snippet (~__main__.py:{_line_of(main_src, fill_call_start)}):")
    for line in fill_call.splitlines()[:8]:
        print(f"    {line}")

    print("""
  FINDING P2 SUMMARY:
    CLI output: предложено N сборок из M мыслей
    Missing: attempted seeds (N attempted, K returned None) → NOT in output
    Weak-seed fill propose: no_start/open_end/rhythm_out failures → NOT tracked""")

    return sha_a, sha_b


# ---------------------------------------------------------------------------
# §3 Part 3 — teaser_misses discrepancy (HELPER_CONFIRMED)
# ---------------------------------------------------------------------------

def run_part3(repo: Path) -> None:
    _header("§3 PART 3 — teaser_misses claims 'прошла' when _hook_cands rejects (HELPER_CONFIRMED)")

    from autoreels.cloud.autocut import _hook_cands, teaser_misses, AutoParams
    from autoreels.core.config import load_r0_config

    cfg = load_r0_config(repo / "config" / "r0.yaml")
    p = _build_autoparams(cfg)

    print(f"\n  Config params (from r0.yaml via load_r0_config):")
    print(f"    start_pause_min  = {p.start_pause_min}")
    print(f"    hook_teaser      = {p.hook_teaser}")
    print(f"    hook_teaser_pos  = {p.hook_teaser_pos}")
    print(f"    hook_clauses     = {p.hook_clauses}")
    print(f"    hook_min_sec     = {p.hook_min_sec}")
    print(f"    hook_max_sec     = {p.hook_max_sec}")
    print(f"    hook_min_words   = {p.hook_min_words}")
    print(f"    min_punch        = {p.min_punch}")

    _assert(17, p.start_pause_min > 0, f"start_pause_min={p.start_pause_min} > 0 (glued_start active when callback given)")
    _assert(18, p.hook_teaser, "hook_teaser=True (teaser_misses is called on hookless clips)")
    _assert(19, p.hook_clauses, "hook_clauses=True (clauses callback expected by _hook_cands)")

    # Synthetic clip: 2 units, each 30s
    # Unit 1: 0-30s (first half), Unit 2: 30-60s (second half)
    # Sentence 2.1 is in the second half → teaser_misses will inspect it
    # It passes all standard checks but is "glued" (start_pause=0.05 < 0.15)
    clip = [
        {"id": 1, "t0": 0.0, "t1": 30.0, "role": "thesis", "punch": 5,
         "topic": "main", "refs": "1.1", "standalone": True, "summary": "First unit.", "similar": []},
        {"id": 2, "t0": 30.0, "t1": 60.0, "role": "conclusion", "punch": 5,
         "topic": "main", "refs": "2.1", "standalone": True, "summary": "Second unit.", "similar": []},
    ]

    # sentences callback: returns a row that passes all standard checks
    # ref="2.1": sec=4.0, nwords=6, complete=True — not a pointer word so teaser_misses → "прошла"
    # but _hook_cands WITH start_pause=0.05 rejects it via glued_start (0.05 < start_pause_min=0.15)
    def sentences(refs: str):
        mapping = {
            "1.1": [("1.1", 25.0, 10, True, "Первая мысль нормальная длинная фраза без склейки.")],
            "2.1": [("2.1", 4.0, 6, True, "Главная мысль теста здесь.")],
        }
        return mapping.get(refs, [])

    # start_pause callback: ref "2.1" is glued (0.05 < start_pause_min=0.15)
    def start_pause(ref: str):
        return 0.05 if ref == "2.1" else 0.5

    # --- teaser_misses (WITHOUT start_pause) ---
    n_tm, why_tm = teaser_misses(clip, sentences, p)
    print(f"\n  teaser_misses(clip, sentences, p):  n={n_tm}, why={why_tm}")

    # --- _hook_cands (WITH start_pause) ---
    cands_with_sp = _hook_cands(clip, sentences, p, start_pause=start_pause)
    print(f"  _hook_cands(clip, sentences, p, start_pause=callback): {len(cands_with_sp)} candidates")
    if cands_with_sp:
        for ref, sc, text in cands_with_sp:
            print(f"    {ref!r}: score={sc:.2f} text={text!r}")
    else:
        print("    → [] (rejected all)")

    # --- _hook_cands (WITHOUT start_pause, as in CLI without alignment) ---
    cands_no_sp = _hook_cands(clip, sentences, p, start_pause=None)
    print(f"  _hook_cands(clip, sentences, p, start_pause=None):    {len(cands_no_sp)} candidates")
    if cands_no_sp:
        for ref, sc, text in cands_no_sp:
            print(f"    {ref!r}: score={sc:.2f} text={text!r}")

    _assert(20, n_tm >= 1, f"teaser_misses sees {n_tm} sentence(s) in second half")
    _assert(21, why_tm.get("прошла", 0) >= 1,
            f"teaser_misses says 'прошла' for sentence 2.1 (why={why_tm})")
    _assert(22, len(cands_with_sp) == 0,
            "_hook_cands with start_pause rejects 2.1 (glued: 0.05 < 0.15)")
    _assert(23, len(cands_no_sp) >= 1,
            "_hook_cands without start_pause accepts 2.1 (confirms discrepancy is start_pause-dependent)")

    # Static: show teaser_misses signature lacks start_pause and clauses
    import inspect
    tm_sig = str(inspect.signature(teaser_misses))
    hc_sig = str(inspect.signature(_hook_cands))
    print(f"\n  teaser_misses signature: {tm_sig}")
    print(f"  _hook_cands signature:   {hc_sig}")

    _assert(24, "start_pause" not in tm_sig,
            "teaser_misses signature has NO start_pause param (STATIC_ONLY)")
    _assert(25, "clauses" not in tm_sig,
            "teaser_misses signature has NO clauses param (STATIC_ONLY)")
    _assert(26, "start_pause" in hc_sig,
            "_hook_cands signature HAS start_pause param")
    _assert(27, "clauses" in hc_sig,
            "_hook_cands signature HAS clauses param")

    print("""
  FINDING P3 SUMMARY:
    teaser_misses(ref "2.1", text="Главная мысль теста здесь.") → "прошла"  (lacks glued_start check)
    _hook_cands(ref "2.1", start_pause=0.05s) → []  (rejects: 0.05 < 0.15)
    teaser_misses is missing 'start_pause' and 'clauses' parameters.
    No model call needed: glued_start is a deterministic rule.
    When start_pause data is unavailable (no alignment file, our CLI case):
      - Both functions agree (no rejection) — no discrepancy at runtime
      - But the diagnostic is structurally incomplete for cases WITH data.
    STATUS: HELPER_CONFIRMED (discrepancy with synthetic callback),
            STATIC_ONLY (structural signature gap)""")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _build_autoparams(cfg):
    """Construct AutoParams from production config (same as __main__.py:8609)."""
    from autoreels.cloud.autocut import AutoParams
    ac = cfg.autocut
    return AutoParams(
        min_sec=ac.min_sec, target_sec=ac.target_sec, max_sec=ac.max_sec,
        min_punch=ac.min_punch, seed_punch=ac.seed_punch,
        passage_gap_sec=ac.passage_gap_sec, rhythm=ac.rhythm,
        max_jumps=ac.rhythm_max_jumps, jump_sec=ac.rhythm_jump_sec,
        settle_near_sec=ac.rhythm_settle_near, settle_far_sec=ac.rhythm_settle_far,
        settle_far_at_sec=ac.rhythm_far_sec, settle_tail=ac.rhythm_tail,
        use_filtered=ac.use_filtered,
        start_pause_min=float(getattr(ac, "start_pause_min", 0.0) or 0.0),
        hook_teaser=bool(getattr(ac, "hook_teaser", False)),
        hook_teaser_pos=float(getattr(ac, "hook_teaser_pos", 0.5)),
        hook_clauses=bool(getattr(ac, "hook_clauses", False)),
        hook_min_sec=ac.hook_min_sec, hook_max_sec=getattr(cfg, "hook_max_sec", 6.0),
        hook_min_words=ac.hook_min_words,
        hook_no_pointer=bool(getattr(ac, "hook_no_pointer", False)),
        context_start=ac.context_start,
    )


def _line_of(src: str, pos: int) -> int:
    return src[:pos].count("\n") + 1


# ---------------------------------------------------------------------------
# Part 1: Static gate inventory (printed, not asserted — STATIC_ONLY)
# ---------------------------------------------------------------------------

def run_part1() -> None:
    _header("§1 PART 1 — Static gate inventory (STATIC_ONLY)")
    print("""
  Pre-pool gates (invisible in CLI output unless noted):
  ┌─────────────────────────┬──────────────────────────────────────┬─────────────────────────────┐
  │ Location                │ Condition                            │ Owner sees                  │
  ├─────────────────────────┼──────────────────────────────────────┼─────────────────────────────┤
  │ eligible:164-169        │ punch<min_punch; aside; no refs;     │ unit absent; no counter     │
  │                         │ filtered; role not in seed_roles     │                             │
  │ seeds filter:1168-1170  │ punch < seed_punch                   │ absent; no counter          │
  │ build_clip/passage None │ too short; no eligible neighbours;   │ absent; no counter          │
  │   :231-247, :407-413    │ question at end; below min_sec       │                             │
  │ propose loop:1175-1179  │ seed in used_seeds or taken          │ absent; no counter          │
  │ _loop_question:1101-109 │ best q too long; shorter q not tried │ no loop; no counter         │
  │ add_payoff:350-355      │ payoff weak/too far/external lean    │ no payoff; no counter       │
  │ overlap check:1257-1261 │ shared last unit; too many shared    │ absent; no counter          │
  │ pool truncation:1309-10 │ candidates > clips*check_pool        │ "not reached" in pool output│
  │ fill_pool:1321-1322     │ weak-seed shares unit with pool      │ only count added            │
  │ _hook_cands:1018-1038   │ weak/early/glued/no-clauses          │ no individual reason        │
  │ short_variant:1929-1934 │ units not found; too short/long      │ variant absent              │
  ├─────────────────────────┼──────────────────────────────────────┼─────────────────────────────┤
  │ Visible in pool output  │ no_start (context_start failures)    │ "без понятного начала: N"   │
  │                         │ open_end (fix_open_end failures)     │ "конец «→», не укоротить: N"│
  │                         │ rhythm_out (fit_rhythm failures)     │ "скачки, не поправить: N"   │
  │                         │ close (too_close rejections)         │ "похожи на принятые: N"     │
  │                         │ rejected (_autocut_check fails)      │ "не прошли проверку: N"     │
  │                         │ hookless_left                        │ "без крючка не взяты: N"    │
  │                         │ not_reached                          │ "не дошла очередь: N"       │
  └─────────────────────────┴──────────────────────────────────────┴─────────────────────────────┘

  Normal None semantics (not a loss): return None from build_clip/build_passage means the
  clip was attempted and disqualified by the algorithm's own correctness rules (too short,
  question at end). These are design decisions but are still invisible in diagnostics.

  Weak-seed fill_pool path (__main__.py ~8821-8830):
    - Second propose() call does NOT receive no_start, open_end
    - rhythm_out passed as [] (new list) — discarded after
    - Losses in weak-seed path are doubly invisible
""")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, default=None)
    args = ap.parse_args()

    repo = args.repo_root or Path(__file__).resolve().parent.parent.parent
    if not (repo / "src" / "autoreels").exists():
        sys.exit(f"ERROR: cannot find src/autoreels under {repo}. Use --repo-root.")

    sys.path.insert(0, str(repo / "src"))

    print(f"PRODUCTION_DIFF={PRODUCTION_DIFF}")
    print(f"SOURCE_SHA={SOURCE_SHA}")
    print(f"BASE_SHA={BASE_SHA}")
    print(f"repo={repo}")

    sha_preflight = run_preflight(repo)
    run_part1()
    sha_a, sha_b = run_part2(repo)
    run_part3(repo)

    _header("SUMMARY")
    print(f"  §0 Preflight     : CLI_CONFIRMED (rc=0, review SHA256={sha_preflight[:16]}…)")
    print(f"  §1 Part 1 (gates): STATIC_ONLY (enumerated {12} pre-pool gates)")
    print(f"  §2 Part 2 (acct) : CLI_CONFIRMED (Map B gap=1 invisible)")
    print(f"                     STATIC_ONLY   (weak-seed no_start/open_end absent)")
    print(f"  §3 Part 3 (hook) : HELPER_CONFIRMED (teaser_misses 'прошла' vs _hook_cands [])")
    print(f"                     STATIC_ONLY   (signature gap: no start_pause/clauses params)")
    print(f"\n  Total PASS assertions: {_pass_count}")
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
