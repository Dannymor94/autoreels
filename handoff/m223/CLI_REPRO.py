"""M223-R2 — CLI-based evidence for three P1 findings in cloud/autocut.py.

Exercises the REAL cmd_autocut() path through __main__.py:
  - load_r0_config(root/config/r0.yaml) → AutoParams → propose() → global selector → validation
  - production config: generator=mixed, select=global, hook_clauses=True,
    start_strict=True, answer_start=True, start_morph=True
  - no paid APIs, no real renders, no writes to the production repo
  - isolated temp root; synthetic transcript, map, manifest, align.json

Run:
    python handoff/m223/CLI_REPRO.py
    echo "exit: $?"

Exit 0 = all checks PASS.  Non-zero = at least one FAIL.

Special mode (for negative subprocess test):
    python handoff/m223/CLI_REPRO.py --check-config PATH
    Loads r0.yaml from PATH, checks required keys; exits 0 if all match, 1 if any mismatch.
"""
from __future__ import annotations

import contextlib, hashlib, inspect, io, json, shutil, subprocess, sys
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Locate project root and bootstrap path
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    here = Path(__file__).resolve()
    for p in [here, *here.parents]:
        if (p / "config" / "r0.yaml").exists():
            return p
    raise RuntimeError("project root not found")

ROOT = _project_root()
sys.path.insert(0, str(ROOT / "src"))

from autoreels.core.models import Manifest, Transcript, Word, SetupProfile, Crop
from autoreels.core.config import load_r0_config
from autoreels.cloud.autocut import propose as _real_propose

# ---------------------------------------------------------------------------
# REQUIRED config values (from production config/r0.yaml)
# ---------------------------------------------------------------------------

REQUIRED_CONFIG = {
    "hook_clauses":  True,
    "start_strict":  True,
    "answer_start":  True,
    "start_morph":   True,
    "generator":     "mixed",
    "select":        "global",
}

FAILURES: list[str] = []

def check(label: str, condition: bool, detail: str = "") -> None:
    status = "OK" if condition else "FAIL"
    msg = f"  {status} {label}" + (f": {detail}" if detail else "")
    print(msg)
    if not condition:
        FAILURES.append(label)

# ---------------------------------------------------------------------------
# --check-config mode (for negative subprocess test)
# ---------------------------------------------------------------------------

if len(sys.argv) >= 3 and sys.argv[1] == "--check-config":
    cfg_path = Path(sys.argv[2])
    _r0 = load_r0_config(cfg_path)
    _ac = _r0.autocut
    _ok = True
    for _k, _v in REQUIRED_CONFIG.items():
        if getattr(_ac, _k, None) != _v:
            print(f"MISMATCH {_k}: {getattr(_ac, _k, None)!r} != {_v!r}")
            _ok = False
    sys.exit(0 if _ok else 1)

# ---------------------------------------------------------------------------
# Synthetic transcript:
#   Block A: 40.0–69.5s  (u1, punch=5, refs="1.1-4")  — gap to Block B = 10.5s < 30s → merged
#   Block B: 80.0–108.0s (u2, punch=4, refs="2.1-4")  — merged with Block A into one clip
#   Block C: 150.0–178.0s(u3, punch=5, refs="3.1-4")  — gap from Block B = 42s > 30s → separate
#   Block D: 200.0–220.0s(tail block, filtered)         — total_duration=220, tail_thr=190
#
# Tail filter: midpoint A=54.75, B=94.0, C=164.0 all < 190 → survive
#              midpoint D=210 > 190 → filtered
#
# Merged clip [u1,u2]: 68s. Teaser threshold = 50% = 26.5s cumulative.
#   S1 "Да, тревога..." starts at 0s (0%)     → before threshold → skipped
#   S2 starts at 5.5s  (10.4%)               → before threshold → skipped
#   S3 starts at 10.5s (19.8%)               → before threshold → skipped
#   S4 "Эволюция..." starts at 15.5s (29.2%) → before threshold → skipped
#        sec = 11.0s (> hook_max_sec=6) → needs clauses; clause (4-7) starts at ~32% → also skipped
#   S5 "Принятие тревоги..." starts at 26.5s (50.0%) → eligible (not strictly < 50%)!
#
# S1 = answer-start sentence (Finding #2)
# S4 = long sentence with clause via align.json (Finding #3 threshold test)
# S5 = first teaser candidate (Finding #2 teaser case)
# ---------------------------------------------------------------------------

def _w(word: str, t0: float, t1: float) -> dict:
    return {"word": word, "t0": t0, "t1": t1}

SYNTHETIC_WORDS: list[dict] = [
    # Block A, S1: "Да, тревога часто возникает перед переменами."
    _w("Да,",          40.0, 40.5),
    _w("тревога",      40.6, 41.3),
    _w("часто",        41.4, 41.9),
    _w("возникает",    42.0, 43.0),
    _w("перед",        43.1, 43.6),
    _w("переменами.",  43.7, 45.5),
    # Block A, S2: gap 1.0s (45.5→46.5); "Страх сигнализирует об изменениях."
    _w("Страх",          46.5, 47.1),
    _w("сигнализирует",  47.2, 48.6),
    _w("об",             48.7, 49.1),
    _w("изменениях.",    49.2, 51.5),
    # Block A, S3: gap 1.0s; "Это нормальная реакция организма."
    _w("Это",          52.5, 53.1),
    _w("нормальная",   53.2, 54.1),
    _w("реакция",      54.2, 54.9),
    _w("организма.",   55.0, 57.5),
    # Block A, S4: gap 1.0s; "Эволюция создала тревогу, как важный сигнал опасности."
    # NOTE: "тревогу," ends in comma → potential clause edge via align.json
    _w("Эволюция",     58.5, 59.6),
    _w("создала",      59.7, 60.5),
    _w("тревогу,",     60.6, 61.0),   # comma: clause break if pause follows in alignment
    _w("как",          61.5, 61.9),
    _w("важный",       62.0, 62.5),
    _w("сигнал",       62.6, 63.2),
    _w("опасности.",   63.3, 69.5),
    # [gap 69.5→80.0 = 10.5s < passage_gap_sec=30s → Block A and B merge into one clip]
    # Block B, S5: "Принятие тревоги снижает её интенсивность."
    # This is the FIRST ELIGIBLE TEASER (starts at exactly 50% cumulative)
    _w("Принятие",      80.0, 80.7),
    _w("тревоги",       80.8, 81.5),
    _w("снижает",       81.6, 82.3),
    _w("её",            82.4, 82.8),
    _w("интенсивность.", 82.9, 86.0),
    # Block B, S6: gap 0.5s; "Многие люди учатся жить с тревогой."
    _w("Многие",    86.5, 87.1),
    _w("люди",      87.2, 87.8),
    _w("учатся",    87.9, 88.6),
    _w("жить",      88.7, 89.2),
    _w("с",         89.3, 89.6),
    _w("тревогой.", 89.7, 92.5),
    # Block B, S7: gap 0.5s; "Это делает жизнь тяжелее и непредсказуемее."
    _w("Это",              93.0, 93.5),
    _w("делает",           93.6, 94.3),
    _w("жизнь",            94.4, 95.0),
    _w("тяжелее",          95.1, 95.9),
    _w("и",                96.0, 96.3),
    _w("непредсказуемее.", 96.4, 99.0),
    # Block B, S8: gap 0.5s; "Начните замечать тревогу сегодня."
    _w("Начните",   99.5, 100.3),
    _w("замечать",  100.4, 101.2),
    _w("тревогу",   101.3, 102.0),
    _w("сегодня.",  102.1, 108.0),
    # [gap 108.0→150.0 = 42s > passage_gap_sec=30s → separate clip for u3]
    # Block C, S9-S12 (u3 clip, 150.0–178.0s)
    # All sentences: 5+ words, no BACK_START, standalone (passes context_min_words=4)
    _w("Принятие",    150.0, 150.8),
    _w("тревоги",     150.9, 151.6),
    _w("делает",      151.7, 152.4),
    _w("нас",         152.5, 152.8),
    _w("сильнее.",    152.9, 157.0),
    _w("Страх",       157.5, 158.1),
    _w("перемен",     158.2, 158.9),
    _w("присутствует",159.0, 160.2),
    _w("у",           160.3, 160.5),
    _w("каждого.",    160.6, 162.0),
    _w("Регулярная",  163.0, 164.0),
    _w("практика",    164.1, 164.9),
    _w("снижает",     165.0, 165.7),
    _w("интенсивность",165.8, 167.0),
    _w("тревоги.",    167.1, 170.0),
    _w("Сделайте",    171.0, 171.8),
    _w("первый",      171.9, 172.4),
    _w("шаг",         172.5, 172.9),
    _w("уже",         173.0, 173.3),
    _w("сегодня.",    173.4, 178.0),
    # [gap 178.0→200.0 = 22s]
    # Block D (tail, filtered): 200.0–220.0s, midpoint=210 > 220-30=190 → filtered
    _w("Всем",         200.0, 200.8),
    _w("спасибо.",     200.9, 204.0),
    _w("До",           205.0, 205.3),
    _w("встречи",      205.4, 206.1),
    _w("на",           206.2, 206.5),
    _w("следующей",    206.6, 207.5),
    _w("неделе.",      207.6, 212.0),
    _w("Это",          213.0, 213.4),
    _w("был",          213.5, 213.9),
    _w("наш",          214.0, 214.4),
    _w("выпуск.",      214.5, 220.0),
]

SOURCE_SHA = "a" * 64

SYNTHETIC_MAP = {
    "source_sha256": SOURCE_SHA,
    "transcript_key": "",
    "units": [
        {
            "id": 1, "role": "thesis", "punch": 5,
            "t0": "40.0", "t1": "69.5",
            "topic": "тревога", "standalone": True,
            "refs": "1.1-4", "missing": False, "filtered": False,
            "voice": {"energy": 65.0, "rate": 2.5},
            "summary": "тревога как нормальная реакция",
            "similar": [], "refers": None,
        },
        {
            "id": 2, "role": "thesis", "punch": 4,
            "t0": "80.0", "t1": "108.0",
            "topic": "тревога", "standalone": True,
            "refs": "2.1-4", "missing": False, "filtered": False,
            "voice": {"energy": 60.0, "rate": 2.5},
            "summary": "принятие тревоги снижает интенсивность",
            "similar": [], "refers": None,
        },
        {
            "id": 3, "role": "thesis", "punch": 5,
            "t0": "150.0", "t1": "178.0",
            "topic": "финал", "standalone": True,
            "refs": "3.1-4", "missing": False, "filtered": False,
            "voice": {"energy": 60.0, "rate": 2.0},
            "summary": "благодарность за просмотр",
            "similar": [], "refers": None,
        },
    ],
    "topics": [],
}

# Align.json: forced alignment (Whisper times as aligned, except S4 creates clause break)
# "тревогу," t0=60.6: aligned_end=61.0 (shortened to create gap to "как")
# "как" t0=61.5: aligned_start=61.6 (extra 0.1s delay → gap 61.0→61.6 = 0.6s > hook_clause_pause=0.12)
# "опасности." t0=63.3: aligned_end=65.0 (shortened for clause duration = 65.0-61.6=3.4s ∈ [1.5,6.0])
ALIGN_OVERRIDES = {
    60600: (60.6, 61.0),   # "тревогу," t0=60.6ms → (start=60.6, end=61.0)
    61500: (61.6, 61.9),   # "как" t0=61.5ms     → (start=61.6, end=61.9)
    63300: (63.3, 65.0),   # "опасности." t0=63.3ms → (start=63.3, end=65.0)
}

def _build_align_json() -> dict:
    words_al = []
    for w in SYNTHETIC_WORDS:
        k = round(w["t0"] * 1000)
        if k in ALIGN_OVERRIDES:
            s, e = ALIGN_OVERRIDES[k]
        else:
            s, e = w["t0"], w["t1"]
        words_al.append({"t0": w["t0"], "start": s, "end": e})
    return {
        "version": 1,
        "source_sha256": SOURCE_SHA,
        "words": words_al,
        "untranscribed": [],
    }


def _build_manifest() -> dict:
    return {
        "source": "synthetic_test.mp4",
        "source_path": "",
        "source_sha256": SOURCE_SHA,
        "source_hash_scheme": "full",
        "source_kind": "lecture",
        "duration_preset": "shorts",
        "setup": {
            "setup_id": "synth",
            "crop": {"x": 100, "y": 0, "w": 540, "h": 960},
            "scale": [1080, 1920],
            "frame": [1920, 1080],
            "rotation_deg": 0.0,
        },
        "run_key": "synth_run_key",
        "transcript_params_key": "",
        "selection_source": "",
        "status": "pending",
        "reels": [],
    }


def _build_transcript() -> dict:
    return {
        "language": "ru",
        "words": SYNTHETIC_WORDS,
        "model": "synthetic",
        "provider": "synthetic",
        "prompt_hash": "",
        "prompt_leak_removed": 0,
        "source_sha256": SOURCE_SHA,
    }


def setup_isolated_root(tmp: Path) -> None:
    stem = "synth"
    for d in ("config", "manifests", "transcripts", "data/cache", "reviews", "out"):
        (tmp / d).mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "config" / "r0.yaml", tmp / "config" / "r0.yaml")
    (tmp / "manifests" / f"{stem}.json").write_text(json.dumps(_build_manifest()), encoding="utf-8")
    (tmp / "data" / "cache" / "synth_tx.transcript.json").write_text(
        json.dumps(_build_transcript()), encoding="utf-8"
    )
    (tmp / "transcripts" / f"{stem}.map.json").write_text(
        json.dumps(SYNTHETIC_MAP), encoding="utf-8"
    )
    (tmp / "transcripts" / f"{stem}.align.json").write_text(
        json.dumps(_build_align_json()), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Config verification
# ---------------------------------------------------------------------------

def verify_config(ac, label: str = "config") -> bool:
    ok = True
    for key, expected in REQUIRED_CONFIG.items():
        val = getattr(ac, key, None)
        if val != expected:
            print(f"  FAIL {key}: {val!r} (expected {expected!r})")
            FAILURES.append(f"{label}:{key}")
            ok = False
        else:
            print(f"  OK {key}: {val!r}")
    return ok


# ---------------------------------------------------------------------------
# SHA256 helpers
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# ---------------------------------------------------------------------------
# CLI runners
# ---------------------------------------------------------------------------

def _run_cmd_autocut(tmp: Path, out_name: str, **kwargs) -> dict:
    """Run cmd_autocut on isolated root; capture stdout/stderr; return evidence dict."""
    from autoreels.__main__ import cmd_autocut
    propose_calls: list[tuple] = []
    select_global_calls: list[tuple] = []

    def spy_propose(*args, **kw):
        propose_calls.append((args, kw))
        return _real_propose(*args, **kw)

    from autoreels.cloud.autocut import select_global as _real_sg

    def spy_select_global(weights, conflict, k, *a, **kw):
        result = _real_sg(weights, conflict, k, *a, **kw)
        select_global_calls.append({"weights": weights, "k": k, "result": result})
        return result

    buf_out, buf_err = io.StringIO(), io.StringIO()
    with (
        patch("autoreels.cloud.autocut.propose", spy_propose),
        patch("autoreels.cloud.autocut.select_global", spy_select_global),
        contextlib.redirect_stdout(buf_out),
        contextlib.redirect_stderr(buf_err),
    ):
        rc = cmd_autocut(
            "synth",
            root=str(tmp),
            llm="none",
            out=str(tmp / "out" / out_name),
            **kwargs,
        )

    return {
        "rc": rc,
        "propose_calls": propose_calls,
        "select_global_calls": select_global_calls,
        "stdout": buf_out.getvalue(),
        "stderr": buf_err.getvalue(),
    }


def _run_cmd_autocut_with_check(tmp: Path, out_name: str) -> dict:
    """Run cmd_autocut with check=True, patching _autocut_check to simulate rejection of clip1."""
    from autoreels.__main__ import cmd_autocut
    propose_calls: list[tuple] = []
    autocut_check_calls: list[dict] = []

    def spy_propose(*args, **kw):
        propose_calls.append((args, kw))
        return _real_propose(*args, **kw)

    def mock_check(head, line, root, cache_dir):
        # Simulate: the first candidate (u1+u2 merged clip) fails validation
        autocut_check_calls.append({"line": line})
        if "1.1" in line and "2.1" in line:
            return "mock-rejection: clip with u1+u2 fails start-strict check", "mock log"
        return None, "ok"

    buf_out, buf_err = io.StringIO(), io.StringIO()
    with (
        patch("autoreels.cloud.autocut.propose", spy_propose),
        patch("autoreels.__main__._autocut_check", mock_check),
        contextlib.redirect_stdout(buf_out),
        contextlib.redirect_stderr(buf_err),
    ):
        rc = cmd_autocut(
            "synth",
            root=str(tmp),
            llm="none",
            check=True,
            out=str(tmp / "out" / out_name),
        )

    return {
        "rc": rc,
        "propose_calls": propose_calls,
        "autocut_check_calls": autocut_check_calls,
        "stdout": buf_out.getvalue(),
        "stderr": buf_err.getvalue(),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    import tempfile
    script_dir = Path(__file__).resolve().parent
    log_dir = script_dir  # logs published flat per handoff convention

    print("=" * 60)
    print("M223-R2 CLI Evidence Harness")
    print("=" * 60)
    print(f"ROOT: {ROOT}")
    print(f"r0.yaml SHA256: {sha256_file(ROOT / 'config' / 'r0.yaml')}")
    print()

    # §0 Config verification
    print("=== §0 Проверка конфига из config/r0.yaml ===")
    r0_cfg = load_r0_config(ROOT / "config" / "r0.yaml")
    ac = r0_cfg.autocut
    config_ok = verify_config(ac)
    print()
    if not config_ok:
        print("СТОП: конфиг не соответствует — производственные данные изменены.")
        return 1

    # §1 Static: propose() has no clauses parameter (Finding #3)
    print("=== §1 STATIC: сигнатура propose() ===")
    propose_params = set(inspect.signature(_real_propose).parameters.keys())
    has_no_clauses = "clauses" not in propose_params
    check("§1-a: propose() НЕ имеет параметра clauses", has_no_clauses,
          f"params={sorted(propose_params)}")
    print(f"  propose() params: {sorted(propose_params)}")
    print()

    with tempfile.TemporaryDirectory(prefix="m223_cli_r2_") as _td:
        tmp = Path(_td)
        setup_isolated_root(tmp)

        # §2 Baseline CLI run (check=False, teaser=True)
        print("=== §2 Baseline CLI: cmd_autocut() через spy ===")
        ev = _run_cmd_autocut(tmp, "synth_draft.txt", check=False)

        (log_dir / "baseline_stdout.txt").write_text(ev["stdout"], encoding="utf-8")
        (log_dir / "baseline_stderr.txt").write_text(ev["stderr"], encoding="utf-8")

        print(f"  rc={ev['rc']}, propose calls={len(ev['propose_calls'])}")
        print(f"  stdout:\n{ev['stdout']}")
        if ev["stderr"].strip():
            print(f"  stderr:\n{ev['stderr']}")

        check("§2-a: cmd_autocut exit 0", ev["rc"] == 0, f"rc={ev['rc']}")
        check("§2-b: propose() вызван хотя бы один раз", len(ev["propose_calls"]) >= 1)

        # §3 AutoParams from CLI
        print("=== §3 AutoParams из CLI ===")
        cli_prm = None
        cli_units = None
        if ev["propose_calls"]:
            # propose(units, p, ...) — first two args are positional
            args0, cli_kwargs = ev["propose_calls"][0]
            cli_units = args0[0]
            cli_prm = args0[1] if len(args0) >= 2 else cli_kwargs.get("p")

        if cli_prm is None:
            check("§3: cli_prm получен из spy", False, "не удалось извлечь AutoParams")
        else:
            # select lives on AutoCutParams, not ProposalParams — skip it here
            PROPOSAL_CONFIG = {k: v for k, v in REQUIRED_CONFIG.items() if k != "select"}
            for key, expected in PROPOSAL_CONFIG.items():
                val = getattr(cli_prm, key, None)
                if val != expected:
                    print(f"  FAIL {key}: {val!r} (expected {expected!r})")
                    FAILURES.append(f"cli_prm:{key}")
                else:
                    print(f"  OK {key}: {val!r}")
            # select verified in §0 via load_r0_config
            print(f"  generator={cli_prm.generator!r}, passage_gap_sec={cli_prm.passage_gap_sec}")
            print(f"  hook_teaser={cli_prm.hook_teaser!r}, hook_teaser_pos={cli_prm.hook_teaser_pos}")
        print()

        # §4 Finding #1: used_seeds + global selector + validation path
        print("=== §4 Finding #1: used_seeds, глобальный selector, rejection path ===")

        # 4a. Pool size from baseline (len(pool) > 1 needed for select_global)
        props_full = _real_propose(cli_units, cli_prm) if cli_prm and cli_units else []
        pool_size = len(props_full)
        print(f"  propose({len(cli_units)} units) → {pool_size} клип(ов)")
        for i, pr in enumerate(props_full):
            print(f"    clip{i+1}: units={set(pr.units)}, score={pr.score:.2f}, secs={pr.seconds:.1f}s")
        check("§4-a: pool имеет 2+ кандидата (нужно для select_global)", pool_size >= 2,
              f"pool_size={pool_size}")

        # 4b. Global selector was called (select=global and len(pool)>1)
        select_calls = ev["select_global_calls"]
        check("§4-b: select_global() вызван через CLI (select=global, len(pool)>1)",
              len(select_calls) >= 1,
              f"calls={len(select_calls)}")
        if select_calls:
            sc = select_calls[0]
            print(f"  select_global: weights={sc['weights']}, k={sc['k']}, result={sc['result']}")

        # 4c. used_seeds: u1 and u2 are merged into one passage clip by propose()
        passage_clip = next((p for p in props_full if {1, 2}.issubset(set(p.units))), None)
        u2_in_passage = passage_clip is not None
        all_units = [set(p.units) for p in props_full]
        check("§4-c: u1+u2 объединены propose() в один клип через passage (оба в used_seeds)",
              u2_in_passage, f"clip compositions={all_units}")

        # u2-alone is viable without u1
        props_u2_only = _real_propose([u for u in cli_units if u["id"] == 2], cli_prm)
        check("§4-d: u2 отдельно строит жизнеспособный клип", len(props_u2_only) >= 1,
              f"clips={len(props_u2_only)}")
        u2_alone_viable = len(props_u2_only) >= 1

        # 4d. Validation path: check=True + mock _autocut_check simulates rejection of clip1
        print("\n  --- Validation path (check=True, mock _autocut_check) ---")
        ev_check = _run_cmd_autocut_with_check(tmp, "synth_draft_check.txt")
        print(f"  rc={ev_check['rc']}, _autocut_check calls={len(ev_check['autocut_check_calls'])}")
        for call in ev_check["autocut_check_calls"]:
            print(f"    checked: {call['line'][:80]!r}")

        check("§4-e: _autocut_check вызван через реальный CLI-путь (check=True)",
              len(ev_check["autocut_check_calls"]) >= 1)
        # Clip1 (u1+u2) rejected; u2-alone never proposed → program falls back to clip2 (u3)
        clip1_rejected = any(
            "1.1" in c["line"] and "2.1" in c["line"]
            for c in ev_check["autocut_check_calls"]
        )
        check("§4-f: clip1 [u1,u2] подан в _autocut_check (проверен реальным путём)", clip1_rejected)
        # u2-alone never tried: it was not in propose() output pool at all
        all_lines_checked = {c["line"] for c in ev_check["autocut_check_calls"]}
        u2_alone_tried = any("2.1" in ln and "1.1" not in ln for ln in all_lines_checked)
        check("§4-g (P1 PROOF): u2-alone НЕ подан в _autocut_check — не было в пуле (used_seeds)",
              not u2_alone_tried,
              f"u2-alone checked={u2_alone_tried}, u2_alone_viable={u2_alone_viable}")
        print(f"  Вывод: u2 попал в used_seeds через clip1; u2-alone жизнеспособен={u2_alone_viable} "
              f"но никогда не предлагался")
        print()

        # §5 Finding #2: answer_start bypass — teaser vs no-teaser
        print("=== §5 Finding #2: answer_start, первые слышимые слова (teaser vs no-teaser) ===")

        # Teaser run already done in baseline (hook_teaser=True from config)
        draft_path = tmp / "out" / "synth_draft.txt"
        draft_text = draft_path.read_text(encoding="utf-8") if draft_path.exists() else ""

        # Parse hook from draft line
        # Draft line format: "M1 <sec>@<score> | <refs> | h:<ref>! | ..."
        hook_ref = None
        body_first_ref = None
        for line in draft_text.splitlines():
            if "| h:" in line:
                import re as _re
                m = _re.search(r"\| h:(\S+?)\s", line)
                if m:
                    hook_ref = m.group(1).rstrip("!")
            if body_first_ref is None and "1.1" in line:
                body_first_ref = "1.1"

        print(f"  Teaser run: hook_ref={hook_ref!r}")
        # Hook should be "2.1" = Block B S1 "Принятие тревоги снижает её интенсивность."
        check("§5-a: teaser run → hook h:2.1 (первый звук = Принятие тревоги...)",
              hook_ref is not None and "2.1" in str(hook_ref),
              f"hook_ref={hook_ref!r}")

        # No-teaser run
        ev_nt = _run_cmd_autocut(tmp, "synth_draft_noteaser.txt", check=False,
                                  ac_over=["hook_teaser=false"])
        (log_dir / "noteaser_stdout.txt").write_text(ev_nt["stdout"], encoding="utf-8")

        draft_nt = tmp / "out" / "synth_draft_noteaser.txt"
        draft_nt_text = draft_nt.read_text(encoding="utf-8") if draft_nt.exists() else ""
        hook_ref_nt = None
        for line in draft_nt_text.splitlines():
            if "| h:" in line:
                import re as _re
                m = _re.search(r"\| h:(\S+?)\s", line)
                if m:
                    hook_ref_nt = m.group(1).rstrip("!")

        print(f"  No-teaser run: hook_ref={hook_ref_nt!r}")
        # Without teaser restriction, hooks from Block A (first half) are allowed
        # hook_ref_nt='1.2' means S2 from Block A (~25% of clip) is selected as hook
        check("§5-b: no-teaser run → hook з Block A (першої половини) можливий",
              hook_ref_nt is not None and str(hook_ref_nt).startswith("1."),
              f"hook_ref={hook_ref_nt!r}")

        # First planned audible words
        from autoreels.cloud.autocut import answer_start_reason, back_reference as _br, stands_alone

        ANSWER_TEXT = "Да, тревога часто возникает перед переменами."
        TEASER_TEXT = "Принятие тревоги снижает её интенсивность."

        asr = answer_start_reason(ANSWER_TEXT)
        check("§5-c: answer_start_reason() ОТВЕРГАЕТ тело-открывалку (Да, тревога...)",
              asr is not None, f"reason={asr!r}")
        br = _br(ANSWER_TEXT)
        check("§5-d: back_reference() НЕ ловит тело-открывалку (stands_alone её пропустит)",
              br is None, f"back_reference={br!r}")
        sa = stands_alone(ANSWER_TEXT, "Страх сигнализирует.", cli_prm, judge=None, core="тревога")
        check("§5-e: stands_alone() → None для тела-открывалки (не отвергает)",
              sa is None, f"stands_alone={sa!r}")

        # Verify draft references block 1 sentence 1 (the answer-start sentence is in the clip)
        check("§5-f: CLI черновик включает 1.1 (u1 с ответным началом принят)",
              "1.1" in draft_text,
              "1.1 в черновике" if "1.1" in draft_text else "1.1 не найдено")

        print(f"\n  С teaser:    первый звук = h:2.1 → '{TEASER_TEXT}'")
        print(f"  Без teaser:  первый звук = тело → '{ANSWER_TEXT}'")
        print(f"  CLI prm: answer_start={cli_prm.answer_start if cli_prm else '?'!r}, "
              f"start_strict={cli_prm.start_strict if cli_prm else '?'!r}")
        print(f"  STATIC: stands_alone() не вызывает answer_start_reason() — проверяет только back_reference()")
        print()

        # §6 Finding #3: hook_clauses=True but clauses not passed to propose()
        print("=== §6 Finding #3: hook_clauses=True, align.json, clauses() не доходит до propose() ===")

        # 6a. align.json present → CLI should NOT warn about missing alignment
        align_exists = (tmp / "transcripts" / "synth.align.json").exists()
        check("§6-a: align.json присутствует в изолированном корне", align_exists)

        warn_no_align = "нет карты речи и выравнивания" in ev["stderr"]
        check("§6-b: CLI НЕ выдаёт предупреждение об отсутствии карты речи (align.json загружен)",
              not warn_no_align,
              f"stderr contains warning: {warn_no_align}")
        if warn_no_align:
            print(f"  stderr: {ev['stderr'][:200]!r}")

        # 6b. _hook_cands spy: verify clauses=None in production call
        from autoreels.cloud.autocut import _hook_cands as _real_hc
        hook_cand_calls: list[dict] = []

        def spy_hc(clip, sentences, p, start_pause=None, clauses=None):
            hook_cand_calls.append({"clauses": clauses})
            return _real_hc(clip, sentences, p, start_pause=start_pause, clauses=clauses)

        ev_hc = _run_cmd_autocut.__wrapped__(tmp, "synth_draft_hcspy.txt", check=False) \
            if hasattr(_run_cmd_autocut, "__wrapped__") else None

        # Run directly with _hook_cands spy
        from autoreels.__main__ import cmd_autocut
        buf_hc = io.StringIO()
        buf_hce = io.StringIO()
        hc_calls: list[dict] = []

        def spy_hc2(clip, sentences, p, start_pause=None, clauses=None):
            hc_calls.append({"clauses_is_none": clauses is None})
            return _real_hc(clip, sentences, p, start_pause=start_pause, clauses=clauses)

        with (
            patch("autoreels.cloud.autocut._hook_cands", spy_hc2),
            contextlib.redirect_stdout(buf_hc),
            contextlib.redirect_stderr(buf_hce),
        ):
            cmd_autocut("synth", root=str(tmp), llm="none", check=False,
                        out=str(tmp / "out" / "synth_draft_hcspy.txt"))

        check("§6-c: _hook_cands() вызван через CLI (hook_clauses=True active)",
              len(hc_calls) >= 1, f"calls={len(hc_calls)}")
        all_clauses_none = all(c["clauses_is_none"] for c in hc_calls)
        check("§6-d: все вызовы _hook_cands() получили clauses=None (propose() не передаёт clauses)",
              all_clauses_none,
              f"calls={len(hc_calls)}, all_none={all_clauses_none}")

        # 6c. With real SpeechTimes from align.json, S4 (block 1, sent 4) has eligible clause
        from autoreels.cloud.plan import SpeechTimes, load_alignment, heard_pause as _heard_pause
        from autoreels.cloud.autocut import clause_spans as _clause_spans
        from autoreels.core.models import Word as _Word
        from autoreels.cloud.edit import merge_group_sentences
        from autoreels.cloud.montage import montage_blocks

        # Build Word objects from SYNTHETIC_WORDS
        tx_words = [_Word(**w) for w in SYNTHETIC_WORDS]
        align_data = load_alignment(tmp / "transcripts" / "synth.align.json", SOURCE_SHA)
        check("§6-e: load_alignment успешно загружает synth.align.json", align_data is not None)

        times = SpeechTimes(tx_words, None, align_data)

        # Build sent_by_ref for block 1 sentence 4 (S4)
        # S4 = "Эволюция создала тревогу, как важный сигнал опасности." (words at 58.5-69.5)
        # Find S4 words: t0 in [58.5, 69.5]
        s4_words = [w for w in tx_words if 58.0 <= w.t0 <= 70.0]
        print(f"  S4 words: {[w.word for w in s4_words]}")

        def _pa_s4(k: int) -> "float | None":
            # pause after k-th word (1-based) of S4
            if k < len(s4_words):
                return _heard_pause(times, s4_words[k - 1], s4_words[k])
            return None

        def _du_s4(a: int, z: int) -> float:
            return times.audible(s4_words[z - 1])[1] - times.audible(s4_words[a - 1])[0]

        s4_hook_min_words = int(getattr(ac, "hook_min_words", 4))
        s4_hook_min_sec   = float(getattr(ac, "hook_min_sec",   1.5))
        s4_hook_max_sec   = float(getattr(ac, "hook_max_sec",   6.0))
        s4_hook_cl_pause  = float(getattr(ac, "hook_clause_pause", 0.12))

        s4_clauses = _clause_spans(
            s4_words, _pa_s4,
            min_words=s4_hook_min_words, min_sec=s4_hook_min_sec,
            max_sec=s4_hook_max_sec, min_pause=s4_hook_cl_pause, dur=_du_s4
        )
        print(f"  clause_spans(S4, via align.json): {s4_clauses}")

        # We expect clause (4, 7) = "как важный сигнал опасности." ≈ 3.4s
        s4_eligible = any(a == 4 and z == 7 for a, z in s4_clauses)
        check("§6-f: align.json → clause_spans(S4) находит клозу (4, 7) «как важный сигнал опасности.»",
              s4_eligible, f"clauses={s4_clauses}")

        if s4_eligible:
            a4, z4 = 4, 7
            dur4 = _du_s4(a4, z4)
            span4 = (times.audible(s4_words[a4 - 1])[0], times.audible(s4_words[z4 - 1])[1])
            from autoreels.cloud.autocut import hook_score as _hs
            u1_map = next((u for u in SYNTHETIC_MAP["units"] if u["id"] == 1), None)
            clause_text = " ".join(w.word for w in s4_words[a4-1:z4])
            score4 = _hs(clause_text, dur4, u1_map)
            print(f"  Клоза 1.4@{a4}-{z4}: text='{clause_text}'")
            print(f"    span={span4}, dur={dur4:.2f}s, hook_score={score4:.2f}")
            check("§6-g: клоза (4,7) имеет допустимую длину [1.5, 6.0]s",
                  s4_hook_min_sec <= dur4 <= s4_hook_max_sec, f"dur={dur4:.2f}s")

        # 6d. Clause threshold test: S4 starts BEFORE 50% threshold → clause never found in _hook_cands
        # Clip [u1,u2] total = S1(5.5)+S2(5.0)+S3(5.0)+S4(11.0)+S5(6.0)+S6(6.0)+S7(6.0)+S8(8.5) = 53.0s
        # S4 cumulative start = 5.5+5.0+5.0 = 15.5s. threshold = 26.5s. 15.5/53.0 = 29.2% < 50%.
        CLIP_TOTAL_SECS = 53.0
        S4_START_CUM    = 15.5
        THRESHOLD_CUM   = CLIP_TOTAL_SECS * 0.5  # 26.5s

        print(f"\n  Тест порога тизера для S4:")
        print(f"    S4 начинается в {S4_START_CUM}s / {CLIP_TOTAL_SECS}s = {S4_START_CUM/CLIP_TOTAL_SECS:.1%}")
        print(f"    Порог 50% = {THRESHOLD_CUM}s")
        print(f"    S4 начало < порога: {S4_START_CUM < THRESHOLD_CUM}")
        print(f"    Клоза (4,7) начинается в ~{S4_START_CUM + 3.0:.1f}s = {(S4_START_CUM+3.0)/CLIP_TOTAL_SECS:.1%} < 50%")
        print(f"    _hook_cands: S4 → continue (пропускается); клоза никогда не проверяется")

        s4_before_threshold = S4_START_CUM / CLIP_TOTAL_SECS < 0.5
        check("§6-h: S4 начинается ДО порога тизера (29.2% < 50%) → пропускается вместе с клозой",
              s4_before_threshold, f"{S4_START_CUM/CLIP_TOTAL_SECS:.1%}")

        # Confirm: even with real clauses() from align, _hook_cands returns no S4 clause
        # Build a clauses() callback using the same logic as the CLI
        def demo_clauses(ref: str) -> list:
            """Real clauses() logic for block 1 sentences (via SpeechTimes from align.json)."""
            # Only handle S4 (block 1, sentence 4 = "1.4")
            if ref == "1.4":
                return [(a, z, round(_du_s4(a, z), 2), " ".join(w.word for w in s4_words[a-1:z]))
                        for a, z in s4_clauses]
            return []

        # Build a mock sentences function for the threshold test
        def demo_sentences_threshold(refs: str) -> list:
            # Return S4 and S5 info for the threshold demo
            # S4: starts at 15.5s cumulative, long (11s)
            # S5: starts at 26.5s cumulative, short (6s), eligible
            if refs == "1.1-4":
                return [
                    ("1.1", 5.5, 6, True, "Да, тревога часто возникает перед переменами."),
                    ("1.2", 5.0, 4, True, "Страх сигнализирует об изменениях."),
                    ("1.3", 5.0, 4, True, "Это нормальная реакция организма."),
                    ("1.4", 11.0, 7, True, "Эволюция создала тревогу, как важный сигнал опасности."),
                ]
            if refs == "2.1-4":
                return [
                    ("2.1", 6.0, 5, True, "Принятие тревоги снижает её интенсивность."),
                    ("2.2", 6.0, 6, True, "Многие люди учатся жить с тревогой."),
                    ("2.3", 6.0, 6, True, "Это делает жизнь тяжелее и непредсказуемее."),
                    ("2.4", 8.5, 4, True, "Начните замечать тревогу сегодня."),
                ]
            return []

        from autoreels.cloud.autocut import _hook_cands, AutoParams
        from dataclasses import replace

        demo_prm_teaser = replace(cli_prm,
                                  hook_teaser=True, hook_teaser_pos=0.5,
                                  hook_clauses=True,
                                  hook_min_sec=1.5, hook_max_sec=6.0,
                                  hook_min_words=4,
                                  hook_clause_pause=0.12) if cli_prm else None

        if demo_prm_teaser:
            demo_clip = [u for u in SYNTHETIC_MAP["units"] if u["id"] in (1, 2)]

            # With teaser + clauses=None (production path): S4 skipped, its clause not found
            cands_no_clauses = _hook_cands(demo_clip, demo_sentences_threshold,
                                           demo_prm_teaser, clauses=None)
            s4_clause_found_no = any("1.4" in r for r, _, _ in cands_no_clauses)
            check("§6-i: _hook_cands(clauses=None) НЕ находит клозу S4 (пропускается до проверки)",
                  not s4_clause_found_no,
                  f"cands={[(r, t[:30]) for r, _, t in cands_no_clauses[:3]]}")

            # With real clauses callback: S4 STILL skipped (sentence threshold, not clause threshold)
            cands_with_clauses = _hook_cands(demo_clip, demo_sentences_threshold,
                                             demo_prm_teaser, clauses=demo_clauses)
            s4_clause_found_with = any("1.4" in r for r, _, _ in cands_with_clauses)
            check("§6-j: _hook_cands(clauses=demo_clauses) ВСЁ РАВНО пропускает клозу S4 "
                  "(предложение начинается до порога тизера — continue до проверки клоз)",
                  not s4_clause_found_with,
                  f"cands_with={[(r, t[:30]) for r, _, t in cands_with_clauses[:3]]}")
            print(f"  Вывод: hook_clauses=True не помогает для предложений до 50% порога")
            print(f"         Клоза 1.4@4-7 (après 50% порога не начинается — начало 32%) тоже пропущена")
            print(f"         S5 (50.0% ≥ порога) найдена: {any('2.1' in r for r,_,_ in cands_with_clauses)}")
        print()

        # §7 Negative subprocess test: harness exits nonzero with wrong config
        print("=== §7 Negative test: subprocess с select=greedy → exit != 0 ===")
        bad_yaml = (tmp / "config" / "r0.yaml").read_bytes()
        bad_text = bad_yaml.decode("utf-8").replace("select: global", "select: greedy")
        bad_path = tmp / "config" / "r0_bad.yaml"
        bad_path.write_bytes(bad_text.encode("utf-8"))

        neg_result = subprocess.run(
            [sys.executable, str(Path(__file__)), "--check-config", str(bad_path)],
            capture_output=True,
        )
        (log_dir / "negative_stdout.txt").write_text(
            neg_result.stdout.decode("utf-8", errors="replace")
            + neg_result.stderr.decode("utf-8", errors="replace"),
            encoding="utf-8",
        )
        print(f"  subprocess exit code: {neg_result.returncode}")
        print(f"  subprocess stdout: {neg_result.stdout.decode('utf-8', errors='replace')[:200]!r}")
        check("§7-a: subprocess с select=greedy завершается exit != 0",
              neg_result.returncode != 0, f"rc={neg_result.returncode}")

        # §8 Logs and SHA256
        print()
        print("=== §8 Лог-файлы ===")
        for fname in ("baseline_stdout.txt", "baseline_stderr.txt",
                      "noteaser_stdout.txt", "negative_stdout.txt"):
            p = log_dir / fname
            if p.exists():
                h = sha256_file(p)
                print(f"  {fname}: {h}")
            else:
                print(f"  {fname}: MISSING")
        print(f"  r0.yaml SHA256: {sha256_file(ROOT / 'config' / 'r0.yaml')}")

    # §9 Summary
    print()
    print("=" * 60)
    n_checks = sum(1 for ln in FAILURES) + (sum(1 for _ in FAILURES) == 0 and True)
    print("=== ИТОГ ===")
    if not FAILURES:
        print("PASS: все проверки прошли, три находки CONFIRMED/NOT_REPRODUCED по CLI.")
        print()
        print("Запись для финального отчёта:")
        print(f"  CONFIG_SHA256: {sha256_file(ROOT / 'config' / 'r0.yaml')}")
        return 0
    else:
        print(f"FAIL: не прошли {len(FAILURES)} проверок:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
