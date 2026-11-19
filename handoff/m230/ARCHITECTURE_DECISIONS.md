# M230-ARCH-R1 — Architecture decisions (deterministic, bounded, flag-gated)

**Role:** independent architect (Claude Opus), architecture only.
**Frozen production SHA:** `3c011e94263e16e5780936b4769d3490cd03b682` (`src/` and `config/` are identical to `f92b4d2`, so the M223–M227 line numbers hold).
**Input M229 SHA:** `74588a219b0d055059f60185f51fd4bcf6efa6b1`. **Handoff base:** `ff155de08305189d918c80d54672ace79e444539`.
**Status:** PROPOSAL. Nothing was executed. `PRODUCTION_DIFF=NONE`, `M231_OBSERVABILITY_GO=NO`, `M232_CODE_GO=NO`.
**Proof labels:** `ANALYTIC` means derived by reading the frozen source. It is not a run. Accepted evidence levels are those of M228 `FINDINGS.md`. None is render-level.

---

## 0. Design choice: hybrid, not a rewrite

The M230 base task compared (A) generate → finalize → validate → global select against (B) incremental repair. **Selected: B, with A's invariant discipline.** Each check is placed directly after the one transform that can break it, and it writes to the reason channel that transform already uses (`no_start`, `rhythm_out`, `open_end`, which are printed in the draft at `__main__.py:9123–9170`). The order of existing stages does not change.

Why not A: a full reorder changes every clip at once. OFF parity then can no longer be proven per flag, and #4 (selection before checks) is INSTRUMENT_FIRST, not FIX_NOW.

**Shortening and reordering inventory of `propose()` (ANALYTIC).** This is the basis for the claim that each new check closes its invariant on all paths.

| Operation | min_sec checked? | Can change last unit? | Can remove a unit others lean on? |
|---|---|---|---|
| `build_passage` / `build_clip` | yes (`:412`, `:244`) | no question end (`:408`/`:412`, `:246`) | — |
| loop question prepend `:1188` | lengthens | no (prepends) | no |
| `add_payoff` `:1193` | lengthens | appends a PAYOFF role only | no |
| `fit_rhythm` grow `:312–325` | lengthens | **yes — can append a question (TC8a)** | no |
| `fit_rhythm` remove `:328–334` | yes (`:333`) | last is in `keep` | **yes (TC7)** |
| `context_start` (a) drop `:713–720` | **no (TC5)** | no | no |
| `context_start` (b) context | lengthens | no | no |
| `context_start` (b2) later | yes (`:749`) | no | no |
| `context_start` (c) drop thought `:762–766` | yes | no | guarded by `needed` |
| `fix_open_end` `:625–654` | yes (`:641`) | trims sentences; role unchanged | no |
| `_prune` (montage only) | yes | no | guarded by `needed` |

So under the existing `_dur` measure there are exactly three gaps: (a) min_sec (TC5), the fit_rhythm append (TC8a) and the fit_rhythm removal (TC7). Each gets one check.

**Contract facts used below (ANALYTIC):**

- `Proposal.line()` (`autocut.py:143–157`) carries refs, hook, close, keys and title, **never `t0`/`t1`**. Playback is derived downstream from refs by `_autocut_check` → `_blocks_do_apply`. So the unit `t0`/`t1` inside `propose` drive only duration bookkeeping (min/max/target, rhythm spans, `Proposal.seconds`), not audio. This narrows #6 (see Q8).
- With production `context_judge: false`, `propose` makes **no** LLM call (`judge=None`). LLM calls happen only in CLI polish (`_polish` → `judge_hooks`, `rank_hooks`, `headline`, `pick_keywords`; `check_seams` on `pool[:clips*2]`), for candidates the selection loop reaches.
- Pool size in production is `clips × check_pool = max(5, minutes/2) × 3`. For a talk of 20 minutes or more this exceeds `select_global(exact_max=30)`, so "global" there is already greedy by weight (`autocut.py:1378–1383`).

---

## 1. Decision table

Flag names are **PROVISIONAL**. The coordinator fixes final names at the code gate. Each must become an `AutocutConfig` field (`core/config.py`, `extra="forbid"`) and an `AutoParams` field, mapped in `cmd_autocut` at `__main__.py:8609`. Every default is `False`/`off`, and **flag OFF executes the frozen code path unchanged**.

| TC | Root mechanism (frozen line) | Selected strategy | Invariants preserved | Future touched symbols | Fail-before / pass-after / oracle | Deps · proof level |
|---|---|---|---|---|---|---|
| **TC5** #5 | `context_start` step (a) drops the first sentence without a min_sec test (`autocut.py:713–720`); (b2) and (c) do test | **Guard (a)**: take the drop only if `Σ_dur(clip) − rows[0].sec ≥ min_sec`, otherwise fall through to (b)/(b2)/(c)/soft/reject, as the other steps do. **Post-check** in `propose` right after `context_start` returns: `Σ_dur < min_sec` → `no_start.append((pieces, "короче min_sec после начала: X < Y с"))`; `continue`. Reason code `dur_below_min_sec`. | timing source unchanged (`_dur`); refs untouched; manual path untouched | `AutoParams.fix_context_min_sec`; `context_start` (one condition); `propose` (one check) | FB: FX-5 → clip 25→23 s returned. PA: (a) is not taken; the clip is either repaired by (b) to ≥ 25 or lands in `no_start` with the reason. Oracle: every returned Proposal has `Σ_dur ≥ min_sec`. Neg: a drop that leaves ≥ min_sec still happens. OFF: equal to the golden. | none · accepted M224 CLI_HELPER_BOUNDARY (25→23, **not** 25→15) |
| **TC7** #7 | `fit_rhythm` removes a piece whose unit is the `refers` target of a kept unit (`:328–331`) | **Post-check after `fit_rhythm` returns** (in `propose`, after `:1200`). Dependency edge = `leans_on(u, by_id, 1)`, i.e. `standalone is False and refers in by_id`, an **integer id, no coercion**, the same predicate the code already uses. Broken = an edge (u→t) with t in the pre-rhythm clip, u kept and t gone. Then `rhythm_out.append((pieces, "опора #t нужна #u — убрана ритмом"))`; `continue`. Fail-closed. | transitive support: if every direct edge is preserved, the closure is preserved; edges that never existed are not judged | `AutoParams.fix_rhythm_integrity`; `propose` (check after `fit_rhythm`) | FB: FX-7 → `[1,3]` with `#3.refers=2`. PA: no proposal, `rhythm_out` holds the reason. Neg: `[1,2,3]` untouched passes; u standalone with `refers` set → no edge → removal allowed. OFF: golden. | none · HELPER_CONFIRMED (M225 A) |
| **TC8a** #8a | `fit_rhythm` grows the short last piece with the next unit, a question (`:312–325`) | Same post-check: if `clip[-1].role == "question"` → `rhythm_out` reason `"ритм добавил вопрос в конец"`; `continue`. Question **first** is not inspected. Prevention inside `fit_rhythm` is **DEFER** (see §2.4). | question-first loop untouched (`:1183`, `rhythm_why(first_is_question)`); matches the existing "never end on a question" rule (`:246`, `:412`) | same flag and symbol as TC7 | FB: FX-8a → `[1,2,3]` ends on a question. PA: no proposal, reason recorded. Neg: `[q, conclusion]` passes. OFF: golden. | TC7 package · HELPER_CONFIRMED (M225 B) |
| **TC8b** #8b | `fix_open_end` trims to 2.5 s; the final `rhythm_why` rejects (`:1239`, `:1250`) | **Default = current behaviour**, which is already fail-closed **and logged** in `rhythm_out` (printed at `:9138`). M232-A adds only a **pinning regression test**. Recovery is OWNER Q6 (§2.6). The TC8b contract wording "silent drop" is inaccurate: M225 C proved `rhythm_out` non-empty. | unchanged | tests only | FB = PA: `len(proposals)==0`, `rhythm_out` non-empty, `open_end` empty. | none · HELPER_CONFIRMED trim→reject; recovery NOT_VERIFIED |
| **TC2** #2 | `context_start` judges the first body sentence with `stands_alone` (back_reference, min_words, judge) only. `strict_start_reason`/`answer_start_reason`/`start_morph` are never called on the montage path (`:707`), and the apply path skips `montage` lines (`__main__.py:6822`). | Extend the start predicate inside `context_start` when the flag is on **and the sentence does not end with "?"**: `why = glued or alone or strict_body_why(text)`, where `strict_body_why` = `strict_start_reason` → (`answer_start`) `answer_start_reason(text, "")` → (`start_morph`) `clipcheck.start_morph(text.split())`, in the exact order of `scenario.py:203–217`. The same predicate is used for candidate starts inside repairs (a)/(b)/(b2). Add the owner-approved **M197 rule** (`scenario.py:219–225`): an answer-word opener drops its first sentence regardless of length when the next one stands and `Σ_dur ≥ min_sec`. Then the existing ladder runs: earlier context (b), (c), else reject into `no_start`. `host_text=""`: interviewer-reply detection is **DEFER** (it needs a callback the montage path lacks). | question-first loop: questions keep the legacy predicate. `start_morph` already skips questions; `answer_start_reason` would not, hence the "?" guard. Hook/teaser order unchanged: `context_start` still runs before `_hook_cands`, which sees the final clip. Not the hook: the target is the first sentence **after** the hook (the `context_start` M74 contract). | `AutoParams.fix_body_start`; new pure helper `_strict_body_why(text, p)` in `autocut.py`; `context_start` (predicate call sites) | FB: FX-2 clip A keeps body `1.1 «Да, конечно.»` under strict flags. PA: starts at `1.2` (or is repaired earlier, or lands in `no_start`). Neg: FX-2 clip B `[q, conclusion]` passes. `require_morph()` raises if pymorphy3 is absent with `start_morph` on: an existing fail-closed rule, keep it. OFF: golden. Note: the M223 witness's first audio was the **hook** `2.1`/`1.2`, not `Да…`. | needs TC5 guard (shared drop path) · CLI_CONFIRMED bounded (M223) |
| **TC9a** #9a | `build_passage` `break`s when the preferred pick overflows `max_sec` and never tries the other side (`:404`) | **Side closing**: on overflow, close that side (`closed_prv`/`closed_nxt`) and `continue`. A closed side is treated as `None`. Break when both sides are `None`. **Exact, not heuristic:** the neighbour on a side changes only when the run grows on that side, and `total` only grows, so an infeasible side stays infeasible. | output equals legacy whenever no overflow occurs; question-forward and lean-back preferences are applied as before to the remaining side, exactly as legacy does when that side is `None` | `AutoParams.fix_passage_side`; `build_passage` | FB: FX-9a → `None`. PA: `[4,5]` (45 s ≥ 25). Neg: both sides overlong → `None`. **Termination:** each iteration appends one unit (`_dur>0`, ids adjacent and distinct, `total ≤ max_sec`) or closes a side (≤ 2) or breaks ⇒ ≤ `len(units) + 2` iterations, O(n). | none · HELPER_CONFIRMED (M226) |
| **TC3** #3 | `propose` has no `clauses` parameter, so `_hook_cands` always gets `None` (`:1281`; CLI builds `clauses` at `__main__.py:8705` and does not pass it at `:8818`) | **OWNER Q3.** The mechanism is fixed. Add `propose(..., clauses=None)` as the **last keyword** (backward compatible) and forward `clauses=clauses` **only at the main call `:8818`**. The weak-seed call `:8825` is DEFER (same class as its other missing wiring). Mode flag `hook_clauses_autocut: off \| rescue \| full`. `rescue`: `cands = _hook_cands(..., clauses=None)`; if empty → `_hook_cands(..., clauses=clauses)`. `full` = the scenario path's semantics. `_hook_cands` itself is unchanged. | `hook_clauses=false` ⇒ `clauses` is `None` in the CLI ⇒ identical. `rescue` leaves every clip that already has a hook **byte-identical**. Teaser position: a clause starts ≥ its sentence start ≥ `hook_teaser_pos`·total, so ordering is preserved a fortiori; the "sentence before / clause after the threshold" case stays excluded (NOT_REPRODUCED, DEFER). `hook_judge_top=6` unchanged (#10). | `AutoParams.hook_clauses_autocut`; `propose` signature + hook block; `cmd_autocut` main call | FB: FX-3 → 0 candidates. PA (`rescue`/`full`): ≥ 1 `h:1.1@2-3`. Neg: `hook_clauses=false` → 0; mode `off` → golden. STATIC obligation: the montage line `h:B.N@i-j!` must parse in apply (`hook_words`, `__main__.py:5610`); a synthetic CLI test is required. | owner Q3 · CLI boundary + STATIC + HELPER |
| **TC9b** #9b | post-loop pop of a trailing question; the answer after it is never visited (`:408–409`) | **OWNER Q7-b**, default **no extension**. If chosen, it is one bounded step: keep the question and append `answer = by_id[q.id+1]` if usable (same `usable()`), within `passage_gap_sec`, the rhythm jump limit holds, `total ≤ max_sec`, the answer is eligible, and (Б1) `role ∈ PAYOFFS`. At most one extension per build; no loop. | question never last; legacy when the condition fails | `AutoParams.passage_answer` (mode); `build_passage` post-loop | FB: FX-9b → `[u1]`. PA (Б1/Б2): `[u1,u2,u3]`. Neg: no answer / overlong / not payoff (Б1) → `[u1]`. | owner Q7-b; after TC9a (same function) · HELPER_CONFIRMED mechanism; media benefit UNPROVEN |
| **TC1** #1 | a seed inside an earlier candidate is skipped (`:1175`), and `taken` blocks growth into earlier candidates (`:1257`, `:1263`). The only route to a shorter alternative around that seed is closed. | **Bounded complement variants** (§2.1). Pass 1 = legacy, unchanged, with the same truncation `out[:p.clips]`. Pass 2: each seed skipped in pass 1 gets **one** attempt, built and finalized with exclusion set `E = ids(suppressor) − {seed}` instead of global `taken`. At most `seed_alt_max` attempts (default `p.clips`). Variants are appended **after** the legacy list. Conflicts are resolved only at selection. | accepted clips never share a unit in passage mode (union conflict, §2.1); legacy pool ⊆ new pool, same order; greedy-mode decisions on legacy candidates are identical; manual path untouched; no LLM inside `propose` | `AutoParams.seed_alt`, `seed_alt_max`; `propose` (suppressor record + pass 2); `Proposal.alt_of` (defaulted field, not in `line()`); `cmd_autocut` selection block (conflict union, fill trigger, variant-tail ordering) | FB: FX-1 → `u2`-alone absent from the pool. PA: pool holds `{2}` with `alt_of` = the `[1,2]` candidate; the accepted set has no two proposals sharing units (`combinations` assert). OFF: golden + CLI review SHA. | M231 trace (suppression counts) · CLI_CONFIRMED mechanism; late rejection NOT_REPRODUCED |

---

## 2. Specifications that need more than one row

### 2.1 TC1 — complement variants (Q1)

**Why not "independent rebuild with `taken=∅`".** In FX-1, `build_passage(u2, taken=∅)` grows back to `u1` (gap 10.5 s < 30, total 28 < target 55) and returns `[1,2]`, a duplicate. The M223 counterfactual `propose([u2])` worked only because `u1` was absent from the unit list (`CLI_REPRO.py:553`). The viable alternative is "around `u2`, without its suppressor's other units", which is exactly `E`.

- **Suppressor record (pass 1, observation only):** when pass 1 skips seed `s` at `:1175`, record `sup[s]` = the earliest legacy candidate (including later-truncated ones) whose `ids` contain `s`. That candidate is unique and deterministic.
- **Visited key:** `(s, frozenset(E))`, attempted once. Variants never spawn variants, so the recursion depth is 1.
- **Attempt order:** pass-1 seed order (the existing key `(-punch, -energy, t0)`). Pass 2 adds `id` as the final tie-break inside pass 2 only; pass 1 is untouched.
- **Per-attempt pipeline:** identical to pass 1 (loop question with `in_clips=E`, `add_payoff(taken=E)`, `fit_rhythm(taken=E)`, `context_start`, `fix_open_end`, final rhythm, all M232 checks whose flags are on). Pass-1 pool-level rejects (`:1257` taken, `:1259–1261` overlap/payoff vs `out`) are **not** applied to variants; they become selection conflicts.
- **Candidate identity:** `(tuple(ids), pieces)`. A variant equal to any pooled candidate is dropped and counted.
- **Bounds:** attempts ≤ `seed_alt_max` (default `p.clips`), so pooled variants ≤ attempts and pool ≤ 2·`p.clips`. CPU per attempt is O(units). With a context judge configured (off in production), judge calls per attempt are ≤ 6 iterations × (2 + `context_back`) probes, a constant.
- **Selection (CLI, only when `seed_alt` is on):**
  - `conflict(a,b) = _close(a,[b]) is not None OR legacy_conflict(a,b)`, where `legacy_conflict` = (passage and `units(a)∩units(b)` non-empty) or (`|shared| > overlap_max·min(len)`) or (same last unit), i.e. the rules of `:1257–1261`. Applied in `_cf` (`:9042`) **and** `_try_accept` (`:8955`). On legacy–legacy pairs `legacy_conflict` is false by construction, so those decisions are unchanged.
  - **Variant-tail ordering:** every existing pool sort (`:8840`, `:8919`) gets a leading key `is_variant`, which keeps the legacy block's relative order exactly.
  - **Fill trigger and `fill_pool` `have`** (`:8822`, `:1313`) use the legacy pool only, so weak-seed extras are unchanged.
- **Monotonicity (ANALYTIC):**
  - `select: greedy`: legacy candidates are processed first, in the same order, with the same conflicts, so they get the same accept/reject decisions; variants can only fill slots left empty.
  - `select: global` exact (`n ≤ 30`): the legacy accepted set is still feasible, so the total score is ≥ legacy.
  - `n > 30` (greedy by weight): **no guarantee**; measure via the M231 trace before enabling.
- **Scope:** passage/mixed only. `build_clip` (montage) has no exclusion parameter, so montage is **DEFER**.
- **Replay:** variants that reach polish create new judge prompts. `ARL_LLM_CACHE=replay` then misses (`arl auto` rc 1, by design). A/B needs a `record` pass on free models (M237 scope). Unit and regression tests use `judge=None`.

### 2.2 TC2 — strict body start helper

`_strict_body_why(text, p) -> str | None`:

- returns `None` unless the flag is on and `p.start_strict` is set, or when `text.rstrip()` ends with "?";
- otherwise returns, in order, `strict_start_reason(text)`, then `answer_start_reason(text, "")` if `p.answer_start`, then `clipcheck.start_morph(text.split())` if `p.start_morph` (after `require_morph()`, as `scenario.py:197–199` does).

The scenario path is **not** refactored to use this helper; the duplication is tracked as DEFER so that path stays byte-identical.

### 2.3 TC5/TC2 interaction

The M197 drop and step (a) both go through the TC5 guard. A2 (TC2) is therefore sequenced after A1 (TC5).

### 2.4 DEFER items with their settling observation

| Item | Why deferred | Synthetic observation that would settle it |
|---|---|---|
| TC8a prevention (skip a question neighbour when growing at the clip end) | it creates new clips; benefit unproven | M231 trace count of `rhythm_fail` with reason "question end" > 0 on owner-authorized data, plus a fixture where the other side can grow |
| TC7 cascade removal (drop dependents with their target) | changes payoff/coverage | fixture where the dependent is not in `keep` and the remainder passes rhythm |
| TC3 "sentence before / clause after threshold" | M223 NOT_REPRODUCED | a clause hook starting ≥ `hook_teaser_pos` inside a sentence that starts before it, judged by the owner |
| TC2 interviewer-reply (`host_text`) on the montage path | needs a speaker callback | an `_other`-based fixture where the reply follows the interviewer within `answer_gap_sec` |
| Weak-seed `clauses` / `no_start` / `open_end` / `rhythm_out` wiring; `teaser_misses` alignment | signature changes; Q8 excludes them from M231 | M227 helper mismatch replayed at the CLI with alignment loaded |
| #4 post-select fallback, #6 duration measure | INSTRUMENT_FIRST | M231 `select` events showing a picked candidate rejected with a feasible unpicked replacement; `secs_delta ≠ 0` changing a min/max/rhythm verdict |

### 2.5 Q8 — M231 observability (design only; full contract in IMPLEMENTATION_SEQUENCE §M231)

- **#6 narrowed (ANALYTIC):** the `t0`/`t1` offsets affect `Σ_dur` bookkeeping only (see §0). The metric is `secs_delta = Σ_dur(clip) − Σ sentence seconds of pieces`, per candidate, computable inside `propose` from the existing `sentences` callback. A playback effect is not reachable from `propose`.
- **#11:** a per-seed terminal event in `propose`. **#4:** pick versus fate at the CLI.
- **#9a/#9b frequency:** proxy flags computed in `propose` from `by_id` after the build, without touching `build_passage`. They are labelled PROXY.

### 2.6 Q6 / Q7-b / Q3 — owner options

These are in `OWNER_DECISION_BRIEF.md`. Architect defaults are Q3 = off until the owner answers (recommend `rescue`), Q6 = fail-closed, Q7-b = no extension.

---

## 3. Global invariants (each must be a test in every M232 package)

1. **OFF parity:** with the package flag off, `propose()` output equals a golden JSON generated **at `3c011e9`** for every FX fixture and every committed M223/M226/M227 synthetic map. The synthetic `cmd_autocut(llm="none")` review file SHA256 is unchanged. The M226 preflight review `95350aa0…` is a known-deterministic reference.
2. **Question-first loop:** `[q(question), …, payoff]` is never rejected by a new check.
3. **No question last; min_sec; preserved deps:** these hold for every returned Proposal when the relevant flag is on. Property assert over all fixtures.
4. **Dedup:** no two accepted proposals share a unit in passage mode, and every accepted pair has `_close is None`.
5. **No new LLM call inside `propose`; no network in tests;** judge spies report equal call counts with flags off.
6. **Manual path:** no change to the apply stage lists or `selection_source: human` handling (invariant 5 tests stay green).
7. **Failure set** equals `handoff/m222/baseline-failures.txt` via `compare_failures.py`. The 29 known baseline failures include `test_m202_replay_accounting.py` and `test_m177_repeats.py`, so they cannot serve as oracles.
