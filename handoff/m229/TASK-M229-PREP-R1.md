# TASK M229-PREP-R1 — Deterministic regression contracts and architecture handoff

**Executor:** Claude Code Sonnet 4.6. **Independent QA:** Sol 6.1. **Coordinator:** ChatGPT. **Status:** READY_FOR_EXECUTION; **M229_CODE_GO=NO**.

## Authority / frozen sources

- Production base: `main@3c011e94263e16e5780936b4769d3490cd03b682`.
- Accepted synthesis: `handoff/m228/SOL-REVIEW-R2-ACCEPTANCE.md` (reviewed M228 at handoff SHA `1207bda6ada5fd207abf93730c669816737169f7`).
- Coordinator scope: `handoff/m228/COORDINATOR-DECISION-M229-PREP.md`.
- Read `CLAUDE.md`, `handoff/m222/QA-STOP-RULES.md`, `handoff/m228/FINDINGS.md`, `handoff/m228/ARCHITECTURE.md`, `handoff/m228/GATES.md`, `handoff/m228/REPORT.md`, and accepted Sol reviews M223–M227 at their pinned evidence SHAs.
- `handoff` is an orphan evidence branch. Do not compare its full tree with main as evidence of source deletions. If the Mac Documents path is blocked, use a permitted isolated checkout/snapshot; do not bypass OS permissions.

## Strict allowed scope

**Documentation / evidence scaffolding ONLY**, limited to `handoff/m229/`. Do **not** edit or commit `src/`, `tests/`, `config/`, `CLAUDE.md`, production `main` or user media paths. Do not make a production PR, merge, deploy or start M230/231/232. No network LLM/API calls, rendering, owner audio/video/logs/transcripts, or paid APIs. No new broad M223–M227 diagnostic runs.

## A. Build a precise test contract map

Create `handoff/m229/REGRESSION_CONTRACTS.md` **in Russian**. Give one row per FIX_NOW subcase:

`#1, #2, #3, #5, #7, #8a, #8b, #9a, #9b` (nine cases from seven parents).

Mandatory columns:
- deterministic test ID and frozen source SHA;
- original function + exact call site/line or symbol;
- accepted proof level and independent Sol review; distinction from hypothesized user impact;
- minimal synthetic units/refs/timing/callbacks/config keys;
- **fail-before observable** from accepted evidence (or `NOT_YET_REPRODUCED` when lacking);
- **pass-after invariant** subject to M230 architecture decision, not implemented here;
- negative/fail-closed and feature-off parity assertions;
- proposed code-owner milestone M232, dependencies/semantic decision.

Keep the current source contract: typed `Proposal`, manifest and text-only cloud boundary, source-provenance spans, stable IDs, manual selection preservation, no real rendering. Never claim a regression test has been run merely because its case is specified.

Specific safety:
1. #1 distinguishes bounded alternative **candidate enumeration** from legal final overlap/dedup. Do not require simultaneously accepting overlapping clips; no late media rejection proof.
2. #2 does not outlaw supported question-led loop openings; distinguish body opener and actual first planned sound.
3. #3 clauses hook rescue is helper counterfactual, needs `hook_clauses` flag and owner/architect semantics.
4. #5 25→23s is CLI-helper boundary, final Proposal unknown.
5. #7 references `refers=2` after trimming original `propose` helper, not rendered output.
6. #8a last question vs permitted first question; #8b legal repair neighbor remains NOT_VERIFIED, reject with reason when unavailable.
7. #9a overlong next / prior fallback helper only; #9b answer after question is not an unconditional mandated repair.
8. #4/#6/#11 are `INSTRUMENT_FIRST` (not part of FIX_NOW test rows); document observational counter contracts separately without code.

## B. Fixture catalog, static mapping

Create `handoff/m229/FIXTURE_CATALOG.md` **in Russian** specifying test-only synthetic fixture blueprints for each test ID (unit fields, `role`, `punch`, `topic`, `refers`, `t0/t1`, sentence tuple, optional `start_pause`/clauses/end_tone, expected source refs and no owner content). Reuse accepted M223–M227 fixture logic or reference it by pinned SHA; do not generate private user text/video.

Define how each future code stage will assert:
- existing baseline test suite PASS;
- new defect regression FAIL-before on the pinned base, PASS-after only on code-fix SHA;
- negative fail-closed cases PASS when the reject reason is correct;
- deterministic seeds 0/42/1337 where randomness exists, and idempotency;
- feature flag off baseline parity and stable user/manual selection;
- no nonempty-input/zero-output false success.

Optional: a tiny read-only `handoff/m229/REPRO_PREP.py` may check *fixture schema/source reachability* in a disposable snapshot. If you actually run it, capture exit, stdout/stderr and hashes. It must NOT be a pretense of proving an unimplemented future pass-after or produce a new production effect claim. Not required for acceptance.

## C. Callgraph and M230 design agenda

Create `handoff/m229/CALLGRAPH_AND_ARCH_QUESTIONS.md` **in Russian** with:
- precise source entry points: CLI `cmd_autocut` → `propose` → helpers/context/repair → selection → validator → review writer. Mark **observed** vs **static** edges and phase boundaries.
- each affected symbol (including `used_seeds/taken`, `build_passage`, `context_start`, `fit_rhythm`, `_hook_cands`, `select_global`, `teaser_misses`); permissions: all code behind M230 arch acceptance.
- architecture questions requiring an explicit decision: #1 bounded reattempt N and stop condition, #3 clause rescue, #8b legal repair neighbor, #9b question/answer semantics, compatibility of potential `build_passage` return changes, post-repair/final validation ordering.
- state exactly what M231 observability will measure (eligible, attempted, None reasons, pool, selected, accepted, t0/t1 delta), **without changing behavior**, and what must wait until post-M231 gated M232 implementation.
- risk: no automatic claim of real user impact, real media approval, or LLM calls.

## D. Audit-ready handoff

Create `handoff/m229/REPORT.md` **in Russian** containing exact base/evidence pins, changed paths, the nine test IDs and coverage matrix, source/config settings, verified vs not-executed checks, all unresolved architecture decisions, `PRODUCTION_DIFF=NONE`, and `M229_CODE_GO=NO`.

Publication:
- Commit/push docs/test blueprints only to `origin/handoff`.
- Return `TASK=M229-PREP-R1`, `BASE_SHA`, `FINAL_HANDOFF_SHA`, `CHANGED_PATHS`, `TEST_SPEC_COUNT=9`, `OWNER_MEDIA_WRITES=NONE`, `PRODUCTION_DIFF=NONE`, `READY_FOR_SOL_QA=YES/NO`.
- Stop for independent Sol 6.1 QA. This is **not** M230 architecture approval and **not** code execution permission. No M229 production code; no model/render.
