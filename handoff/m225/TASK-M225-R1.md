# TASK M225-R1 — Deterministic CLI diagnostics of rhythm repair (#7 / #8)

**Executor:** Claude Code Sonnet 4.6. **Independent QA:** Sol 6.1.  
**Language:** code/task English, owner-facing REPORT.md Russian.  
**Actual production baseline:** `main 3c011e94263e16e5780936b4769d3490cd03b682` (supersedes the outdated f92b4d2 baseline in the earlier `TASK-M225.md`).  
**Gate:** `handoff/m224/SOL-REVIEW-R2-ACCEPTANCE.md` (`PASS_SCOPED`).  
**Stage:** diagnostics **only**. No production changes, PRs merging algorithms, rendering, paid LLMs, or owner-media edits.

## 0. Read first and pin

Read `CLAUDE.md`, `handoff/m222/QA-STOP-RULES.md`, `handoff/m225/COORDINATOR-PREFLIGHT.md`, `handoff/m225/TASK-M225.md`, and M224's final scoped acceptance and erratum.

Record exact `BASE_SHA`, `HANDOFF_INPUT_SHA`, `config/r0.yaml SHA256`, actual CLI params and entry point in your report. Use separate task worktree and isolated `TemporaryDirectory` for **all** test artifacts.

## 1. One reusable real-CLI harness before cases

Adapt the successful M224 R2 approach to produce a **single** synthetic CLI runner using real `cmd_autocut("synth", root=isolated_tmp, llm="none")`, production `config/r0.yaml` unmodified, and original production callbacks. Spies may only record and delegate to originals. Capture real `propose` output (exact `Proposal.pieces`, `unit_refs`, `seconds`), internal branch decisions, and draft/selection/validator outcome separately. Assert final results; printing only a spy trace is not proof of final acceptance.

Production config: `generator=mixed`, `rhythm=true`, `min_sec=25`, `rhythm_max_jumps=2`, `rhythm_jump_sec=10`, `rhythm_settle_near=6`, `rhythm_settle_far=12`, `rhythm_far_sec=120`, `rhythm_tail=0.5`, `end_tone=true`. Load it through the actual CLI; do **not** instantiate `AutoParams()` defaults or disable validators to obtain desired outputs.

## 2. Case A — #7 dependent meaning loss

Try a synthetic set where `standalone=false`, `refers=<support id>`, a short non-kept support piece is a potential removal target, and the surviving unit depends transitively on it.

Record: pre/post `fit_rhythm` IDs, `refers`, dependency closure, `keep`, `rhythm_why`, final `Proposal.pieces`, and validation outcome.

Assertion: if final accepted proposal lacks a required support unit, `CLI_CONFIRMED`; if only the direct original `fit_rhythm` helper can produce it, `HELPER_CONFIRMED, CLI_NOT_REPRODUCED`; if construction is blocked, `NOT_REPRODUCED` with exact blocking guard. Do not bypass `build_passage` or `add_payoff` merely to force CLI confirmation.

## 3. Case B — #8a question appended as ending

Try a distant last piece needing rhythm extension and a genuinely eligible neighboring `role="question"`. Show `fit_rhythm` before/after, last unit ID/role/refs, real `end_tone` result, final `Proposal`, and whether downstream checks reject/accept it.

Distinguish `question appended inside repair` from `question accepted as final output`. Claim the latter only if verified in final observed proposal/validator evidence.

## 4. Case C — #8b late rejection after trimming open ending

Use synthetic aligned words and prosody so **real** `fix_open_end` trims an open-tone tail, then show `rhythm_why` before and after trim, nearby legal neighbor eligibility, attempted or missing repair call, and final outcome.

If the candidate disappears earlier, mark the intended downstream claim `NOT_REPRODUCED` rather than manipulating config to bypass existing guards.

## 5. Optional helper-level fixtures and negative controls

For each case, include exactly one small helper fixture if CLI construction is not reachable, clearly separated `HELPER_CONFIRMED` from CLI tests. Prefer one true negative control (e.g. counterpart with reference retained or legal tail) to detect a harness that merely asserts the mechanism. If a “negative subprocess test” is claimed, **actually launch the subprocess and assert nonzero exit**; otherwise call it a config-difference test.

## 6. Deliverables and acceptance

Publish to `handoff/m225/`:
- `REPRO.py` with clear CLI-vs-helper labels and fail-closed assertions;
- `REPORT.md` in Russian, exact SHA, command, check count, **captured real exit code**, comparison of expected/actual and **one status per case**;
- immutable R1 stdout/stderr logs and SHA256 for each, avoiding the M224 stale-log mistake.

`PRODUCTION_DIFF=none`; no real `manifests/`, `transcripts/`, `reviews/`, or output-media modifications. Preserve existing user worktrees. Reuse script infrastructure from M224 R2, without copying old stdout as new proof.

**Predeclared acceptable outcomes:** `CLI_CONFIRMED`, `HELPER_CONFIRMED`, `STATIC_ONLY`, or `NOT_REPRODUCED` for each finding. A truthful bounded result with real proof is acceptable; **all three do not need to reproduce**. The limit is one targeted revision after independent QA, then stop/escalate per `QA-STOP-RULES.md`. Do not invent a new obligation mid-review or start M226 without Sol acceptance of M225's claimed scope.

**Finish:** publish evidence to `origin/handoff`; return `TASK=M225-STAGE-A`, `BASE_SHA`, `HANDOFF_HEAD_SHA`, `REPRO_EXIT`, `CHECKS_EXECUTED`, `CASE_A/B/C_STATUS`, `PRODUCTION_DIFF`, `LOG_SHA256S`, and blockers. Then request independent Sol 6.1 review; **no production fix**.
