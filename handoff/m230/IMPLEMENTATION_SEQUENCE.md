# M230-ARCH-R1 — Implementation sequence (design; no permission granted)

**Current code permissions: NONE.** Every path listed below is a *future* permission request. Each one opens only through its own recorded coordinator gate, after independent Sol QA of the preceding step.
`M231_OBSERVABILITY_GO=NO` · `M232_CODE_GO=NO` · `M237_A_B_OWNER_MEDIA_GO=NO`.

All packages share `src/autoreels/cloud/autocut.py::propose`, so they are **strictly serial**. Each package is based on the previous accepted package SHA (the first on `3c011e9`). There is no parallel worktree on shared files.

---

## Common package template (≤ 4 parts each)

1. **Fail-before receipts on the package base.** The new tests fail (or, for parity and negative tests, pass) on the unmodified base. Each command is logged as `cmd > f 2>&1; rc=$?`, followed by a line printing `OK` or `FAIL: …`. No `| tee`.
2. **Minimal flagged patch,** touching only the listed symbols. The flag defaults to OFF.
3. **Parity and positive tests:**
   - golden JSON generated **at `3c011e9`** by a committed script (provenance recorded);
   - synthetic `cmd_autocut(llm="none")` in `tmp_path` with the review file SHA256 compared OFF vs base;
   - ON positive and negative tests;
   - property asserts from ARCHITECTURE_DECISIONS §3.
4. **REPORT (Russian):** commit SHA, diffstat, `compare_failures.py` against `handoff/m222/baseline-failures.txt`, named tests, and the OFF comparison. Then Sol QA. Merge only by the appointed integrator after Sol PASS and the coordinator decision.

Tests live in `tests/` with **committed fixtures** (`tests/fixtures/m23x/`). No owner data, render, network or paid API. `judge=None` / `llm="none"`.

---

## M231 — observability only (#4, #6, #11; proxies for #9a/#9b)

**Future permitted paths (on GO):**

- `src/autoreels/cloud/autocut.py::propose`: add a keyword `trace: list | None = None` (last position) and only `if trace is not None: trace.append({...})` statements. **No** other change to control flow or return values.
- `src/autoreels/__main__.py::cmd_autocut`: read env `ARL_AUTOCUT_TRACE` (PROVISIONAL name, path outside the repo). When it is set, pass a list to the **main** `propose` call only (`:8818`), collect CLI selection events, and write JSON Lines (`sort_keys`, floats rounded to 3 decimals, no timestamps). When it is unset, **no** code path changes and nothing is printed.
- `tests/test_m231_trace.py` plus `tests/fixtures/m231/*`.

**Explicitly excluded:**

- the weak-seed `propose` call (`:8825`), its arguments and `fill_pool`;
- `teaser_misses`, `_hook_cands`, `build_passage` and `fit_rhythm` signatures;
- `config/`, the manifest schema;
- any new stdout/stderr line.

**Events (schema 1):**

| Stage | Where | Fields |
|---|---|---|
| `seed` (terminal, exactly one per seed in `seeds`) | each `continue`/append exit of the seed loop `:1174–1309` | `seed`, `outcome ∈ {skip_used, skip_taken, build_none, rhythm_fail, start_fail, open_end_fail, final_rhythm_fail, taken_after_context, overlap_or_payoff, pooled}`, `sup` (id of the earliest pooled candidate containing the seed, for skip_*), `units`, `secs_build`, `secs_rhythm`, `secs_start`, `secs_end` (each `Σ_dur` after its stage, `null` if not reached), `secs_sent` (Σ sentence seconds of the final pieces, when `sentences` is given), `secs_delta = secs_end − secs_sent` (#6), `proxy_q_after`, `proxy_overlong_side` (PROXY #9b/#9a, computed from `by_id`, labelled proxy) |
| `truncate` | before `return out[:p.clips]` | `pooled`, `kept`, `dropped` (unit lists of candidates cut by the cap — pre-pool loss #11) |
| `select` (CLI) | `:9038–9050` | `mode`, `n`, `exact = n ≤ 30`, `picked`, `greedy`, pick sums |
| `fate` (CLI, one per pool index) | after the accept loops | `idx`, `picked`, `fate ∈ {accepted, close, rejected, not_reached, hookless_left}`, `reason` — #4 is "picked ∧ rejected" with a feasible unpicked replacement |

**Acceptance and parity tests (all required):**

- **P1.** `propose(trace=None)` versus `propose(trace=[])` returns equal Proposal lists (dataclass equality) on FX-1…FX-9b and the committed M223/M226/M227 synthetic maps.
- **P2.** With the env var unset versus set: identical review file SHA256, stdout and stderr (synthetic `cmd_autocut`, `tmp_path`).
- **P3.** Accounting identity: |`seed` events| = |seeds|; `count(pooled)` = `pooled`; `kept + dropped` = `pooled`; Σ fates = pool size.
- **P4.** Determinism: two runs produce byte-identical trace files.
- **P5.** Judge-spy call counts are equal with tracing on and off; no provider is constructed.
- **P6.** The repo-write guard passes; the trace file lives under `tmp_path`.
- **P7.** The failure set equals the baseline.

**Known unknowns (stay unknown after M231):** real-source frequencies (suppression, truncation, `secs_delta`, question pops). Measuring them needs owner-authorized data or logs, which is not part of M231 success. The proxies are approximations and are not decision-grade for #9.

---

## M232-A — FIX_NOW packages (order = increasing blast radius)

| Pkg | TC | Flag (PROVISIONAL) | Future permitted symbols | Extra stop condition |
|---|---|---|---|---|
| A1 | TC5 | `fix_context_min_sec` | `autocut.py`: `AutoParams`, `context_start` (step (a) condition only), `propose` (post-check after `:1209–1234`); `core/config.py::AutocutConfig` (+1 field); `__main__.py::cmd_autocut` `AutoParams(...)` (+1 kwarg); optional `config/r0.yaml` key `false` | FX-5 does not reproduce 25→23 on base → STOP, decision-only report |
| A2 | TC7 + TC8a (+TC8b pin) | `fix_rhythm_integrity` | `autocut.py`: `AutoParams`, `propose` (post-check right after `fit_rhythm` `:1200–1206`); config wiring as A1 | any new check rejects the question-first negative control → STOP |
| A3 | TC2 | `fix_body_start` | `autocut.py`: `AutoParams`, new `_strict_body_why`, `context_start` (predicate call sites, M197 drop); config wiring | the pymorphy3-absent path must raise as now; `scenario.py` must not change |
| A4 | TC9a | `fix_passage_side` | `autocut.py`: `AutoParams`, `build_passage`; config wiring | iteration-bound test (counter ≤ `len(units)+2`) missing → CHANGES_REQUIRED |
| A5 | TC3 | `hook_clauses_autocut` (`off\|rescue\|full`) — **only after owner Q3** | `autocut.py`: `AutoParams`, `propose` signature (+`clauses=None`, last) and hook block `:1281`; `__main__.py::cmd_autocut` main call `:8818` (+`clauses=clauses`); config wiring | Q3 unanswered or `О1` → package not opened; the `h:B.N@i-j!` apply-parse test fails → STOP |
| A6 | TC9b | `passage_answer` (`off\|payoff\|eligible`) — **only if Q7-b ≠ Б0** | `autocut.py`: `AutoParams`, `build_passage` post-loop; config wiring | more than one extension per build is possible → CHANGES_REQUIRED |
| A7 | TC8b recovery | `end_trim_recover` (`off\|front\|earlier`) — **only if Q6 ≠ В1**, and only after a synthetic fixture with a legal neighbour exists | `autocut.py`: `AutoParams`, `propose` after the final rhythm `:1249–1256`; config wiring | the recovery calls `fix_open_end` again or loops → STOP |
| A8 | TC1 | `seed_alt`, `seed_alt_max` | `autocut.py`: `AutoParams`, `Proposal` (+`alt_of`, default `None`), `propose` (suppressor record, pass 2); `__main__.py::cmd_autocut` selection block `:8822–8919`, `:8955`, `:9038–9050` (conflict union, legacy-only fill trigger/`have`, `is_variant` leading sort key); config wiring | M231 not accepted; monotonicity tests (greedy-identical legacy decisions; global exact sum ≥ legacy) fail → STOP |

**Per-package oracles** are the fail-before/pass-after/negative/OFF columns of `ARCHITECTURE_DECISIONS.md` §1. A2 includes TC8b as a pure regression pin with no code.

## M232-B — conditional post-instrument fixes (not scheduled)

#4 post-select fallback and #6 duration measure. Opened only if M231 events on safe fixtures — and, separately, on owner-authorized data — show a violation, and Sol confirms the evidence suffices. Own flags, own gates.

## M232-C — deferred wiring (not scheduled)

Weak-seed `clauses`/`no_start`/`open_end`/`rhythm_out`, `teaser_misses` alignment (Q8), the montage-path interviewer-reply rule, and the TC8a/TC7 prevention variants (ARCHITECTURE_DECISIONS §2.4).

---

## QA / CI per step

- **Sol** checks the reproducible fail-before on the base, the diff limited to the permitted symbols, OFF parity (golden + review SHA), negatives, the termination test (A4/A6/A7), the failure-set comparison, and that no LLM, network or owner data was used.
- **CI:** the existing offline smoke gate from `main@de127df`/`3c011e9` stays green; the new tests are added to it.
- **Escalation to a strong agent** after two CHANGES_REQUIRED cycles on one package, or if A8 monotonicity cannot be shown.

## Global stopping conditions

- A fixture fail-before does not reproduce on its base → decision-only report, no fix.
- OFF output differs from the golden by one byte → STOP.
- A change is needed outside the listed symbols → STOP for a coordinator decision.
- The failure set differs from the baseline → STOP.
- Any need for render, owner media, paid or live LLM → STOP (that is M237 scope).
- The owner decision is missing for A5/A6/A7 → the package is not opened; the conservative default stays.
