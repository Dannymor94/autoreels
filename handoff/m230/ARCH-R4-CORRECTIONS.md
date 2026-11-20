# M230-R4 — A3/A8 architecture correction (coordinator + Astra review)

STATUS=DESIGN_ONLY
BASE_R3_ARCH_SHA=231b5dfa110749602cc295906e7bc4a07215ce2e
FROZEN_PRODUCTION_SHA=3c011e94263e16e5780936b4769d3490cd03b682
SOL_R3=P1-R3-1 ACCEPTED; P1-R3-2 ACCEPTED; ADDITIONAL_A8_GAP ACCEPTED_FOR_DESIGN
M231_OBSERVABILITY_GO=NO
M232_CODE_GO=NO

The following is a **normative R4 delta** to R3 `ARCHITECTURE_DECISIONS.md` §§2.2, 2.4.1, 2.4.3 and `IMPLEMENTATION_SEQUENCE.md` A3/A8 rows. It supersedes their conflicting sentences; no code is approved. Earlier accepted contracts (including established-edge asymmetry, A2 final integrity, exactly one default-OFF flag per package, legacy two-phase isolation, owner defaults O1/V1/B0) remain intact.

## A3: recheck the semantic input after *every* materialized CLI shortening

Current R3 says “only if first ref changed”; that is insufficient: `stands_alone(text, following, p, judge, core)` depends on `following`, and M173 can delete a sentence after an unchanged first ref. M167 can change the last played unit used for `core` even when it cannot change the first ref.

For each attempted shortening in the frozen M167/M173 loops (**≤2 + ≤2 per candidate**) on montage-origin candidates (main and weak-seed, not scenario):

1. Compute temporary candidate `c`, do **not** mutate `pr`, notes, accepted lists or published draft yet.
2. Under A2 flag, run the already specified established-edge/question-tail check against `played(pr)` and `played(c)`.
3. Under A3 flag, resolve *actual played* `first_ref(c)`, `first_text(c)`, the immediately following played sentence text `following(c)` (possibly empty if a one-sentence result), and `core(original_seed, last_played_unit(c))`. `Proposal.seed_id` is a defaulted, non-serialized field set from the original seed. Recompute **unconditionally for every c** with the exact `context_start` semantic predicate `stands_alone(first_text, following, p, judge, core) or _strict_body_why(first_text, p)` (including the same question-first exemption). Never use stale original `following`/core or treat missing text as safe. No separate glued_start timing decision: a shortening did not create a new initial glue event.
4. If any required refs/text/core cannot be resolved or a check fails: do not adopt c; append exactly one non-mutating note `укорочение не взято: <reason>`; exit this shortening loop; preserve the original `_autocut_check` error and reject the original candidate through its existing stage channel. If checks pass, apply frozen mutation/recheck order.
5. When `fix_body_start ∧ start_strict ∧ start_morph`, call `require_morph()` before entering any montage selection/early exit. `scenario` path remains untouched. Default-OFF behavior must be byte-identical.

Bound: at most **4 semantic probes per candidate**, and at most `4*r_j` model application attempts for cold configured judge (`r_j≤2` → ≤8), plus existing baseline calls. This supersedes R3's “2 per candidate” budget.

**A3 mandatory fake test oracles:**

- A3-FOLLOW: `_drop_sentences` changes `1.1-3 2.1 → 1.1 1.3 2.1`; first `1.1` same, `following` 1.2→1.3; fake configured judge accepts original but rejects shortened input. Final candidate not accepted; original error and note intact.
- A3-ONE: two-sentence clip shortened to one; `following=""`, full input evaluated; no successful empty-ref shortcut.
- A3-CORE: last played unit changes, first unchanged; original seed and resulting final unit are the exact summary sources for `core`.
- A3-ORIGIN: montage main/weak-seed checks run; scenario pool and its draft bytes unchanged, including default OFF.
- A3-MORPH: configured strict morph unavailable → `RuntimeError` before any acceptance.
- A3-RATE: four attempted shortening probes, judge calls ≤8 (cold) and exactly 0 with judge disabled.

Frozen refs: `src/autoreels/cloud/autocut.py:657–673,696–707,887–920`; `src/autoreels/__main__.py:1136–1183,8966–8991`.

## A8: two-stage build, filter full refs before any variant model call

The R3 V1 interviewer guard *after* G2 is too late if G2 used a configured contextual judge. A variant may introduce an interviewer ref through backward context repair. Keep R3 G1 descriptor collection **pure** within legacy `propose`, then wait until the last legacy provider call, late plate redo, short variants, statistics and legacy prints complete (R3 Phase L §2.4.2). Variant handling starts only thereafter.

- **V0 / G2 deterministic build:** invoke `propose(..., variant_descs=descs, judge=None)` and build complete frozen `pieces`/played refs and metadata. Never use a live judge during G2. Dedup and seed_alt_max cap unchanged. G2 may still perform deterministic context repair; all final refs are visible for screening.
- **V1 guard:** apply the *same* `interviewer: off` policy as legacy CLI to **all** refs expanded from the completed `pieces`. Reject `set(expand_refs(v.pieces)) & _other` before seams, hook judge, contextual judge, title, keywords or any other variant-attributed provider call. Every rejected descriptor receives `variant_interviewer`, including with `check=False`. Reapply the guard after later structural mutations before publication.
- **V1b judge:** only after V1 on a clean frozen shape, optionally evaluate its actual first played sentence, following and core with the configured contextual judge; apply the existing `start_judge` rank/reject interpretation without rebuilding `pieces` or allowing context repair. A configured negative rejection (or unresolved required material under fail-closed policy) records an explicit variant fate; a ranking doubt only adjusts stable ordering. A second `propose` with live judge is **forbidden**.
- **V2–V9:** preserve R3 ordering, conflicts, legacy two-phase isolation, title-form continuation, short-variant DEFERRAL, separate fate section, added slots only (`R = clips - legacy accepted`) and default-off parity.

### A8 variant-only path when legacy pool becomes empty

Frozen CLI creates `_forms`, `_byid_h`, `_polish`, `_plate` and optional `_hjudge` only under `if prov is not None and pool`. Filtering can leave **zero** legacy candidates while G1 descriptors contain clean variants. Split closure initialization from the legacy `check_seams` loop. Preserve the original legacy guarded initialization/calls when its pool is non-empty. If initial legacy setup was skipped, initialize the same closures **once** lazily after V1, upon first clean variant batch, with the same provider/config/cache/form state. With `prov=None`, variants must still run deterministically without undefined closures. Never cause legacy calls when legacy pool is empty; never reinitialize or retroactively change the titles/console lines of accepted legacy candidates.

**A8 mandatory fake test oracles:**

- A8-INTERVIEWER: dirty variant whose backward repair added a played `_other` ref; `context_judge=true` and `interviewer: off`. The rejected variant produces **0** model calls, including context judge, for both `check=True/False`.
- A8-CLEAN: clean alternative can be judged after V1 without changing its `pieces`; judge-negative rank/reject outcomes obey the existing policy.
- A8-EMPTY: legacy interviewer filter empties `pool`; a clean alternative survives; test with fake provider and with no provider, `check=True/False`, and assert closure setup exactly once and no exception.
- A8-PREFIX: compare fake-provider complete request logs: flag-off sequence must be **exact prefix** of flag-on; legacy titles, drafts and stdout identical at all legacy positions.
- A8-DEDUP: each descriptor has one exact fate, accepted variants only occupy remaining main slots, no replacement of a legacy pick, and no interviewer ref is published.

Frozen refs: `src/autoreels/cloud/autocut.py:724–742,1208–1222`; `src/autoreels/__main__.py:8818–8837,8860–8923,9104–9108`.

## Independent gate and precedence

1. Sol R3 remains `CHANGES_REQUIRED`; R4 design is a coordinator draft awaiting **independent Sol R4 QA** against frozen source and regression oracles.
2. This R4 delta and `M231-BUDGET-R4-CORRECTION.md` override only their named R3 sentences, not unrelated R3 architecture. Report conflicts explicitly.
3. Do not approve M231 observability, M232 A3/A8, any production edit or owner media from this design alone. A separate scope-pinned coordinator GO requires an independent PASS and proof the intended regression is reproducible.
