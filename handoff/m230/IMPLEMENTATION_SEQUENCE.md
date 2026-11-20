# M230-ARCH-R2 — Implementation sequence (design; no permission granted)

**Revision:** R2 (P1-1…P1-5 applied; R1 = `1cdfbfa`).
**Current code permissions: NONE.** Every path below is a *future* permission request. It opens only through its own recorded coordinator gate after independent Sol QA of the preceding step.
`M231_OBSERVABILITY_GO=NO` · `M232_CODE_GO=NO` · `M237_A_B_OWNER_MEDIA_GO=NO`.

All packages share `autocut.py::propose` and/or `cmd_autocut`, so they are **strictly serial**. Each package is based on the previous accepted package SHA; the first is based on `3c011e9`.

---

## Common package template (≤ 4 parts)

1. **Fail-before receipts on the package base.** Each command is run as `cmd > f 2>&1; rc=$?`, followed by a separate line that prints `OK` or `FAIL: …`. No `| tee`.
2. **Minimal flagged patch,** limited to the listed symbols. The flag defaults to OFF.
3. **Parity (to be proven):**
   - golden JSON generated **at `3c011e9`** by a committed script;
   - synthetic `cmd_autocut(llm="none")` in `tmp_path`, with the review SHA256 compared OFF vs base;
   - ON positives and negatives;
   - property asserts from ARCHITECTURE_DECISIONS §3.
4. **Russian REPORT:** SHA, diffstat, `compare_failures.py` against `handoff/m222/baseline-failures.txt`, test names, the OFF comparison. Then Sol QA; the integrator merges only after Sol PASS and the coordinator decision.

Committed fixtures go in `tests/fixtures/m23x/`. No owner data, render, network or paid API. `judge=None` / `llm="none"`.

---

## M231 — observability only (#4, #6, #11, final integrity; proxies #9a/#9b)

**Prerequisite:** AQ1 (approval of the `trace` keyword) answered by the coordinator **before** the M231 GO.

**Future permitted paths:**
- **`autocut.py::propose`:** a keyword `trace: list | None = None`, placed last, plus `if trace is not None: trace.append({...})` statements only. No other change to control flow or return values.
- **`__main__.py::cmd_autocut`:** reads env `ARL_AUTOCUT_TRACE` (PROVISIONAL name; a path outside the repo). When it is set: passes a list to the **main** `propose` call (`:8818`) only, enriches events with word times from `sent_by_ref`, collects CLI events, and writes JSON Lines (`sort_keys`, floats rounded to 3 decimals, no timestamps). When it is unset: no code path changes and nothing is printed.
- `tests/test_m231_trace.py`, `tests/fixtures/m231/*`.

**Excluded:**
- the weak-seed call (`:8825`) and `fill_pool`;
- the signatures of `teaser_misses`, `_hook_cands`, `build_passage`, `fit_rhythm`, `context_start`;
- `config/`, the manifest schema;
- any new stdout/stderr line.

**Events (schema 1).**

`seed` — terminal, exactly one per seed in `seeds`. Emitted at each `continue`/append exit of the seed loop (`:1174–1309`).
- `seed`
- `outcome` ∈ {`skip_used`, `skip_taken`, `build_none`, `rhythm_fail`, `start_fail`, `open_end_fail`, `final_rhythm_fail`, `taken_after_context`, `overlap_or_payoff`, `pooled`}
- `sup`
- `snap`: unit-id lists at S0…S6, `null` if not reached
- `dep_broken`: list of `[u, t, stage]` computed from `snap` with the `_final_integrity` predicate; **observation only**, nothing is rejected
- `tail_question`: bool
- `secs_*` per stage
- `spans_final`: `[[id, refs, t0, t1], …]` of the final clip
- `proxy_q_after`, `proxy_overlong_side` (labelled PROXY)

`spans_final` — CLI enrichment, per unit:
- `w0` = start of the first word of the first sentence in `refs`;
- `w1` = end of the last word of the last sentence;
- `d0 = t0 − w0`, `d1 = t1 − w1`, `err = d1 − d0`.
Per candidate: `secs_delta = Σ err`. When `d0 = d1 ≠ 0` (both boundaries shifted the same way), `err = 0` and `secs_delta` stays 0 although both boundaries are off. Errors of opposite sign in different units also cancel in `secs_delta`. **Hence the per-boundary `d0`/`d1` are mandatory**, together with `max(|d0|)` and `max(|d1|)`. A further field, `speed_secs`, records which `@speed` the word-time durations would give versus the emitted one. It is observation only (#6 code-level output influence).

`truncate` — `pooled`, `kept`, `dropped` (units of candidates cut by `out[:p.clips]`).

`select` (CLI, `:9038–9050`) — `mode`, `n`, `exact = n ≤ 30`, `picked`, `greedy`, sums.

`fate` (CLI, one per pool index) — `idx`, `picked`, `fate` ∈ {`accepted`, `close`, `rejected`, `not_reached`, `hookless_left`}, `reason`, and `shortened` (whether `_drop_last_sentence` or `_drop_sentences` was applied, with `played` units before and after → CLI-level `dep_broken_cli`, observation only).

**Acceptance / parity tests:**
- **P1.** `trace=None` vs `trace=[]` give equal Proposal lists on FX-1…FX-9b, FX-7L, FX-2G, FX-1H and the committed M223/M226/M227 maps.
- **P2.** With the env var unset vs set: identical review SHA256, stdout and stderr.
- **P3.** Accounting identity:
  - |`seed` events| = |seeds|;
  - `count(pooled)` = `pooled`;
  - `kept + dropped` = `pooled`;
  - Σ fates = pool size.
- **P4.** Byte-identical traces over two runs.
- **P5.** Equal judge-spy counts; no provider constructed.
- **P6.** The repo-write guard passes; the trace lives under `tmp_path`.
- **P7.** Failure set = baseline.
- **P8.** FX-7L yields `dep_broken=[[11,10,"S5"]]`, a valid question-first loop yields `[]`, and in both cases the output is unchanged.
- **P9.** A synthetic unit with known `t0 = w0 + 0.4` and `t1 = w1 + 0.4` yields `d0 = d1 = 0.4`, `err = 0`. This proves the cancellation is visible.

**Unknown after M231:** real-source frequencies. They need owner-authorized data, which is not part of M231 success. The proxies are not decision-grade.

---

## M232-A — FIX_NOW packages (order = increasing blast radius)

| Pkg | TC | Flag (PROVISIONAL, AQ2) | Future permitted symbols | Extra stop condition |
|---|---|---|---|---|
| A1 | TC5 | `fix_context_min_sec` | `autocut.py`: `AutoParams`, `context_start` (step (a) condition), `propose` (post-check after `:1209–1234`); `core/config.py::AutocutConfig` (+1); `__main__.py::cmd_autocut` `AutoParams(...)` (+1); optional `r0.yaml` key `false` | FX-5 does not reproduce 25→23 on base → STOP |
| A2 | TC7, TC8a, FX-7L (+ TC8b pin) | `fix_final_integrity` | `autocut.py`: `AutoParams`, new `_final_integrity`, `propose` (S0…S6 snapshots, final check after `:1256`); `__main__.py::cmd_autocut::_try_accept` (CLI re-check after `:8969`/`:8984`, montage pool only); config wiring | AQ7/AQ8 unanswered → not opened; a question-first negative rejected → STOP |
| A3 | TC2 | `fix_body_start` | `autocut.py`: `AutoParams`, new `_strict_body_why`, `_start_why`; `context_start` (every predicate call site incl. soft capture/return, `require_morph` at entry); config wiring | FX-2G publishes a start, or the pymorphy3-absent case returns without raising → STOP; `scenario.py` changed → STOP |
| A4 | TC9a | `fix_passage_side` | `autocut.py`: `AutoParams`, `build_passage`; config wiring | missing iteration-counter test (≤ `len(units)+2`) → CHANGES_REQUIRED |
| A5 | TC3 | `hook_clauses_autocut` — **only after owner Q3 ≠ О1** | `autocut.py`: `AutoParams`, `propose` signature (+`clauses=None`) and hook block `:1281`; `cmd_autocut` main call `:8818`; config wiring | the apply-parse test of `h:B.N@i-j!` fails → STOP |
| A6 | TC9b | `passage_answer` — **only if Q7-b ≠ Б0** | `autocut.py`: `AutoParams`, `build_passage` post-loop; config wiring | two consecutive questions extend, or more than one extension occurs → STOP |
| A7 | TC8b recovery | `end_trim_recover` — **only if Q6 ≠ В1** and after a synthetic fixture with a legal neighbour exists | `autocut.py`: `AutoParams`, `propose` after `:1249–1256`; config wiring | the recovery re-calls `fix_open_end` or loops → STOP |
| A8 | TC1 | `seed_alt`, `seed_alt_max` | `autocut.py`: `AutoParams`, `Proposal` (+`alt_of`), `propose` (suppressor record, pass 2, keyword `variants_out=None`); `cmd_autocut`: pass `variants_out` at `:8818`, Phase V after `:9075`; config wiring | M231 `seed`/`fate` evidence not accepted → not opened; FX-1H legacy decision differs with the flag on → STOP |

Oracles per package are the columns of `ARCHITECTURE_DECISIONS.md` §1. A2 includes TC8b as a pure pin.

## M232-B — conditional (not scheduled)

#4 post-select fallback; #6 measure change (it must show `@speed`, verdict or `k:` changes from M231 `d0`/`d1`). Own flags, own gates, owner-authorized evidence.

## M232-C — deferred (not scheduled)

- weak-seed `clauses` / `no_start` / `open_end` / `rhythm_out` wiring;
- `teaser_misses` alignment;
- montage-path interviewer reply;
- TC8a/TC7 prevention variants;
- TC1 replace/global variant mode.

---

## ARCH_QUESTION classification (R2)

| AQ | Question | Blocks | Proposed disposition |
|---|---|---|---|
| AQ1 | `propose(trace=None)` keyword in M231 | **M231 GO** | approve: additive, OFF = unchanged; parity P1/P2 prove it |
| AQ2 | final flag names / one flag per package | each **M232** code gate | one flag per package (as above) |
| AQ3 | A8 monotonicity at pool > 30 | resolved by the two-phase design (Phase L unchanged at any size) | closed in R2; replace mode stays DEFER |
| AQ4 | `_dur` vs word-time measure | **M232-B** only | keep `_dur` in A1–A8; revisit with M231 `d0`/`d1` |
| AQ5 | replay misses for A5/A8 A/B | **M237** | `record` on free models with owner consent |
| AQ6 | TC8b ledger wording "silent drop" | none (docs) | coordinator edit of the M229 contract text |
| AQ7 (new) | established-edge reference (loop-drop asymmetry, §2.1) | **A2 code gate** | accept fail-closed |
| AQ8 (new) | CLI re-check limited to the montage pool (scenario byte-identical) | **A2 code gate** | accept; the scenario path is a separate scope |

## QA / CI per step

- **Sol checks:**
  - fail-before on base;
  - the diff confined to the permitted symbols;
  - OFF parity: golden, review SHA, and for A2/A8 the draft bytes;
  - negatives: FX-7L, FX-2G, FX-1H, two-question;
  - termination counters;
  - the failure-set comparison;
  - no LLM, network or owner data.
- **CI:** the offline smoke gate (`de127df`) stays green; the new tests are added to it.
- **Escalation:** to a strong agent after two CHANGES_REQUIRED cycles on one package.

## Global stopping conditions

- Fail-before does not reproduce → decision-only report.
- OFF differs by one byte → STOP.
- A change is needed outside the listed symbols → STOP for the coordinator.
- The failure set differs from the baseline → STOP.
- Render, owner media, or paid/live LLM is needed → STOP (M237).
- An owner answer is missing for A5/A6/A7 → the package is not opened.
