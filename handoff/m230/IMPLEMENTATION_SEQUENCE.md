# M230-ARCH-R3 — Implementation sequence (design; no permission granted)

**Revision:** R3. Provenance: R1 `1cdfbfa`, R2 `d471f35`; R3 applies Sol R2 (P1-R2-1..3, P2 ×3) and `COORDINATOR-AQ-DECISIONS-R2.md`.

**Current code permissions: NONE.** Every path below is a *future* request that opens only through its own recorded coordinator gate after independent Sol QA. `M231_OBSERVABILITY_GO=NO` · `M232_CODE_GO=NO` · `M237_A_B_OWNER_MEDIA_GO=NO`.

All packages share `autocut.py::propose` and/or `cmd_autocut`, so they run **strictly serially**; each is based on the previous accepted package SHA, the first on `3c011e9`. If an implementation needs a source path outside its allowlist, it stops and a new explicit gate is required.

---

## Common package template (≤ 4 parts)

1. **Fail-before receipts on the package base.** Run as `cmd > f 2>&1; rc=$?`, followed by a separate line printing `OK` or `FAIL: …`. No `| tee`.
2. **Minimal flagged patch,** limited to the allowlisted symbols. Default OFF.
3. **Parity, to be proven:**
   - golden JSON generated **at `3c011e9`** by a committed script;
   - review SHA256 of synthetic `cmd_autocut(llm="none")` in `tmp_path`, compared OFF vs base;
   - ON positives and negatives;
   - property asserts from ARCHITECTURE_DECISIONS §3.
4. **Russian REPORT:** SHA, diffstat, `compare_failures.py` against `handoff/m222/baseline-failures.txt`, test names. Then Sol QA. Merge only after Sol PASS and a coordinator decision.

Committed fixtures go in `tests/fixtures/m23x/`. No owner data, render, network or paid API. Use `judge=None` / `llm="none"` or a deterministic **fake provider** (request log captured).

---

## M231 — observability only

**Status.** AQ1 is approved in principle by the coordinator. M231 code GO = **NO** until Sol R3 PASS and a separate pinned gate.

### M231.1 Future allowlist

**`autocut.py::propose`:**
- (a) a final keyword `trace: list | None = None`;
- (b) **passive trace statements**, all inside `if trace is not None:` guards. Only these three forms are allowed:
  1. `_tr = {...}` — one per-seed local dict, created at the top of each seed iteration, holding plain data: ints, floats, strings, lists of those, `None`;
  2. `_tr[...] = <expression over already-computed locals>` — an assignment that reads `clip`, `seed`, `ids` and similar locals, **calls no callback** (`sentences`, `end_tone`, `judge`, `taste`), **mutates nothing** (it builds new lists, e.g. `[u["id"] for u in clip]`), and **raises nothing** (only total operations: dict/list literals, `float(u["t0"])` on values the frozen code already used);
  3. exactly one `trace.append(_tr)` at each terminal exit (M231.2), plus one `trace.append(<truncate event>)` before `return out[:p.clips]`.

  No other statement changes, no new branch outside the guards, no try/except.

**`__main__.py::cmd_autocut`:** reads env `ARL_AUTOCUT_TRACE` (path outside the repo). When it is set:
- passes a list to the **main** call at `:8818` only;
- after the run, enriches events from `sent_by_ref` (M231.3);
- appends the CLI `select` and `fate` events;
- writes JSON Lines with `sort_keys`, floats rounded to 3 decimals, no timestamps.

When it is unset: no statement runs and nothing is printed.

**Tests:** `tests/test_m231_trace.py`, `tests/fixtures/m231/*`.

**Excluded:**
- the weak-seed call (`:8825`) and `fill_pool`;
- the signatures of `teaser_misses`, `_hook_cands`, `build_passage`, `fit_rhythm`, `context_start`;
- `config/`, the manifest schema;
- any new stdout/stderr line.

### M231.2 Seed events: count, order, exits

For each element of `seeds` there is **exactly one** `seed` event, appended in seed order at the iteration's single terminal point. The frozen seed loop `:1174–1308` has nine exits:

| Exit | Line | `outcome` |
|---|---|---|
| used/taken skip | `:1175–1176` | `skip_used` if `seed.id ∈ used_seeds`, else `skip_taken`, evaluated in that order |
| build `None` | `:1178–1179` | `build_none` |
| rhythm fail | `:1201–1204` | `rhythm_fail` |
| start fail | `:1228–1231` | `start_fail` |
| open end | `:1241–1244` | `open_end_fail` |
| final rhythm | `:1252–1255` | `final_rhythm_fail` |
| taken after context | `:1257–1258` | `taken_after_context` |
| overlap / payoff | `:1259–1261` | `overlap_or_payoff` |
| pooled | after `out.append` `:1300` | `pooled` |

After the loop: one `truncate` event, so each call produces `|seeds| + 1` events. An exception raised by frozen code propagates unchanged; trace content is then unspecified and is not a test subject.

**Event fields:**
- `schema: 1`, `seed`, `outcome`, `sup` (for skip_*: the index of the earliest pooled-or-truncated candidate containing the seed, else `null`);
- `snap: {S0..S6}` — unit-id lists assigned right after build, loop prepend, payoff, prune, `fit_rhythm`, `context_start`, `fix_open_end`; a stage not reached is `null`; a stage reached without change repeats the list;
- `dep_broken` — `[[u, t, stage]]`, computed only from `snap` with the §2.1 predicate over `by_id`, an observation;
- `tail_question`;
- `secs` per stage (`Σ_dur`, from values the frozen code computes; `null` if not reached);
- `spans_final: [[id, refs, t0, t1]]` for outcome `pooled` and for exits after S5;
- `proxy_q_after`, `proxy_overlong_side` (labelled PROXY).

`truncate` event: `pooled`, `kept`, `dropped`.

### M231.3 Timing enrichment with incomplete observations (P2)

The enrichment runs in the CLI per unit span `[id, refs, t0, t1]` and never inside `propose`.

**Per boundary:**
- `w0` = first word start of the first sentence of `refs` in `sent_by_ref`;
- `w1` = last word end of the last sentence;
- `d0 = t0 − w0`, `d1 = t1 − w1`.

**Status per boundary:** `ok`, `no_refs` (refs empty or unparsable), `no_sentence` (ref not in `sent_by_ref`), `no_words` (sentence with an empty word list). If the status is not `ok`, then `w*` and `d*` are `null`.

**Per unit:** `err = d1 − d0` only if both are present, else `null`.

**Per candidate:**
- `units_total`, `n_d0`, `n_d1`, `n_err` (coverage);
- `secs_delta = Σ err` **only if `n_err = units_total`**, else `null`; `secs_delta_known = Σ err` over the known units, with `n_err`;
- `max_abs_d0` / `max_abs_d1` over the known values, `null` if there are none;
- `speed_secs` (the `@speed` that word-span durations would give) only if every unit has `err` and `voice.rate`, else `null` with `speed_status`.

**Rules:**
- unknown is **never** coerced to 0;
- the enrichment is total (explicit checks, no exceptions);
- a missing timing never alters, drops or delays a proposal or a legacy output.

`context_start:702–703` can return a clip with no sentence rows. Its units then get statuses, not zeros.

### M231.4 Acceptance and parity tests

- **P1.** `trace=None` vs `trace=[]`: equal Proposal lists, on FX-1…FX-9b, FX-7L, FX-2G, FX-1H and the M223/M226/M227 maps.
- **P2.** Env var unset vs set: identical review SHA256, stdout and stderr.
- **P3.** Accounting identities:
  - |`seed`| = |seeds| and events follow the seed order;
  - one `truncate` event, last;
  - `count(pooled) = pooled`;
  - `kept + dropped = pooled`;
  - Σ fates = pool size.
- **P4.** Two runs give byte-identical traces.
- **P5.** Judge and callback spies: identical call counts and arguments with trace on and off (proves "no callback calls").
- **P6.** The repo-write guard passes; the trace lives under `tmp_path`.
- **P7.** Failure set = baseline.
- **P8.** FX-7L: `dep_broken=[[11,10,"S5"]]`. A valid question-first loop: `[]`. Outputs unchanged.
- **P9.** `t0=w0+0.4`, `t1=w1+0.4` gives `d0=d1=0.4`, `err=0`.
- **P10 (R3, new).** FX-T0 sparse timing:
  - a unit whose ref is missing from `sent_by_ref` → `no_sentence`;
  - an empty `sentences` callback → `no_sentence` for all units;
  - a sentence with an empty word list → `no_words`;
  - empty refs → `no_refs`.

  Expected: `secs_delta=null`, coverage counts correct, `max_abs_*` from the known values only, `speed_secs=null`, and the proposals and review bytes identical to trace-off.
- **P11 (R3, new).** Every seed exit of M231.2 is hit by at least one fixture, and its `outcome` matches.

---

## M232-A — FIX_NOW packages (order = increasing blast radius)

| Pkg | TC | Flag (AQ2: one per package; names frozen at its gate) | Future allowlist | Extra stop condition |
|---|---|---|---|---|
| A1 | TC5 | `fix_context_min_sec` | `autocut.py`: `AutoParams`, `context_start` (step (a) condition), `propose` (post-check after `:1209–1234`); `core/config.py::AutocutConfig`; `cmd_autocut` `AutoParams(...)`; optional `r0.yaml` key | FX-5 does not reproduce 25→23 → STOP |
| A2 | TC7, TC8a, FX-7L (+TC8b pin) | `fix_final_integrity` | `autocut.py`: `AutoParams`, `_final_integrity`, `propose` (S0…S6 snapshots, final check after `:1256`); `cmd_autocut::_try_accept` slices `:8966–8978`, `:8980–8991` (reversible adoption, AD §2.2); config wiring | AQ7 tests missing (introduced-then-removed loop target **and** never-established target); origin classification or reversible-adoption test missing → not opened |
| A3 | TC2, FX-2S | `fix_body_start` | `autocut.py`: `AutoParams`, `_strict_body_why`, `_start_why`, `context_start` (all call sites incl. soft, `require_morph` at entry), `Proposal.seed_id` (`:1300`); `cmd_autocut::_try_accept` slices as in A2 (first-sentence check), one `require_morph()` at montage-selection entry; config wiring | FX-2G or FX-2S publishes an invalid start; pymorphy3 absent without `RuntimeError`; `scenario.py` or the scenario pool changed → STOP |
| A4 | TC9a | `fix_passage_side` | `autocut.py`: `AutoParams`, `build_passage`; config wiring | missing ≤ `len(units)+2` iteration counter → CHANGES_REQUIRED |
| A5 | TC3 | `hook_clauses_autocut` — **only after owner Q3 ≠ О1** | `propose` signature (+`clauses=None`), hook block `:1281`; `cmd_autocut` main call `:8818`; config wiring | apply-parse test of `h:B.N@i-j!` fails → STOP |
| A6 | TC9b | `passage_answer` — **only if Q7-b ≠ Б0** | `build_passage` post-loop; config wiring | two consecutive questions extend, or more than one extension → STOP |
| A7 | TC8b recovery | `end_trim_recover` — **only if Q6 ≠ В1** + a legal-neighbour fixture | `propose` after `:1249–1256`; config wiring | the recovery re-calls `fix_open_end` or loops → STOP |
| A8 | TC1 | `seed_alt`, `seed_alt_max` | `autocut.py`: `AutoParams`, `Proposal.alt_of`, `propose` keywords `variant_descs_out` (G1), `variant_descs` (G2) (AD §2.4.1); `cmd_autocut`: G1 at `:8818`, Phase V after `:9107` (V0–V9), `_try_accept` keyword targets with frozen defaults, `_counted` exclusion `:9160`, variant draft section; config wiring | M231 `seed`/`fate` evidence not accepted; FX-1H, FX-1I or FX-1P fails (legacy bytes or the provider-request prefix differ, or an interviewer ref is accepted) → STOP |

Oracles per package: the columns of `ARCHITECTURE_DECISIONS.md` §1. A2 includes the TC8b pin.

## M232-B — conditional (not scheduled)

#4 post-select fallback; #6 measure change, only if M231 `d0`/`d1` with full coverage show `@speed`, verdict or `k:` changes. Own flags, own gates, owner-authorized evidence.

## M232-C — deferred (not scheduled)

- weak-seed `clauses` / `no_start` / `open_end` / `rhythm_out` wiring;
- `teaser_misses` alignment;
- montage-path interviewer reply;
- TC8a/TC7 prevention;
- TC1 replace mode;
- short variants of A8 variants.

---

## ARCH_QUESTION status (after `COORDINATOR-AQ-DECISIONS-R2.md`)

| AQ | Status | Blocks | Remaining condition |
|---|---|---|---|
| AQ1 | **APPROVED IN PRINCIPLE** (trace keyword) | M231 code GO | Sol R3 PASS on M231.1–M231.4, then a separate pinned gate |
| AQ2 | **DECIDED:** one default-OFF flag per package | each M232 gate | exact name and typed wiring frozen at that package's gate |
| AQ3 | conditional (coordinator) | A8 gate | monotonicity only with the full §2.4.2 lifecycle accepted |
| AQ4 | open | M232-B | M231 `d0`/`d1` evidence |
| AQ5 | open | M237 | `record` on free models with owner consent; separate judge stores for ON/OFF |
| AQ6 | docs only | none | coordinator edit of the M229 wording |
| AQ7 | **ACCEPTED** (architecture) | A2 gate | tests: introduced-then-removed loop target, never-established target, question-first, integer `refers` |
| AQ8 | **ACCEPTED**, montage-origin (main + weak-seed) | A2 and A3 gates | origin classification test; reversible adoption test; A3 start re-check included |

## QA / CI per step

- **Sol checks:** fail-before on base; the diff confined to the allowlist; OFF parity (golden, review SHA, draft bytes, and for A8 the provider-request prefix); the negatives FX-7L, FX-2G, FX-2S, FX-1H, FX-1I, FX-1P, FX-T0 and two-question; termination counters; the failure set; no LLM, network or owner data.
- **CI:** the offline smoke gate stays green; the new tests are added to it.
- **Escalation** to a strong agent after two CHANGES_REQUIRED cycles on one package.

## Global stopping conditions

- Fail-before does not reproduce → decision-only report.
- OFF differs by one byte → STOP.
- A path outside the allowlist is needed → STOP, new gate.
- The failure set differs from the baseline → STOP.
- Render, owner media, or paid/live LLM is needed → STOP (M237).
- An owner answer is missing for A5/A6/A7 → the package is not opened.
