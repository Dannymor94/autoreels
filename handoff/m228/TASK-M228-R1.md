# TASK M228-R1 — Formal evidence synthesis and architecture decision (NO production edits)

**Executor:** Claude Code Sonnet 4.6. **Independent reviewer:** Sol 6.1. **Owner/coordinator:** ChatGPT. **Status:** READY_FOR_EXECUTION after M227 PASS_SCOPED. This file supersedes `handoff/m228/TASK-M228.md` wherever they differ.

## Frozen baseline and prerequisites

- Production baseline `main@3c011e94263e16e5780936b4769d3490cd03b682` — **NOT** the obsolete `f92b4d2` mentioned in the old M228 task.
- `handoff` is an **orphan evidence branch**, not a production overlay or a normal merge base. Use the exact main source archive plus explicit handoff files in a disposable worktree/snapshot; never interpret whole-tree comparison as production deletion.
- Read `CLAUDE.md`, `handoff/m222/QA-STOP-RULES.md`, `handoff/m222/PLAN-M222-V2.md`, `handoff/m228/COORDINATOR-LEDGER-DRAFT.md`, and the **independent Sol reviews**, not merely developer REPORTs:
  - M223 `handoff/m223/SOL-REVIEW-R5.md`, evidence `9bb5667386b70ac93f041b8abb9f22359dbca286`
  - M224 `handoff/m224/SOL-REVIEW-R2-ACCEPTANCE.md`, evidence `d18627fb0fff56c4735b3c0462b1796337989715`, erratum `78511b42887b5be7070b8241d30e6d7556e20568`
  - M225 `handoff/m225/SOL-REVIEW-STAGE-A.md`, evidence `af35a30b7e522d344dcac41ce9c2b9e4b32ea8af`
  - M226 `handoff/m226/SOL-REVIEW-STAGE-A.md`, evidence `e1be1b74cb033a8575d3967eceb8b06c3800f790`
  - M227 `handoff/m227/SOL-REVIEW-STAGE-A.md`, evidence `929646319dc55b5d6dc62f6321582bf20622cc09`
- Before starting, check for newer coordinator decisions on handoff; do not silently alter baseline/proof scope.

## Hard boundaries

1. **Documentation/analysis only.** No modifications to `src/`, `tests/`, `config/`, `CLAUDE.md`, production main, real media, review/manifest/transcript/output paths. No merge/deploy.
2. No LLM API calls, paid model calls, video render, owner data, network media upload, or live pipeline execution. Reuse already independently accepted evidence. Read-only source inspection is allowed. No new 12-scenario reproduction campaign.
3. Preserve determinism-first, cloud text-only, local render, Pydantic Manifest contract, content-based idempotency, feature-flag-off parity, protected manual selection, and the rule that nonempty input with zero output is not a successful run.
4. Do not upgrade a finding's proof level. Use `STATIC`, `HELPER`, `CLI_HELPER_BOUNDARY`, `CLI_OUTPUT`, `FINAL_PROPOSAL`, or `RENDER` accurately. Clearly separate **observed**, **inferred**, **not reproduced**, and **intentional**.
5. The published M227 `evidence.json` references a missing `repro.exit`; the independent Sol rerun observed exit0. Do not claim the historical manifest is complete. M226 order sensitivity is static inference, **not nondeterminism**. M224 and M225 do not prove final rendered clips.

## Part A — exactly 12 finding dispositions

Create `handoff/m228/FINDINGS.md` **in Russian** with exactly one main row per finding ID **#1 through #12**, optionally linking named subcases (#8a/#8b, #9a/#9b). Mandatory columns:

`ID | failure mode / invariant | highest independently accepted evidence level | observed vs not reproduced | intended behavior or policy | user-visible impact (PROVED / INFERRED / UNKNOWN) | action (FIX_NOW / INSTRUMENT_FIRST / NO_FIX_INTENTIONAL / NOT_REPRODUCED / DEFER) | target milestone | regression test contract | pinned evidence`.

Specific constraints:

- #1: viable alternative suppressed in M223 CLI; later actual media rejection NOT_REPRODUCED.
- #2: hook vs body opener checks in the M223 bounded CLI path; no invented real-audio outcome.
- #3: clauses omitted at the proposal boundary; end-to-end rescue only helper counterfactual. Propose wiring may be fixable, but protect off-flag parity.
- #4: `select_global` comparison B+C=120 vs A=95 HELPER; **late rejection not reproduced**. Never label the supposed downstream rejection confirmed.
- #5: `context_start` 25s→23s below min25 at original CLI-helper boundary; final Proposal unknown.
- #6: t0/t1 offsets 0.4s/1.0s at CLI-helper boundary; real playback mismatch unmeasured.
- #7: `propose` helper yields dependent [1,3] without refers2; final CLI clip not demonstrated.
- #8: question appended helper; later rejection after trim helper; feasible second-repair neighbor NOT_VERIFIED.
- #9: original build_passage helper premature break and question-then-answer unreachable; CLI final outcomes not shown.
- #10: `hook_judge_top: 6` is an intentional call budget, not an established defect. **NO_FIX_INTENTIONAL** until measured user impact warrants a budget decision.
- #11: M227 manual A=1→1, B=2→1 accounting vs review M-lines; no per-seed CLI spy; `build_passage None` HELPER; teaser discrepancy HELPER_ONLY with synthetic start_pause; CLI has no alignment; weak-seed missing callbacks STATIC. Choose **INSTRUMENT_FIRST** for per-stage counters and diagnostics rather than blanket fixing normal `None` returns.
- #12: same ordered input deterministic; identity permutation order sensitivity NOT_RUNTIME_PROVEN; no unsupported claim of nondeterminism.

Do not flatten composite statuses into binary `CONFIRMED/NOT REPRODUCED`. Each action needs a concrete reason and minimum test obligation. A finding may have multiple evidence levels, but one clearly justified primary action for the current gate.

## Part B — single bounded architecture decision

Create `handoff/m228/ARCHITECTURE.md` **in Russian**, describing a staged, deterministic change design:

- bounded generation/seed accounting (#1/#9), with stable IDs, non-destructive attempts, explicit counters and stopping bounds;
- single final consistency/validator boundary for opener, dependencies, duration, timing, open questions, and post-repair final shape (#2/#4/#5/#6/#7/#8). Clearly mark checks not yet demonstrated as hypotheses, and distinguish repair vs reject without inventing impossible fixes;
- minimal callback/flag wiring (#3), preserving `feature_off` behavior and source provenance;
- observability-first for #11 (stage counts: eligible, attempted, returned None by reason, pool, selected, rejected by validator, accepted; machine-readable reasons; no misleading success on zero yield);
- #10 budget unchanged; #12 no fix without genuine identity-permutation proof and impact.

Give explicit contracts for `Proposal`/Manifest invariants, dedup/idempotency, manual selection, tie-break determinism, and no feature regression. Include a dependency graph and precise gates rather than premature code snippets. Review any upcoming modifications of `propose` through the M230 architecture gate **before implementation**.

## Part C — executable implementation handoff

Create `handoff/m228/GATES.md` **in Russian** with:

1. Recommendation `GO_SCOPED` or `NO_GO` for documentation-to-fix planning (M229+), independently of whether specific finding claims remain unproven.
2. Milestone proposal M229–M236 with ordering/dependencies, allowed source paths, feature flags, no-side-effect tests, deterministic seeds, CI gates, failure/rollback criteria, and senior QA before production merge. Do not claim these tasks approved for code yet.
3. Separate unresolved decisions requiring owner/architect approval (semantic product choices, new model budget, full render or M237 A/B, increased hook judging budget).
4. A risk register naming non-reproduced impacts and the minimal instrumentation required to observe them safely.

## Part D — audit-ready delivery

- Create `handoff/m228/REPORT.md` **in Russian** listing all source review paths and their pinned SHAs, changed paths, SHA of production baseline, evidence scope, disposition counts, unresolved questions, recommended gate, and explicit `PRODUCTION_DIFF=NONE`.
- **Do not require a new REPRO.py**: this is a synthesis of independently verified M223–M227 evidence. A source cross-reference/check script is optional only if deterministic, read-only and genuinely valuable; no re-running full diagnostic stages for cosmetic proof.
- Publish `FINDINGS.md`, `ARCHITECTURE.md`, `GATES.md`, `REPORT.md` to `origin/handoff` in one scoped deliverable if possible. If publishing needs permissions, stop and report. No owner artifact writes or production commits.
- End with `READY_FOR_SOL_QA`, `BASE_SHA`, `HANDOFF_SHA`, changed paths, disposition counts, recommended GO/NO-GO, and proof gaps.
- Stop for **independent Sol 6.1 QA**. There is no M228 PASS, no M229 coding authorization and no algorithm merge until that review is published and coordinator records the decision.

## Hard stop and efficiency

Do not request M223–M227 reruns merely to improve wording, replay an already-scoped accepted helper proof, or force binary findings. If a source contradiction changes a decision, document the precise conflict and scope it. Ask owner only for choices that materially change behavior or cost. Do not invent approvals.
