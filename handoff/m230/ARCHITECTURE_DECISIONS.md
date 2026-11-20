# M230-ARCH-R3 — Architecture decisions (deterministic, bounded, flag-gated)

**Revision:** R3. It responds to the three P1 findings of Sol QA R2 (`QA-RESULT-M230-ARCH-R2.md`) and applies `COORDINATOR-AQ-DECISIONS-R2.md`. Provenance: R1 `1cdfbfaa1fb138641ef1687f6be06457b79c346c`, R2 `d471f35536d270994c8a00805376eeade587f1c3`. R2 answered the five R1 P1 findings (`TASK-M230-ARCH-R2.md`); those answers are kept.
**Coordinator decisions applied (architecture only, no code GO):**
- AQ1: additive `propose(trace=None)` approved in principle.
- AQ2: one default-OFF flag per package.
- AQ7: established-edge asymmetry accepted.
- AQ8: CLI re-check accepted for montage-origin pools (main + weak-seed), now including the A3 start check.
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
- In the **production configuration** (`context_judge: false`), `propose` makes no LLM call (`judge=None`), and LLM calls happen only in CLI polish (`_polish`, `check_seams`, plate redo) for candidates the selection loop reaches. **R3:** this is one configuration, not a universal guarantee. With `context_judge: true`, `propose` calls the judge inside `context_start`. Configuration-parameterized bounds are in REPORT §2.
- Pool = `clips × check_pool`. Above `exact_max=30`, `select_global` is greedy by weight (`:1378–1383`).

### 0.3 CLI mutations after `propose` (ANALYTIC; R2 — new)

`_try_accept` can replace a proposal with a sentence-level shortening:
- `_drop_last_sentence` (M167, `__main__.py:1136`, called at `:8966–8978`);
- `_drop_sentences` (M173, `:1159`, called at `:8980–8991`).

Both keep `Proposal.units` unchanged while removing refs from `pieces`. So a unit can stop playing, a dependency can lose its target, and the last **played** unit can become a question. **R3:** M173 can also remove the **first played body sentence**, which re-opens the strict-start problem (P1-R2-1, §2.2). These paths are reachable in production (`check=True`).

`short_variant` (`autocut.py:1922`) uses `_prune`, which is guarded by `needed` and keeps the first and last units, so it preserves both invariants. It is off in production (`short_variant: false`).

---

## 1. Decision table

Flag names are **PROVISIONAL** (ARCH_QUESTION AQ2). Each becomes an `AutocutConfig` field (`extra="forbid"`) and an `AutoParams` field, mapped in `cmd_autocut` (`__main__.py:8609`). The default is OFF. When OFF, the design executes the frozen code path; the parity tests (§3) must prove it.

| TC | Root mechanism | Selected strategy | Invariants | Future touched symbols | Fail-before / pass-after / negatives | Deps · proof |
|---|---|---|---|---|---|---|
| **TC5** #5 *(unchanged from R1)* | S5(a) drops the first sentence without a min_sec test (`:713–720`) | **Guard (a):** take the drop only if `Σ_dur − rows[0].sec ≥ min_sec`, else fall through to (b)/(b2)/(c)/soft/reject. **Post-check** right after `context_start` returns (`Σ_dur < min_sec` → `no_start`, reason `dur_below_min_sec`). After S5, only `fix_open_end` shortens, and it enforces min_sec (`:641`), so the invariant holds at publication. | `_dur` measure unchanged (AQ4); refs untouched | `AutoParams.fix_context_min_sec`; `context_start` (one condition); `propose` (one check) | FB: FX-5 → 25→23 s returned. PA: (a) not taken; repaired to ≥ 25 or `no_start` with reason. Neg: a drop leaving ≥ min_sec still happens. | none · CLI_HELPER_BOUNDARY (25→23) |
| **TC7 + TC8a** #7/#8a *(R2 — P1-1)* | S4 removes a dependency target (TC7) or appends a question at the end (TC8a). S5(c) drops a loop question that a kept unit leans on (P1-1). | **FINAL validator `_final_integrity`** after the final rhythm verdict (`:1256`) and before the pool checks (`:1257`), §2.1. Dependency = `leans_on(u, by_id, 1)` edge (`standalone is False and refers in by_id`, **integer id, no coercion**). An edge is **established** once both ends are in the clip at any observation point S0…S6. It is **broken** if the dependent is present at publication and the target is not. Also rejects `clip[-1].role == "question"`. The failure channel is set by the stage that removed the target or made the tail (§2.1). The R1 rhythm-local check is **dropped**: stage attribution gives the same diagnostic, and a single guard cannot be bypassed. | question-first loop: only the **last** unit's role is tested, and a valid `[q, …, payoff]` keeps its edges. Never-established edges are not judged (§2.1). | `AutoParams.fix_final_integrity`; `propose` (stage snapshots S0…S6 + final check); `cmd_autocut::_try_accept` (CLI re-check, §2.2) | FB: FX-7 `[1,3]` with `#3.refers=2`; FX-8a ends on a question; **FX-7L (new)**: loop question #10 dropped by S5(c) while kept `#11.refers=10` (REPORTED by Sol at HELPER level). PA: no proposal; reasons in `rhythm_out` / `no_start`. Neg: `[1,2,3]` untouched; `standalone=True` with `refers` set is not an edge; a valid question-first loop with its question kept passes. | none · HELPER_CONFIRMED (M225 A/B); FX-7L REPORTED |
| **TC8b** *(unchanged)* | `fix_open_end` trims to 2.5 s; the final `rhythm_why` rejects (`:1239`, `:1250`) | Default = current behaviour: already fail-closed **and logged** in `rhythm_out` (printed at `:9138`). Pinning regression test only. Recovery is OWNER Q6. | unchanged | tests only | FB = PA: 0 proposals, `rhythm_out` non-empty, `open_end` empty. | none · HELPER_CONFIRMED; recovery NOT_VERIFIED |
| **TC2** #2 *(R2 — P1-2)* | `context_start` judges the body opener with `stands_alone` only (`:707`); the apply path skips `montage` lines (`__main__.py:6822`). The M145 soft fallback (`:711`, `:768–772`) caches on `_alone is None` and can return a strict-invalid start. | **One composable start predicate** `_start_why(ref, text, following) → (timing, semantic)` used at **every** decision point: normal acceptance, repair (a), the M197 drop, (b) context candidates, (b2) later candidates, soft capture and soft return. `timing = glued_start(...)`. `semantic = stands_alone(...) or _strict_body_why(text, p)` (§2.3). **Soft may relax timing only:** capture iff `timing and semantic is None`. A soft clip is semantically valid by construction, so soft return can never publish a semantic-invalid start. No valid repair → `(None, notes, semantic reason)` → `no_start`. `require_morph()` is called at `context_start` entry, before any early return, when the flag is on and `start_strict and start_morph` (as in `scenario.py:197–199`). | Question-first exemption: `_strict_body_why` returns `None` for a sentence ending in "?"; the legacy `stands_alone` still applies to it. Hook order unchanged. | `AutoParams.fix_body_start`; new pure helpers `_strict_body_why`, `_start_why`; `context_start` (all predicate call sites); **R3:** `Proposal.seed_id` (defaulted, not serialized) set at `:1300`; `cmd_autocut::_try_accept` slices `:8966–8978` and `:8980–8991` (reversible adoption, §2.2); one `require_morph()` call at montage-selection entry | FB: FX-2 clip A keeps «Да, конечно.»; **FX-2S (R3):** M173 turns `1.1-2 2.1` into `1.2 2.1` with `1.2`=«Да, конечно.» and it is accepted (fake check). PA: starts at 1.2, or is repaired earlier, or `no_start`; FX-2S shortening not taken → `rejected` with the original error and note. Neg: valid M173 shortening (new first sentence stands) is taken; new first sentence is a question → taken (exemption); missing pymorphy3 → `RuntimeError` before the first acceptance; timing-only (glued) new start → taken; main and weak-seed origin both covered; scenario pool untouched. **FX-2G (new)** glued + strict-invalid + no repair → `no_start`; missing pymorphy3 with `start_morph` → `RuntimeError` before any return; glued but semantically valid with no repair → soft kept (M145) with note; FX-2 clip B question-first passes. | TC5 guard (shared drop path) · CLI_CONFIRMED bounded (M223) |
| **TC9a** #9a *(R2 — complexity corrected)* | `build_passage` `break`s when the preferred pick overflows (`:404`) | Side closing (R1 design). Exact: the neighbour on a side changes only when the run grows on that side, and `total` is monotone. | equal to legacy when no overflow occurs | `AutoParams.fix_passage_side`; `build_passage` | FB: FX-9a → `None`. PA: `[4,5]`. Neg: both sides overlong → `None`. **Bound:** ≤ `len(units)+2` loop iterations. **Time O(n²) worst case** (R1's "O(n)" withdrawn): each iteration recomputes jumps over `run` and copies `run`. | none · HELPER_CONFIRMED |
| **TC3** #3 *(unchanged)* | `propose` has no `clauses`; `_hook_cands` always gets `None` (`:1281`, `__main__.py:8818`) | OWNER Q3. Mechanism as in R1: `propose(..., clauses=None)` as the last keyword, forwarded at `:8818` only. `hook_clauses_autocut: off \| rescue \| full`. | `hook_clauses=false` → `clauses is None`; `rescue` keeps hooked clips identical | as R1 | as R1 + apply-parse test of `h:B.N@i-j!` | owner Q3 |
| **TC9b** #9b *(R2 — P1-5)* | post-loop pop of a trailing question; the following answer is never visited (`:408–409`) | OWNER Q7-b; **default Б0** (no extension, package not opened). If chosen: one bounded step, keep the question and append `a = by_id[q.id+1]` only if `a.role != "question"` (**explicit**, because `eligible()` admits questions), `usable(a)`, gap ≤ `passage_gap_sec`, `total + _dur(a) ≤ max_sec`, `eligible(a)`, rhythm jump limit holds when `p.rhythm`, and (Б1) `a.role ∈ PAYOFFS`. Afterwards, **independently of `p.rhythm`**, the run's last role must not be question; otherwise revert to the legacy pop. | question never last; at most one extension per build | `AutoParams.passage_answer`; `build_passage` post-loop | FB: FX-9b → `[u1]`. PA (Б1/Б2): `[u1,u2,u3]`. Neg: **two consecutive questions** → no extension, legacy result; overlong answer / gap > limit / non-payoff (Б1) → `[u1]`; the extension is applied at most once (counter). | owner Q7-b; after TC9a |
| **TC1** #1 *(R2 — P1-4)* | a seed inside an earlier candidate is skipped (`:1175`); `taken` blocks growth (`:1257`, `:1263`) | **Complement variants (R1) + two-phase selection** (§2.4). Pass 2 generates at most `seed_alt_max` variants with exclusion set `E = ids(sup) − {s}`. Variants are **held outside the legacy pool**. The CLI runs the **complete legacy lifecycle unchanged** (Phase L). Only then are variants considered for slots still free (Phase V). | **R3:** Phase L = steps 1–12 of §2.4.2, including the late plate redo, legacy short variants and the stats print. No variant object and no variant provider call exists before the boundary ⇒ legacy outputs and the provider-request prefix are identical (conditional on the §2.4.2 inventory being accepted). Dedup by union conflict against everything accepted. Interviewer-off is applied to variants (V1). | `AutoParams.seed_alt`, `seed_alt_max`; `propose` (keywords `variant_descs_out`, `variant_descs`; §2.4.1); `Proposal.alt_of`; `cmd_autocut`: G1 at `:8818`, Phase V after `:9107`, `_try_accept` keyword targets (defaults = frozen lists), `_counted` exclusion `:9160`, variant draft section | FB: FX-1 u2-alone absent. PA: variant `{2}` exists. **Neg FX-1H (R2):** `fill_pool` + `hookless_last=true` + 1 slot, legacy hookless vs conflicting hooked variant → legacy accepted, greedy and global. **Neg FX-1I (R3):** `_other={"12.1"}`, `_ivmode="off"`, variant `12.1`, free slot → `variant_interviewer`, for `check=False` and fake `check=True`; a clean variant is accepted. **Neg FX-1P (R3):** fake provider; legacy titles, plates, all serialized fields and the provider request sequence with the flag on (variants accepted / rejected / hookless-deferred / only considered) equal the flag-off run, as a prefix; greedy + global, fill + hookless. | M231 trace · CLI_CONFIRMED mechanism; benefit unproven |

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

### 2.2 CLI re-check after M167 / M173 shortening — A2 integrity **and** A3 start (R2 P1-1 + R3 P1-R2-1; AQ8 accepted)

**Defect traced (ANALYTIC; REPORTED by Sol at helper level).** `_drop_sentences` (`__main__.py:1159–1183`) removes arbitrary refs and keeps `Proposal.units`. M173 (`:8980–8991`) can therefore remove the **first played body sentence**: Sol showed `1.1-2 2.1 → 1.2 2.1`. The montage apply path skips the strict-start check (`:6822`), so a start such as «Да, конечно.» would be published. The A2 integrity check does not see it, because no edge breaks and no question ends the clip.

`_drop_last_sentence` (M167, `:1136`) removes only the last ref. It can never change the first played sentence, but it can change the last played unit, which is what A2 checks.

**Origin classification (AQ8).** In frozen code the pool is either entirely scenario-origin (`if scenario:` branch, `:8795–8816`) or entirely montage-origin: main `propose` (`:8818`) plus weak-seed extras (`:8825–8828` via `fill_pool`). So the re-check predicate is `_montage = not scenario`. That covers main and weak-seed candidates and leaves the scenario path byte-identical. For tracing only, a weak-seed candidate is tagged by object identity in `_extra`.

**Reversible adoption.** This changes the order inside each of the two frozen loops at `:8966` and `:8980`. The current order is: compute the shortened candidate → append the note to `pr.notes` → replace `pr` → re-check. The new order: compute the candidate `c` (`_short` / `_less`), and **before any mutation of `pr`** evaluate:

| Flag | Condition `c` must satisfy |
|---|---|
| `fix_final_integrity` | no edge `(u,t)` with `u, t ∈ played(pr)` has `t ∉ played(c)` and `u ∈ played(c)`; and `role(last_played(c)) ≠ "question"` (§2.1 predicate on played units) |
| `fix_body_start` | if `first_ref(c) ≠ first_ref(pr)`, then `semantic(first_ref(c)) is None`, where `semantic` is the **same** `_start_why(...)[1]` as in `context_start` (§2.3): `stands_alone(text, next_text, p, judge, core)` or `_strict_body_why(text, p)`. The question-first exemption is identical (a first sentence ending in "?" skips `_strict_body_why`). `core` must equal `context_start`'s (`:696–697`: the summaries of the **seed** and the last unit). `Proposal.opener` is the opener unit, not the seed (`:1307`), so A3 adds a defaulted, non-serialized `Proposal.seed_id` set at `:1300`. With `judge=None` (production `context_judge: false`), `core` is unused. **Timing (`glued_start`) is not re-checked:** M145 soft semantics allow a timing-only start, and the shortening does not create a new glue decision. |

`played(x)` = the units with at least one sentence of their `unit_refs` (or map refs) in `x.pieces`. `first_ref(x)` = `expand_refs(x.pieces)[0]`.

- **Pass:** the frozen statements run unchanged (note, `c.notes = pr.notes`, `pr = c`, re-check).
- **Fail:** `pr` is **not** mutated. One note is appended, `"укорочение не взято: <reason>"`, and the loop `break`s. `err` stays the pre-shortening error → `rejected`. No published start is ever unchecked, and the candidate fails closed.

**Bounds.** Unchanged: at most 2 + 2 shortenings per candidate (`range(2)` twice), at most one predicate evaluation per shortening.

**Model calls.** A probe happens only when the A3 flag is on, the first ref changed and `judge` is configured (`context_judge: true`). At most 2 per candidate (only M173 can change the first ref).

**Missing morph.** When `fix_body_start ∧ start_strict ∧ start_morph`, `require_morph()` is called once at `cmd_autocut` entry to the montage selection block (before the first `_try_accept`). If pymorphy3 is absent the run fails with `RuntimeError` before any acceptance, exactly as `scenario.py:197–199`.

**OFF.** With both flags off, the frozen statements run in the frozen order. That is a test obligation (§3).

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

### 2.4 TC1 two-phase lifecycle (R2 P1-4; R3 P1-R2-2, P1-R2-3)

**R3 correction.** R2 placed Phase V before the late plate redo, used a single generation step, and did not filter variants by interviewer. Sol R2 showed two problems:
- **interviewer leak:** `_other={"12.1"}` with `_ivmode="off"` let a variant play the interviewer;
- **shared state:** `_forms`, which `headline` mutates and scores against (`autocut.py:1839–1848`), together with the late redo at `:9076–9081`, let variant polish change a legacy title and reorder provider requests.

R2's monotonicity claim is **withdrawn** until the complete lifecycle below is accepted.

#### 2.4.1 Generation in two steps (no variant model call before Phase L ends)

- **G1 — descriptors only.** Inside the main `propose` call at `:8818`, a keyword `variant_descs_out: list | None = None` receives, for each seed skipped at `:1175`, the tuple `(seed_id, sup_index, E)` with `E = ids(sup) − {seed}`. Rules:
  - pure: no build, no `context_start`, no judge, no callback calls;
  - deterministic order: the pass-1 seed order;
  - bounded: at most `seed_alt_max` entries;
  - `sup` is the earliest legacy candidate containing the seed, including ones later truncated.
- **G2 — build.** At the start of Phase V, `propose(..., variant_descs=descs)` runs the **same loop body** with:
  - iteration over the descriptors instead of `seeds`;
  - `E` in place of `taken`, `in_clips`, `add_payoff(taken)` and `fit_rhythm(taken)`;
  - pass-1 pool checks `:1257–1261` disabled;
  - `_final_integrity` and every enabled M232 check applied;
  - candidate identity `(tuple(ids), pieces)`, deduplicated against the legacy pool;
  - cap `seed_alt_max`.

  It returns the variants with `alt_of = sup_index`. When `judge` is configured, its calls happen here, after every legacy provider call.
- **Allowlist.** Both keywords default to `None`. With both `None`, the frozen path runs; that is a test obligation.

#### 2.4.2 Complete frozen CLI lifecycle (inventory) and where variants may enter

| # | Frozen step | Line | Shared mutable state touched | Variant visible? |
|---|---|---|---|---|
| 1 | main `propose` (+G1 descriptors) | `:8818` | `no_start`, `open_end`, `rhythm_out` | descriptors only |
| 2 | weak-seed `propose` + `fill_pool` re-sort | `:8821–8831`; `autocut.py:1325` | pool | no |
| 3 | interviewer-off filter | `:8832–8837` | pool | no |
| 4 | `start_doubt` sort | `:8838–8841` | pool | no |
| 5 | provider setup: `_forms`, `_hjudge` (+ persistent `_jstore`) | `:8860–8874` | `_forms`, judge caches | no |
| 6 | `check_seams` on `pool[:clips*2]` + sort | `:8915–8921` | `pr.bad_seams`, pool | no |
| 7 | global/greedy pick → `pool = picks + rest` | `:9038–9050` | pool | no |
| 8 | primary loop: `_polish` (judge_hooks, rank_hooks, `_plate`→`headline` with `_forms`, pick_keywords), `_keys_rule`, `hookless_last` deferral, `_try_accept` | `:9053–9068` | `_forms`, `accepted`/`rejected`/`close`, `hookless` | no |
| 9 | deferred hookless pass | `:9069–9075` | same | no |
| 10 | M112 late plate redo of accepted | `:9076–9083` | `_forms`, legacy titles | no |
| 11 | M70 `short_variant` for accepted (+check) | `:9084–9103` | `accepted`, `rejected`, `_var_rejected` | no |
| 12 | hook-judge statistics print | `:9104–9107` | stdout | no |
| — | **Phase L boundary: every legacy provider call, mutation and print above has happened.** | | | |
| 13 | **Phase V** (2.4.3) | new, after `:9107` | own lists, `_forms` (continuation), judge caches | yes |
| 14 | draft body: `accepted` numbered `M{i}`, then the rejected/no_start/open_end/scen_out/rhythm_out/close/hookless_left/not_reached sections | `:9108–9157` | `body` | appended after legacy items, own section |
| 15 | M202 accounting `_counted` vs `len(pool)` | `:9160–9163` | stdout | excluded (`alt_of is not None`) |
| 16 | write the review; console summary and lines; `_usage_report` | `:9164–9183` | file, stdout | yes, after legacy items |

#### 2.4.3 Phase V

Phase V runs only if `seed_alt` is on, `variant_descs` is non-empty, and `R = prm.clips − |{a ∈ accepted : a.variant_of is None}| > 0`. Short variants do not use main slots. Steps, in order:

- **V0 — build (G2).**
- **V1 — interviewer filter (P1-R2-2).** The *same* predicate as `:8832`, applied before any polish or model call: drop `v` if `_other and _ivmode == "off" and not scenario and set(expand_refs(v.pieces)) & _other`. Fate: `variant_interviewer`. It is applied identically for `check=False` and `check=True`.
- **V2 — order.** Stable key `(bool(start_doubt), -score, descriptor order)`. When `seam_check` is on and a provider exists, `check_seams` runs on the V1 survivors (at most `seed_alt_max`), followed by the same stable sort as `:8919`.
- **V3 — conflict.** Drop `v` if `union_conflict(v, a)` holds for any `a ∈ accepted`, including legacy short variants. `union_conflict` = `_close` **or** `legacy_conflict`. Fate: `variant_close`. No model call.
- **V4 — loop.** `_polish(v)` → `_keys_rule(v)` → `hookless_last` deferral into `v_hookless` → `_try_accept(v, acc=v_accepted, rej=v_rejected, cls=v_close, conflict=union over accepted + v_accepted)`. Stop when `|v_accepted| = R`. The keyword defaults of `_try_accept` are the frozen lists, so legacy calls are unchanged. `_polish` uses the **same** `_forms` list as a continuation: variant titles are diversified against legacy forms, and since legacy titles are already final (step 10), they cannot change.
- **V5 — deferred hookless variants** (same rule as step 9).
- **V6 — M112 plate redo of `v_accepted` only.**
- **V7 — no `short_variant` for variants** (DEFER).
- **V8 — print** one line of variant counts.
- **V9 — merge.** `accepted.extend(v_accepted)` after the legacy items. The variant fates go to a separate draft section, `# --- альтернативы (M232-A8): …`. Every descriptor gets exactly one fate from {`built_none`, `duplicate`, `variant_interviewer`, `variant_close`, `variant_rejected`, `variant_hookless_left`, `variant_not_reached`, `variant_accepted`}.

**Guarantees, conditional on the full lifecycle (ANALYTIC; to be tested):**
1. Steps 1–12 never see a variant object, and G1 makes no provider call. Therefore:
   - the legacy `accepted`, `rejected`, `close`, `hookless_left` and `not_reached` lists and every legacy `Proposal` field (title, plate, hook, keys, notes, line) are identical with the flag on or off;
   - the sequence of fake-provider requests with the flag **off** is a **prefix** of the sequence with the flag **on**;
   - this holds in greedy and global mode, at pool > 30, with `fill_pool` and with `hookless_last`.
2. Legacy draft lines `M1…Mk` (k = legacy accepted, incl. short variants) are byte-identical; variant items follow as `M{k+1}…`.
3. `_counted` excludes `alt_of is not None`. Variant accounting is separate: |fates| = |descriptors|.
4. Persistent `_jstore`: variant judgments add keys only. Within a run, every legacy lookup precedes them. A later run's legacy prompts are identical to this run's Phase L prompts, so they hit the same stored answers. **M237 ON/OFF A/B must still use separate judge stores** (AQ5).
5. No variant `Proposal` shares a mutable list (`notes`, `hooks`, `keys`, `close`, `unit_refs`, `hook_texts`) with a legacy one. G2 constructs new objects; a test checks `id()` disjointness.

What is still withdrawn: variants never displace legacy picks (the R1 swap benefit); replace mode is DEFER.

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
6a. **(R3) A8 legacy isolation:** with `seed_alt` on, the legacy part of the draft (`M1…Mk`, all legacy sections) and the console lines for legacy items are byte-identical to the flag-off run. The flag-off fake-provider request log is a prefix of the flag-on log. Variants never play an interviewer ref when `interviewer: off`.
6b. **(R3) A2/A3 CLI shortening:** with the flags on, no accepted montage-origin proposal has a shortened `pieces` whose first played sentence fails the semantic start predicate or whose played units break an established edge or end on a question.
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

## 5. Change log (R2 and R3)

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
| §0.3 (R2) | M167/M173 affect integrity only | M173 can also change the first played sentence | P1-R2-1 |
| §2.2 (R2) | integrity re-check only, adoption then check | A2 + A3 re-check before any mutation of `pr`; fail → shortening not taken, `rejected`; `require_morph` at entry; origin = `not scenario` (main + weak-seed) | P1-R2-1, AQ8 |
| §2.4 (R2) | Phase V before late plate redo; no interviewer filter; single-step generation | full lifecycle inventory (16 steps); Phase L boundary after redo, short variants and the stats print; G1 descriptors / G2 build; V1 interviewer filter; separate fates and accounting; `_forms` continuation; monotonicity conditional | P1-R2-2, P1-R2-3 |
| §3 (R2) | — | invariants 6a, 6b | P1-R2-1..3 |
