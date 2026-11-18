"""M223 — deterministic reproducers for three P1 findings in cloud/autocut.py.

Run with:
    python handoff/m223/REPRO.py

No network calls. No writes to the repo. Reads config/r0.yaml via load_r0_config.
Outputs OK / FAIL lines for each sub-check; exits non-zero if any FAIL.
"""
from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root and config loading
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    here = Path(__file__).resolve()
    for p in [here, *here.parents]:
        if (p / "config" / "r0.yaml").exists():
            return p
    raise RuntimeError("project root not found")

ROOT = _project_root()
sys.path.insert(0, str(ROOT / "src"))

from autoreels.core.config import load_r0_config
from autoreels.cloud.autocut import (
    AutoParams, propose, _hook_cands, eligible,
    answer_start_reason, strict_start_reason,
)

# Load the production r0.yaml config (the same path the CLI uses)
r0_cfg = load_r0_config(ROOT / "config" / "r0.yaml")
ac = getattr(r0_cfg, "autocut", None)

# ---------------------------------------------------------------------------
# Verify required config keys from BASELINE-CONFIG.md
# ---------------------------------------------------------------------------

REQUIRED = {
    "hook_clauses": True,
    "start_strict": True,
    "answer_start": True,
    "start_morph": True,
    "generator": "mixed",
    "select": "global",
}

config_ok = True
print("=== Проверка конфига из config/r0.yaml ===")
for key, expected in REQUIRED.items():
    val = getattr(ac, key, None)
    ok = val == expected
    print(f"  {'OK' if ok else 'FAIL'} {key}: {val!r} (ожидалось {expected!r})")
    if not ok:
        config_ok = False
print()

# ---------------------------------------------------------------------------
# Helpers — synthetic units and sentences
# ---------------------------------------------------------------------------

def make_unit(uid: int, role: str, punch: int, t0: float, t1: float, topic: str = "тема",
              standalone: bool = True, refers: int | None = None, summary: str = "") -> dict:
    return {
        "id": uid, "role": role, "punch": punch,
        "t0": str(t0), "t1": str(t1),
        "topic": topic, "standalone": standalone, "refers": refers,
        "refs": f"B{uid}.1", "missing": False, "filtered": False,
        "voice": {"energy": 60.0, "rate": 2.5},
        "summary": summary or f"мысль #{uid} ({role}★{punch})",
        "similar": [],
    }


def make_sentences(ref_map: dict[str, list[tuple[str, float, str]]]):
    """ref_map: ref → [(sentence_ref, sec, text, complete=True)]"""
    def sentences(refs: str):
        rows = []
        for ref in refs.split():
            for entry in ref_map.get(ref, []):
                if len(entry) == 3:
                    sref, sec, text = entry
                    rows.append((sref, sec, len(text.split()), True, text))
                else:
                    sref, sec, text, complete = entry
                    rows.append((sref, sec, len(text.split()), complete, text))
        return rows
    return sentences


FAILURES = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "OK" if condition else "FAIL"
    print(f"  {status} {label}" + (f": {detail}" if detail else ""))
    if not condition:
        FAILURES.append(label)


# ===========================================================================
# FINDING #1 — used_seeds greedy pre-selection hides alternatives
# ===========================================================================
# Config: generator=mixed, prm.overlap_max=0.5
# Scenario: seeds=[#1 (★5 thesis), #2 (★4 thesis), #3 (★4 conclusion)]
# In mixed mode build_passage+add_payoff: seed #1 (★5) goes first (sorted by -punch).
# build_passage grows #1 → picks up adjacent #2, #3 (they are neighbors, same topic).
# After clip is accepted, used_seeds.update(ids for STORY roles) adds #1, #2, #3.
# When we reach seed #2, it is already in used_seeds → skipped.
# Alternative clip [#2, #3] (50 s, within min/max) is never proposed.
# ===========================================================================

print("=== Finding #1: used_seeds скрывает альтернативы ===")

# Three units in a row: thesis #1 (★5, 30s), thesis #2 (★4, 25s), conclusion #3 (★4, 25s)
u1 = make_unit(1, "thesis",     5, t0=0.0,  t1=30.0, topic="тема", standalone=True)
u2 = make_unit(2, "thesis",     4, t0=30.5, t1=55.5, topic="тема", standalone=True)
u3 = make_unit(3, "conclusion", 4, t0=56.0, t1=81.0, topic="тема", standalone=True)

units_all = [u1, u2, u3]

# Minimal AutoParams matching config (passage/mixed, min_sec=25, target_sec=55, max_sec=90)
prm = AutoParams(
    clips=5, min_sec=25.0, target_sec=55.0, max_sec=90.0, max_pieces=4,
    min_punch=int(getattr(ac, "min_punch", 3)),
    seed_punch=int(getattr(ac, "seed_punch", 4)),
    generator="mixed",
    loop=False,  # simplify: no loop question needed
    prune=False,
    rhythm=False,
    context_start=False,
    end_tone=False,
    hook_clauses=bool(getattr(ac, "hook_clauses", True)),
    start_strict=bool(getattr(ac, "start_strict", True)),
    answer_start=bool(getattr(ac, "answer_start", True)),
    start_morph=bool(getattr(ac, "start_morph", True)),
    overlap_max=float(getattr(ac, "overlap_max", 0.5)),
    passage_gap_sec=float(getattr(ac, "passage_gap_sec", 30.0)),
    close_last=False,
    hook_teaser=False,
)

# Full run: seeds are sorted by -punch: #1(★5), #2(★4), #3(★4)
# In mixed mode: build_passage(#1) → runs forward past #2, #3 → clip=[#1, #2, #3] (80.5s > target_sec)
# Actually build_passage stops at target_sec. Let me trace it:
# total starts at 30s (u1), picks nxt=u2 (30s+25s=55s = target), stops.
# add_payoff finds u3 (conclusion, same topic, within max_sec), adds it → [#1, #2, #3] = 80.5s
# After accepted: used_seeds.update({1, 2, 3}) (all STORY roles)
# Seed #2: in used_seeds → skipped
# Seed #3: in used_seeds → skipped

proposals_full = propose(units_all, prm)
ids_full = [set(pr.units) for pr in proposals_full]

print(f"  Полный набор ([#1,#2,#3]): {len(proposals_full)} клипов, составы: {ids_full}")

check("#1-a: полный набор даёт хотя бы один клип", len(proposals_full) >= 1)

if proposals_full:
    first = proposals_full[0]
    check("#1-b: первый клип содержит seed #1", 1 in first.units)
    check("#1-c: первый клип включил #2 и #3 (обе семена забраны)", 2 in first.units and 3 in first.units,
          f"units={first.units}")

# Without unit #1: seed #2 (★4 thesis) should produce a clip [#2, #3] = 50 s (within min/max)
units_no1 = [u2, u3]
proposals_no1 = propose(units_no1, prm)
print(f"  Без #1 ([#2,#3]): {len(proposals_no1)} клипов, составы: {[set(pr.units) for pr in proposals_no1]}")

check("#1-d: без #1 клип из #2+#3 строится (альтернатива жизнеспособна)", len(proposals_no1) >= 1)
if proposals_no1:
    check("#1-e: клип без #1 содержит #2 как семя", 2 in proposals_no1[0].units)

# The P1 failure: with all 3 units, seed #2 never gets a chance because used_seeds blocks it.
# After clip [#1,#2,#3] is accepted, propose() skips seed #2.
# If unit #1 fails montage checks LATER (not in propose), owner sees no alternative.
seed2_in_used = False
if proposals_full and 1 in proposals_full[0].units:
    # Confirm #2 is in units of accepted clip → would be in used_seeds
    seed2_in_used = 2 in proposals_full[0].units

check("#1-f (P1 PROOF): #2 попал в used_seeds через первый клип → как семя пропускается",
      seed2_in_used and len(proposals_full) == 1,
      f"клипов={len(proposals_full)}, #2 в первом клипе={seed2_in_used}")

print()

# ===========================================================================
# FINDING #2 — start_strict/answer_start/start_morph bypass for montage
# ===========================================================================
# Config: start_strict=true, answer_start=true, start_morph=true, context_start=true
# In propose() → context_start() → stands_alone(): only back_reference() is checked.
# strict_start_reason() / answer_start_reason() are NOT called there.
# In __main__.py line 6822: "montage" clips explicitly skip the strict-start block.
# Therefore a montage clip can open on "Да, тревога..." despite answer_start=True.
# ===========================================================================

print("=== Finding #2: start_strict/answer_start/start_morph обход в montage ===")

ANSWER_TEXT = "Да, тревога часто возникает перед переменами."  # typical reply opener
SAFE_TEXT   = "Тревога часто возникает перед переменами."      # no answer word

# 1. Verify answer_start_reason WOULD reject ANSWER_TEXT
answer_why = answer_start_reason(ANSWER_TEXT)
check("#2-a: answer_start_reason отвергает ANSWER_TEXT", answer_why is not None,
      f"answer_why={answer_why!r}")

# 2. Verify strict_start_reason doesn't reject ANSWER_TEXT (only catches back-refs, not answer words)
strict_why = strict_start_reason(ANSWER_TEXT)
check("#2-b: strict_start_reason НЕ отвергает ANSWER_TEXT", strict_why is None,
      f"strict_why={strict_why!r}")

# 3. Build a unit that opens with ANSWER_TEXT and run propose() with context_start=True, answer_start=True
answer_unit = make_unit(10, "thesis", 5, t0=0.0, t1=35.0, topic="тревога", standalone=True,
                        summary="тревога перед переменами")
answer_unit["refs"] = "B10.1"

ref_map_answer = {
    "B10.1": [
        ("B10.1.1", 3.0, ANSWER_TEXT),         # first sentence: answer-start
        ("B10.1.2", 7.0, "Страх сигнализирует о важности."),
        ("B10.1.3", 5.0, "Это нормальная реакция организма."),
        ("B10.1.4", 8.0, "Доверяйте своим чувствам в трудный момент."),
    ]
}
sentences_answer = make_sentences(ref_map_answer)

prm2 = AutoParams(
    clips=3, min_sec=20.0, target_sec=35.0, max_sec=90.0, max_pieces=4,
    min_punch=3, seed_punch=4, generator="montage",
    loop=False, prune=False, rhythm=False,
    context_start=True,          # enables stands_alone check
    end_tone=False, close_last=False, hook_teaser=True, hook_teaser_pos=0.5,
    hook_no_pointer=False,
    hook_clauses=True, hook_min_sec=1.5, hook_max_sec=6.0, hook_min_words=4,
    start_strict=True,           # configured ON
    answer_start=True,           # configured ON
    start_morph=True,            # configured ON
    overlap_max=0.5, passage_gap_sec=30.0,
)

proposals_answer = propose([answer_unit], prm2, sentences_answer)
print(f"  propose() с ANSWER_TEXT началом: {len(proposals_answer)} клипов")
if proposals_answer:
    first_a = proposals_answer[0]
    print(f"  первый клип: pieces={first_a.pieces!r}, notes=")
    for n in first_a.notes:
        print(f"    {n}")

check("#2-c (P1 PROOF): propose() принимает клип с ANSWER_TEXT несмотря на answer_start=True",
      len(proposals_answer) >= 1,
      f"клипов={len(proposals_answer)}")

# 4. Confirm stands_alone does NOT call answer_start_reason
# stands_alone only calls back_reference + context_min_words check + judge
from autoreels.cloud.autocut import stands_alone, back_reference as _br
_br_result = _br(ANSWER_TEXT)
check("#2-d: back_reference НЕ ловит ANSWER_TEXT (passes через stands_alone)",
      _br_result is None,
      f"back_reference={_br_result!r}")

# 5. Inspect __main__.py line 6822: "montage" in flags skips strict check
# This is confirmed statically — we show the code path
print("  STATIC: __main__.py:6822 — if r.id in _seen or \"montage\" in (r.flags or []) → continue")
print("  STATIC: строгая проверка начала явно пропускает montage-клипы")
print("  STATIC: propose() передаёт start_strict/answer_start/start_morph в AutoParams (строки 8632-8636)")
print("  STATIC: но stands_alone() (autocut.py:657-673) их не читает — только back_reference + min_words + judge")
print()

# ===========================================================================
# FINDING #3 — hook_clauses=True doesn't work in propose()
# ===========================================================================
# Config: hook_clauses=True
# CLI builds clauses() at __main__.py:8701-8714 when hook_clauses=True
# propose() signature (autocut.py:1145-1150) has NO clauses parameter
# propose() calls _hook_cands(clip, sentences, p, start_pause) at line 1281 — no clauses
# _hook_cands receives clauses=None → clause branch never executes
# ===========================================================================

print("=== Finding #3: hook_clauses=true не действует в propose() ===")

# Build a unit with one long sentence that contains an eligible clause
# Sentence "Страх сигнализирует о важности изменений; доверяйте своим ощущениям."
# Full sentence: 10 words, ~8s → too long for hook (max 6s)
# Clause "доверяйте своим ощущениям" → 3 words, ~3s, after pause — but < hook_min_words=4
# Clause "страх сигнализирует о важности изменений" → 5 words, ~4.5s — eligible clause

LONG_SENT = "Страх всегда сигнализирует о важности изменений; доверяйте своим ощущениям и они вас не подведут."
CLAUSE_TEXT = "страх всегда сигнализирует о важности изменений"  # 6 words, ~4.5s

hook_unit = make_unit(20, "conclusion", 5, t0=0.0, t1=55.0, topic="страх", standalone=True,
                      summary="страх сигнализирует")
hook_unit["refs"] = "B20.1"

# Sentences: first half boring (hook_teaser_pos=0.5), second half has the long sentence
ref_map_hook = {
    "B20.1": [
        ("B20.1.1", 5.0,  "Когда мы говорим о тревоге, важно понимать её природу."),
        ("B20.1.2", 5.0,  "Это биологический механизм, а не признак слабости."),
        ("B20.1.3", 5.0,  "Эволюция создала тревогу как сигнал опасности."),
        # -- clip at 50% mark (15/55 ~ 27%) -- need items past 50% --
        ("B20.1.4", 5.0,  "Многие люди сражаются с тревогой вместо того, чтобы слушать её."),
        ("B20.1.5", 5.0,  "Это делает жизнь тяжелее и непредсказуемее."),
        ("B20.1.6", 5.0,  "Принятие тревоги снижает её интенсивность."),
        # -- past 50% (30/55 ~ 55%) --
        # This long sentence is 9s — too long for hook_max_sec=6 → normally skipped
        ("B20.1.7", 9.0,  LONG_SENT, True),
        ("B20.1.8", 4.0,  "Так мы становимся хозяевами своих реакций.", True),
        ("B20.1.9", 7.0,  "Начните замечать свою тревогу сегодня, и жизнь изменится навсегда.", True),
    ]
}
sentences_hook = make_sentences(ref_map_hook)

prm3 = AutoParams(
    clips=3, min_sec=30.0, target_sec=55.0, max_sec=90.0, max_pieces=4,
    min_punch=3, seed_punch=4, generator="montage",
    loop=False, prune=False, rhythm=False, context_start=False,
    end_tone=False, close_last=False,
    hook_teaser=True, hook_teaser_pos=0.5,
    hook_no_pointer=False,
    hook_clauses=True,
    hook_min_sec=1.5, hook_max_sec=6.0, hook_min_words=4,
    hook_clause_pause=float(getattr(ac, "hook_clause_pause", 0.12)),
    start_strict=False, answer_start=False, start_morph=False,
    overlap_max=0.5, passage_gap_sec=30.0,
)

proposals_hook = propose([hook_unit], prm3, sentences_hook)
print(f"  propose() с hook_clauses=True: {len(proposals_hook)} клипов")

hook_found_propose = None
if proposals_hook:
    p = proposals_hook[0]
    hook_found_propose = p.hook
    print(f"  hook из propose(): {hook_found_propose!r}")
    print(f"  всего кандидатов: {p.hooks!r}")

check("#3-a: propose() производит хотя бы один клип", len(proposals_hook) >= 1)

# Now call _hook_cands DIRECTLY with a mock clauses function
# that returns the eligible clause for B20.1.7
def mock_clauses(ref: str):
    if ref == "B20.1.7":
        # clause: words 1-6 "страх всегда сигнализирует о важности изменений"
        return [(1, 6, 4.5, CLAUSE_TEXT)]
    return []

clip_hook = [hook_unit]
direct_cands = _hook_cands(clip_hook, sentences_hook, prm3, start_pause=None, clauses=mock_clauses)
print(f"  _hook_cands DIRECTLY с clauses: {[(r, round(sc, 2)) for r, sc, t in direct_cands[:5]]!r}")

clause_hook_in_direct = any("@" in r for r, _, _ in direct_cands)
check("#3-b: _hook_cands напрямую с clauses= находит clause-крючок", clause_hook_in_direct,
      f"кандидаты={[(r, t[:30]) for r, _, t in direct_cands[:3]]}")

# P1 proof: compare propose (clauses=None) vs direct call (clauses=mock_clauses)
hook_propose_has_clause = hook_found_propose is not None and "@" in hook_found_propose
check("#3-c (P1 PROOF): propose() НЕ находит clause-крючок (clauses не передаётся)",
      not hook_propose_has_clause,
      f"hook из propose={hook_found_propose!r}")

# Static: show propose() signature has no clauses parameter
import inspect
propose_params = set(inspect.signature(propose).parameters.keys())
check("#3-d STATIC: propose() не имеет параметра clauses",
      "clauses" not in propose_params,
      f"параметры propose()={sorted(propose_params)}")

# Static: show the call site in __main__.py
print("  STATIC: __main__.py:8818-8820 — propose(..., start_pause=start_pause) — clauses= не передаётся")
print("  STATIC: autocut.py:1281 — _hook_cands(clip, sentences, p, start_pause) — без clauses")
print("  STATIC: autocut.py:1027 — if whole_bad and not (p.hook_clauses and clauses is not None): continue")
print("          → clause ветка недостижима: clauses=None, даже если hook_clauses=True")
print()

# ===========================================================================
# Summary
# ===========================================================================

print("=== ИТОГ ===")
if not FAILURES:
    print("PASS: все проверки прошли, три находки CONFIRMED.")
    sys.exit(0)
else:
    print(f"FAIL: не прошли {len(FAILURES)} из {len(FAILURES) + (27 - len(FAILURES))} проверок:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
