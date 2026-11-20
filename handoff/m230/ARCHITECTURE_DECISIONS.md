# M230-ARCH-R2 — Architecture decisions (deterministic, bounded, flag-gated)

**Revision:** R2. This responds to the five P1 findings of Sol QA R1 (`TASK-M230-ARCH-R2.md`). R1 provenance: `1cdfbfaa1fb138641ef1687f6be06457b79c346c`.
**Frozen production SHA:** `3c011e94263e16e5780936b4769d3490cd03b682`. At that SHA, `src/` and `config/` are identical to `f92b4d2`, so the M223–M227 line numbers hold.
**Input M229 SHA:** `74588a219b0d055059f60185f51fd4bcf6efa6b1`.
**Status:** PROPOSAL. Nothing was executed. `PRODUCTION_DIFF=NONE`, `M231_OBSERVABILITY_GO=NO`, `M232_CODE_GO=NO`.
**Proof labels:**
- `ANALYTIC` — derived by reading the frozen source; not a run.
- `REPORTED` — a synthetic case run by Sol QA R1 that the architect has not re-executed.
- Accepted evidence levels — those of M228 `FINDINGS.md`. None is render-level.

**OFF parity is a test obligation, not an established fact.** Every "OFF = frozen path" statement below describes design intent. It becomes evidence only through the parity tests in §3.

---

## 0. Design choice: hybrid with one final validator

The M230 base task offered (A) generate → finalize → validate → global select, or (B) incremental repair.

**Selected: B, plus one FINAL pre-publication validator.**
- Local guards stay only where they let an existing repair run instead of failing. This applies to the TC5 guard in `context_start` (a) and to the TC2 semantic predicate inside `context_start`.
- Invariants that a later stage can break are checked **once, after the last structural mutation of `propose`**.
- For mutations made by the CLI after `propose`, the same invariants are re-checked there (§0.3).
- The order of existing stages does not change. A full reorder (A) would change every clip at once and make per-flag parity unprovable.

### 0.1 Structural mutation inventory of `propose()` (ANALYTIC; R2 — corrected)

R1 claimed "exactly three gaps". **That claim is withdrawn:** it missed the `context_start` (c) drop of a loop question that bypasses `needed` (`autocut.py:762–766`, condition `u["id"] == loop_id`), which can break a dependency **after** any rhythm-local check.

| Stage (observation point) | Line | min_sec checked? | Can change the last unit? | Can remove a unit others lean on? |
|---|---|---|---|---|
| S0 `build_passage` / `build_clip` | `:1177` | yes (`:412`, `:244`) | never ends on a question (`:408`/`:412`, `:246`) | — |
| S1 loop question prepend | `:1188` | lengthens | no | no |
| S2 `add_payoff` | `:1193` | lengthens | appends a PAYOFF role only | no |
| S3 `_prune` (montage only) | `:1196` | yes | no | guarded by `needed` |
| S4 `fit_rhythm` (grow + remove, internal loop ≤ 12) | `:1200` | yes on removal (`:333`) | **yes — can append a question (TC8a)** | **yes (TC7)** |
| S5 `context_start` (a) drop first sentence | `:713–720` | **no (TC5)** | no | no (the unit stays) |
| S5 `context_start` (b) add context | `:721–742` | lengthens | no | no |
| S5 `context_start` (b2) later start | `:743–761` | yes (`:749`) | no | no |
| S5 `context_start` (c) drop opening thought | `:762–766` | yes | no | **yes when `u.id == loop_id` (bypasses `needed`) — P1-1** |
| S6 `fix_open_end` | `:1239` | yes (`:641`) | trims sentences; unit id and role unchanged | no |
| final rhythm verdict | `:1249–1256` | — (reject only) | — | — |

Intermediate states inside `fit_rhythm`'s loop are **not** observation points. Its result is judged against its input (S3 → S4).

### 0.2 Contract facts (ANALYTIC unless marked; R2 — #6 corrected)

- **R1 overclaim retracted.** R1 said unit `t0`/`t1` "drive only duration bookkeeping, not audio". That is false at the code level. `_dur` feeds:
  - `_speed()` (`:1131–1143`), which `Proposal.line()` serializes as `@speed`. Sol REPORTED a synthetic HELPER case where a 0.4 s duration change moved speed 1.05→1.08.
  - `score` via `over = secs − target_sec` (`:1271–1272`).
  - `Proposal.seconds`, which sets the rule-keyword count `round(seconds / keywords_every_sec)` (`__main__.py:9028`; production uses `keywords_source: rule`) and the draft header.
  - min/max/target/rhythm verdicts.
- **What is known:**
  - (a) **Proven code-level output influence** (ANALYTIC + REPORTED HELPER): `@speed`, score order, `k:` count, accept/reject verdicts.
  - (b) **Real-media playback effect: UNKNOWN.** Not reproduced, not rendered. `pieces` (refs) still define which sentences play.
- With production `context_judge: false`, `propose` makes no LLM call (`judge=None`). LLM calls happen only in CLI polish (`_polish`, `check_seams`) for candidates the selection loop reaches.
- Pool = `clips × check_pool`. Above `exact_max=30`, `select_global` is greedy by weight (`:1378–1383`).

### 0.3 CLI mutations after `propose` (ANALYTIC; R2 — new)

`_try_accept` can replace a proposal with a sentence-level shortening:
- `_drop_last_sentence` (M167, `__main__.py:1136`, called at `:8966–8978`);
- `_drop_sentences` (M173, `:1159`, called at `:8980–8991`).

Both keep `Proposal.units` unchanged while removing refs from `pieces`. So a unit can stop playing, a dependency can lose its target, and the last **played** unit can become a question. These paths are reachable in production (`check=True`).

`short_variant` (`autocut.py:1922`) uses `_prune`, which is guarded by `needed` and keeps the first and last units, so it preserves both invariants. It is off in production (`short_variant: false`).

---

## 1. Decision table

Flag names are **PROVISIONAL** (ARCH_QUESTION AQ2). Each becomes an `AutocutConfig` field (`extra="forbid"`) and an `AutoParams` field, mapped in `cmd_autocut` (`__main__.py:8609`). The default is OFF. When OFF, the design executes the frozen code path; the parity tests (§3) must prove it.

| TC | Root mechanism | Selected strategy | Invariants | Future touched symbols | Fail-before / pass-after / negatives | Deps · proof |
|---|---|---|---|---|---|---|
| **TC5** #5 *(unchanged from R1)* | S5(a) drops the first sentence without a min_sec test (`:713–720`) | **Guard (a):** take the drop only if `Σ_dur − rows[0].sec ≥ min_sec`, else fall through to (b)/(b2)/(c)/soft/reject. **Post-check** right after `context_start` returns (`Σ_dur < min_sec` → `no_start`, reason `dur_below_min_sec`). After S5, only `fix_open_end` shortens, and it enforces min_sec (`:641`), so the invariant holds at publication. | `_dur` measure unchanged (AQ4); refs untouched | `AutoParams.fix_context_min_sec`; `context_start` (one condition); `propose` (one check) | FB: FX-5 → 25→23 s returned. PA: (a) not taken; repaired to ≥ 25 or `no_start` with reason. Neg: a drop leaving ≥ min_sec still happens. | none · CLI_HELPER_BOUNDARY (25→23) |
| **TC7 + TC8a** #7/#8a *(R2 — P1-1)* | S4 removes a dependency target (TC7) or appends a question at the end (TC8a). S5(c) drops a loop question that a kept unit leans on (P1-1). | **FINAL validator `_final_integrity`** after the final rhythm verdict (`:1256`) and before the pool checks (`:1257`), §2.1. Dependency = `leans_on(u, by_id, 1)` edge (`standalone is False and refers in by_id`, **integer id, no coercion**). An edge is **established** once both ends are in the clip at any observation point S0…S6. It is **broken** if the dependent is present at publication and the target is not. Also rejects `clip[-1].role == "question"`. The failure channel is set by the stage that removed the target or made the tail (§2.1). The R1 rhythm-local check is **dropped**: stage attribution gives the same diagnostic, and a single guard cannot be bypassed. | question-first loop: only the **last** unit's role is tested, and a valid `[q, …, payoff]` keeps its edges. Never-established edges are not judged (§2.1). | `AutoParams.fix_final_integrity`; `propose` (stage snapshots S0…S6 + final check); `cmd_autocut::_try_accept` (CLI re-check, §2.2) | FB: FX-7 `[1,3]` with `#3.refers=2`; FX-8a ends on a question; **FX-7L (new)**: loop question #10 dropped by S5(c) while kept `#11.refers=10` (REPORTED by Sol at HELPER level). PA: no proposal; reasons in `rhythm_out` / `no_start`. Neg: `[1,2,3]` untouched; `standalone=True` with `refers` set is not an edge; a valid question-first loop with its question kept passes. | none · HELPER_CONFIRMED (M225 A/B); FX-7L REPORTED |
| **TC8b** *(unchanged)* | `fix_open_end` trims to 2.5 s; the final `rhythm_why` rejects (`:1239`, `:1250`) | Default = current behaviour: already fail-closed **and logged** in `rhythm_out` (printed at `:9138`). Pinning regression test only. Recovery is OWNER Q6. | unchanged | tests only | FB = PA: 0 proposals, `rhythm_out` non-empty, `open_end` empty. | none · HELPER_CONFIRMED; recovery NOT_VERIFIED |
| **TC2** #2 *(R2 — P1-2)* | `context_start` judges the body opener with `stands_alone` only (`:707`); the apply path skips `montage` lines (`__main__.py:6822`). The M145 soft fallback (`:711`, `:768–772`) caches on `_alone is None` and can return a strict-invalid start. | **One composable start predicate** `_start_why(ref, text, following) → (timing, semantic)` used at **every** decision point: normal acceptance, repair (a), the M197 drop, (b) context candidates, (b2) later candidates, soft capture and soft return. `timing = glued_start(...)`. `semantic = stands_alone(...) or _strict_body_why(text, p)` (§2.3). **Soft may relax timing only:** capture iff `timing and semantic is None`. A soft clip is semantically valid by construction, so soft return can never publish a semantic-invalid start. No valid repair → `(None, notes, semantic reason)` → `no_start`. `require_morph()` is called at `context_start` entry, before any early return, when the flag is on and `start_strict and start_morph` (as in `scenario.py:197–199`). | Question-first exemption: `_strict_body_why` returns `None` for a sentence ending in "?"; the legacy `stands_alone` still applies to it. Hook order unchanged. | `AutoParams.fix_body_start`; new pure helpers `_strict_body_why`, `_start_why`; `context_start` (all predicate call sites) | FB: FX-2 clip A keeps «Да, конечно.». PA: starts at 1.2, or is repaired earlier, or `no_start`. Neg: **FX-2G (new)** glued + strict-invalid + no repair → `no_start`; missing pymorphy3 with `start_morph` → `RuntimeError` before any return; glued but semantically valid with no repair → soft kept (M145) with note; FX-2 clip B question-first passes. | TC5 guard (shared drop path) · CLI_CONFIRMED bounded (M223) |
| **TC9a** #9a *(R2 — complexity corrected)* | `build_passage` `break`s when the preferred pick overflows (`:404`) | Side closing (R1 design). Exact: the neighbour on a side changes only when the run grows on that side, and `total` is monotone. | equal to legacy when no overflow occurs | `AutoParams.fix_passage_side`; `build_passage` | FB: FX-9a → `None`. PA: `[4,5]`. Neg: both sides overlong → `None`. **Bound:** ≤ `len(units)+2` loop iterations. **Time O(n²) worst case** (R1's "O(n)" withdrawn): each iteration recomputes jumps over `run` and copies `run`. | none · HELPER_CONFIRMED |
| **TC3** #3 *(unchanged)* | `propose` has no `clauses`; `_hook_cands` always gets `None` (`:1281`, `__main__.py:8818`) | OWNER Q3. Mechanism as in R1: `propose(..., clauses=None)` as the last keyword, forwarded at `:8818` only. `hook_clauses_autocut: off \| rescue \| full`. | `hook_clauses=false` → `clauses is None`; `rescue` keeps hooked clips identical | as R1 | as R1 + apply-parse test of `h:B.N@i-j!` | owner Q3 |
| **TC9b** #9b *(R2 — P1-5)* | post-loop pop of a trailing question; the following answer is never visited (`:408–409`) | OWNER Q7-b; **default Б0** (no extension, package not opened). If chosen: one bounded step, keep the question and append `a = by_id[q.id+1]` only if `a.role != "question"` (**explicit**, because `eligible()` admits questions), `usable(a)`, gap ≤ `passage_gap_sec`, `total + _dur(a) ≤ max_sec`, `eligible(a)`, rhythm jump limit holds when `p.rhythm`, and (Б1) `a.role ∈ PAYOFFS`. Afterwards, **independently of `p.rhythm`**, the run's last role must not be question; otherwise revert to the legacy pop. | question never last; at most one extension per build | `AutoParams.passage_answer`; `build_passage` post-loop | FB: FX-9b → `[u1]`. PA (Б1/Б2): `[u1,u2,u3]`. Neg: **two consecutive questions** → no extension, legacy result; overlong answer / gap > limit / non-payoff (Б1) → `[u1]`; the extension is applied at most once (counter). | owner Q7-b; after TC9a |
| **TC1** #1 *(R2 — P1-4)* | a seed inside an earlier candidate is skipped (`:1175`); `taken` blocks growth (`:1257`, `:1263`) | **Complement variants (R1) + two-phase selection** (§2.4). Pass 2 generates at most `seed_alt_max` variants with exclusion set `E = ids(sup) − {s}`. Variants are **held outside the legacy pool**. The CLI runs the **complete legacy lifecycle unchanged** (Phase L). Only then are variants considered for slots still free (Phase V). | Phase L sees only the legacy pool ⇒ legacy decisions identical by construction, in greedy and global modes, at any pool size. Dedup by union conflict against everything accepted. | `AutoParams.seed_alt`, `seed_alt_max`; `propose` (suppressor record, pass 2, return channel §2.4); `Proposal.alt_of`; `cmd_autocut` (Phase V after `:9075`) | FB: FX-1 u2-alone absent. PA: variant `{2}` exists. **Neg FX-1H (new):** `fill_pool` active + `hookless_last=true` + 1 slot, legacy hookless candidate vs conflicting hooked variant → legacy accepted, variant not; identical with the flag on/off, `select: greedy` and `global`. | M231 trace · CLI_CONFIRMED mechanism; benefit unproven |

---

## 2. Specifications

### 2.1 `_final_integrity` (P1-1)

**Snapshots.** `snap[k] = [u["id"] for u in clip]` at S0 (after build), S1, S2, S3, S4, S5 and S6. Ids only; no copies of dicts.

**Established edges.**
```
EST = ⋃_k { (u, t) : u, t ∈ snap[k], t = leans_on(by_id[u], by_id, 1)[0] }
```
An edge counts if it exists at **any** observation point.

**Broken edges.** `(u, t) ∈ EST` with `u ∈ final ids` and `t ∉ final ids`.

**Attribution.** `stage(t)` = the first k at which `t` is in `snap[k−1]` but not in `snap[k]`. Only S4 (`fit_rhythm`) and S5 (`context_start` (c)) can remove units.

**Question-end.** `final[-1].role == "question"` → attributed to S4, the only stage that can append a non-PAYOFF tail.

**Channels.**

| Stage | Channel | Reason |
|---|---|---|
| S4 | `rhythm_out` | `"финал: опора #t нужна #u — убрана ритмом"` / `"финал: ритм добавил вопрос в конец"` |
| S5 | `no_start` | `"финал: опора #t нужна #u — убрана при поиске начала"` |
| unknown (defensive) | `rhythm_out` | prefix `"финал:"` |

Then `continue`. All of this is gated by `fix_final_integrity`.

**Deliberate asymmetry (documented, AQ7).** An edge that never coexisted in the clip at any observation point is **not** judged. A clip that was built with `u` leaning on an absent `t` is therefore out of TC7 scope; the start rules govern its first unit. A loop question that the clip leans on (it is chosen with weight 3 for leaned questions, `:1104`) establishes its edge at S1. Its later S5(c) removal is therefore broken → reject. So the same final unit list can be accepted when no loop was tried and rejected when a loop was tried and dropped. Fail-closed is chosen on purpose; the coordinator confirms at the A2 code gate.

**Transitive support.** Every direct edge preserved ⇒ the closure is preserved.

### 2.2 CLI re-check after `_drop_last_sentence` / `_drop_sentences` (P1-1, "later mutation")

Under `fix_final_integrity`, inside `_try_accept`, for montage-pool proposals only (`not scenario`; the scenario path stays byte-identical, AQ8):
1. `played(pr)` = the units having ≥ 1 sentence of their (`unit_refs` or map) refs in `pr.pieces`.
2. A shortened `_short`/`_less` is taken only if, against the pre-shortening `pr`, no edge `(u,t)` with `u, t ∈ played(pr)` loses `t` while keeping `u`, and the last played unit's role is not question.
3. Otherwise the shortening is **not taken**. `pr` keeps its original `err` → `rejected`, with the note `"финал: укорочение нарушило опору/концовку — не взято"`.

Bound: each loop already runs at most twice (`:8966`, `:8980`).

### 2.3 `_strict_body_why(text, p)` and `_start_why` (P1-2)

`_strict_body_why` returns `None` if the flag is off, if `not p.start_strict`, or if `text.rstrip().endswith("?")`. Otherwise it returns, in order:
1. `strict_start_reason(text)`;
2. if `p.answer_start`: `answer_start_reason(text, "")`;
3. if `p.start_morph`: `clipcheck.start_morph(text.split())`.

This is the same order as `scenario.py:203–217`; the montage-path `host_text=""` is DEFER.

`_start_why(ref, text, following) = (glued_start(ref, p, start_pause), stands_alone(text, following, p, judge, core) or _strict_body_why(text, p))`.

**Call sites in `context_start`:**

| Call site | Rule |
|---|---|
| first-row verdict | `why = timing or semantic` |
| soft capture | iff `timing and semantic is None` |
| repair (a) next row | must have `(None, None)` |
| M197 drop (answer-word first row, any length) | next row `(None, None)` and `Σ_dur ≥ min_sec` (TC5 guard) |
| (b) context candidate `prow[0]` | `(None, None)` |
| (b2) later candidate | `(None, None)` |

`scenario.py` is not refactored (DEFER).

### 2.4 TC1 two-phase lifecycle (P1-4)

**Generation (`propose`).**
- Pass 1 is legacy. `out.sort` and `out[:p.clips]` (`:1309–1310`) are unchanged and return the legacy list.
- Pass 2 (variants) follows R1 §2.1: suppressor `sup[s]`, visited key `(s, frozenset(E))`, depth 1, attempts ≤ `seed_alt_max`, candidate identity `(tuple(ids), pieces)`, and the full per-candidate pipeline including `_final_integrity`.
- Variants are **not** in the returned list. They reach the CLI through an additive out-list keyword `variants_out: list | None = None` (default `None` → pass 2 does not run at all). This is a signature change, approved only at the A8 code gate.

**CLI lifecycle (complete; the step order is the frozen order).**

| # | Step | Line | Sees variants? |
|---|---|---|---|
| 1 | main `propose` | `:8818` | no (variants go to `variants_out`) |
| 2 | weak-seed fill trigger + `fill_pool` re-sort | `:8822–8831`, `autocut.py:1325` | no |
| 3 | interviewer filter | `:8832–8837` | no |
| 4 | `start_doubt` sort | `:8838–8841` | no |
| 5 | `check_seams` on `pool[:clips*2]` + sort | `:8915–8921` | no |
| 6 | global/greedy pick, `pool = picks + rest` | `:9038–9050` | no |
| 7 | primary loop: `_polish`, `_keys_rule`, `hookless_last` deferral, `_try_accept` | `:9053–9068` | no |
| 8 | deferred hookless pass | `:9069–9075` | no |
| 9 | **Phase V (new):** see below | — | **yes** |
| 10 | plate redo, `short_variant`, draft | `:9076–` | as frozen; variants accepted in step 9 follow the frozen handling of accepted clips |

**Phase V (step 9).** Runs only if `seed_alt` is on and `len(accepted) < prm.clips`.
- Order variants by `(-score, attempt order)`, deterministic.
- Drop every variant with `union_conflict(v, a)` for any `a ∈ accepted`, where union conflict = `_close` **or** `legacy_conflict` (passage: any shared unit; else `|shared| > overlap_max·min` or the same last unit).
- Then run the frozen per-candidate steps (`_polish`, `_keys_rule`, the `hookless_last` deferral **inside Phase V**, `_try_accept` with the union conflict) until `prm.clips` are reached.
- Every variant left over gets a fate: `variant_close`, `variant_rejected`, `variant_not_reached`.

**Guarantees (ANALYTIC; tests required).**
1. Phase L is the frozen lifecycle on the frozen pool ⇒ the accepted/rejected/close/not_reached/hookless_left lists for legacy candidates are identical with the flag on or off, in greedy or global mode, and with pool > 30.
2. Accepted variants only take free slots and never share a unit (in passage mode) with any accepted clip.
3. **What R1 claimed and R2 withdraws:** variants can **not** displace legacy picks. The R1 "selector may trade" benefit (global sum ≥ legacy with swaps) is withdrawn. A replace/global mode would forfeit guarantee 1 and is **DEFER**: it needs a separate gate and M231 evidence.

**Prerequisite.** M231 `seed` (suppression) and `fate` events must be accepted before A8 opens. Variants help only when legacy under-fills; how often that happens is unknown.

---

## 3. Global invariants (each must be a test in every M232 package)

1. **OFF parity (to be proven, not assumed):**
   - with the package flag off, `propose()` output equals a golden JSON generated **at `3c011e9`** by a committed script, on every FX fixture and every committed M223/M226/M227 synthetic map;
   - the synthetic `cmd_autocut(llm="none")` review file SHA256 equals the base value (M226 preflight `95350aa0…` is a known reference);
   - for A2/A8, `_try_accept` and Phase V produce byte-identical drafts when off.
2. **Question-first loop:** `[q, …, payoff]` with intact edges is never rejected by a new check.
3. **With the relevant flag on, every returned Proposal satisfies:** min_sec (A1); no broken established edge and no question tail (A2); a semantic-valid start (A3). This includes after CLI shortening (A2, §2.2).
4. **Dedup:** no two accepted proposals share a unit in passage mode, and every accepted pair has `_close is None`.
5. **No new LLM call inside `propose`; no network in tests;** judge spies report equal call counts with flags off.
6. **Manual path:** no change to the apply stage lists or `selection_source: human` handling.
7. **Failure set** equals `handoff/m222/baseline-failures.txt` (29 known failures, incl. `test_m202_*`, `test_m177_*`) via `compare_failures.py`.

## 4. DEFER items and their settling observation

| Item | Settling observation |
|---|---|
| TC8a prevention in `fit_rhythm` | M231 count of S4 question-tail rejects > 0, plus a fixture where the other side can grow |
| TC7 cascade removal | a fixture with a dependent outside `keep` whose remainder passes rhythm |
| TC3 clause after the threshold, sentence before it | an owner-judged synthetic case |
| TC2 interviewer-reply (`host_text`) on the montage path | an `_other`-based fixture |
| TC1 replace/global variant mode | M231 `fate` events showing legacy under-fill with a better swap |
| weak-seed wiring; `teaser_misses` alignment | the M227 mismatch replayed at the CLI with alignment loaded |
| #4 post-select fallback | M231 `fate`: picked → rejected with a feasible unpicked replacement |
| #6 measure change | M231 boundary deltas `d0`/`d1` that change a min/max/rhythm verdict or `@speed` |

## 5. R2 change log (what changed and why)

| Location (R1) | R1 statement | R2 | Finding |
|---|---|---|---|
| §0 | "exactly three gaps" | withdrawn; inventory with S0…S6 incl. S5(c) loop drop | P1-1 |
| §1 TC7/TC8a | post-check after `fit_rhythm` | final validator with established edges + stage attribution; CLI re-check | P1-1 |
| §1 TC2, §2.2 | predicate in normal checks and repairs | one predicate also at soft capture/return; `require_morph` at entry | P1-2 |
| §0, §2.5 | "#6 affects duration bookkeeping only; playback unreachable" | retracted; code-level output influence (`@speed`, score, `k:`); playback UNKNOWN | P1-3 |
| §2.1 TC1 selection | variant-tail ordering; global sum ≥ legacy | two-phase lifecycle; swap benefit withdrawn | P1-4 |
| §1 TC9b | eligible answer | explicit non-question answer; final role check independent of rhythm | P1-5 |
| §1 TC9a | O(n) | ≤ `len(units)+2` iterations, O(n²) time | complexity |
| §3.1 | "OFF executes the frozen path" | marked as a test obligation | parity wording |
