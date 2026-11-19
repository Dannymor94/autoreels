# TASK: M230-ARCH-R1 — Deterministic Autocut correction architecture

ROLE: Claude Opus (independent architect; not the M229 Sonnet executor)  
MODE: ARCHITECTURE_ONLY / READ_ONLY_PRODUCTION  
REPO: Dannymor94/autoreels  
FROZEN_PRODUCTION_SHA: 3c011e94263e16e5780936b4769d3490cd03b682  
ACCEPTED_M229_SHA: 74588a219b0d055059f60185f51fd4bcf6efa6b1  
COORDINATOR_GATE: handoff/m229/COORDINATOR-DECISION-M230-ARCH-GO.md  
TEST_STATUS: SPECIFIED_NOT_EXECUTED  
M230_ARCH_REVIEW_GO=YES  
M231_OBSERVABILITY_GO=NO; M232_CODE_GO=NO

## Goal

Design the smallest safe deterministic correction sequence for all M228 FIX_NOW findings and observational prerequisites, using the M223–M229 accepted scoped evidence. The M229 test specifications are inputs to architecture, not executed proofs or authorizations. Do not run or implement production fixes.

## Required reading

- handoff/m228/FINDINGS.md, ARCHITECTURE.md, GATES.md, REPORT.md; accepted independent M228 Sol review.
- handoff/m229/REGRESSION_CONTRACTS.md, FIXTURE_CATALOG.md, CALLGRAPH_AND_ARCH_QUESTIONS.md, REPORT.md.
- handoff/m229/SOL-REVIEW-R2.md and SOL-REVIEW-R2C-ACCEPTANCE.md, coordinator gate document.
- Accepted independent proof in handoff/m223/SOL-REVIEW-R5.md, handoff/m224/SOL-REVIEW-R2-ACCEPTANCE.md, handoff/m225/SOL-REVIEW-STAGE-A.md, handoff/m226/SOL-REVIEW-STAGE-A.md, handoff/m227/SOL-REVIEW-STAGE-A.md.
- Read-only source at frozen production SHA: autocut.py, CLI entrypoint and referenced config/contracts as needed.

## Architecture questions to resolve

Q1 / TC1 used_seeds: propose bounded alternative enumeration that does not suppress independently viable overlapping candidate proposals, while final select_global accepted set retains overlap/dedup protections. Define explicit N, visited-key identity, budgets, stable ordering and termination; distinguish candidate pool vs accepted clips.

Q2 / TC2 body opener: propose deterministic policy for an answer-start phrase remaining inside body with start_strict+answer_start+start_morph true. Preserve a legal question-first loop and teaser/hook ordering. Do not claim the M223 body opener was first planned audio (the first planned audio was a hook).

Q3 / TC3 clauses: decide whether clauses can rescue hooks under hook_clauses=true, with optional backward-compatible propose(clauses=...) signature and exact caller forwarding; keep hook_clauses=false baseline. This requires an OWNER semantic choice; provide 2–3 concrete options and a default recommendation, do not assume consent.

Q4 / TC5 duration: define exact post-context_start min_sec validation and reason code, with observed 25→23, no false 25→15 claim. Preserve timing/source references and feature-off behavior.

Q5 / TC7 refers: define integer refers dependency validation after fit_rhythm/remove and before Proposal publication. Address fail-closed alternatives, valid refers and exact negative controls.

Q6 / TC8a/TC8b: protect first-question loop but disallow final question accidentally appended by fit_rhythm. Separately address fix_open_end trims ending to 2.5s then final rhythm_why logs rejection; recovery via legal neighbor is NOT_VERIFIED, not an observed mandatory repair. Provide fail-closed default and OWNER options for post-trim recovery, including boundedness, max_sec/refers/tone checks and replay-proof obligations.

Q7-a / TC9a: replace unsafe suggestion break→continue with a provably terminating bounded alternative-neighbor strategy when overlong nxt is encountered but legal prv exists. Specify worst-case operation bound; no infinite retry.

Q7-b / TC9b: post-loop question removal leaves available answer unvisited. Adding answer is a HYPOTHESIS, not mandated. Provide OWNER options (no extension, conditional payoff-only, bounded always-eligible) and conservative recommendation. Distinguish known helper mechanism from unproven end-to-end media benefit.

Q8 / #11 and M231: define observational counters for #4, #6, #11 (eligible, attempted, rejected reasons, pool, selected, accepted, duration delta). Instrumentation must be additive, deterministic, minimal, synthetic-only, no output/selection behavior changes. The teaser_misses/weak-seed signature changes are explicitly NOT allowed in M231; place them under separately gated M232 or later. Clearly state unknowns and exact M231 acceptance/parity tests.

## Non-negotiable boundaries

- Full user media, real owner transcripts, audio, ffmpeg render, paid APIs, S3 and deployed paths must not be accessed.
- Cloud use remains text-only by the project invariant; no LLM inside state transitions or deterministic selection.
- Manual selection cannot be rescored away. Manifest is the sole contract; new behavior must be feature-gated, OFF = baseline equivalence.
- All negative controls must remain fail-closed and question-first loop protected.
- Do not promote HELPER evidence to proven CLI/render effects.
- No code, tests, config, CI, main, merges, deployment, or broad new diagnostics.
- If the accepted corpus does not justify a proposed mandatory fix, explicitly label the proposed branch HYPOTHESIS/DEFER, and include what synthetic observation would settle it.

## Deliverables — handoff/m230/ only

1. ARCHITECTURE_DECISIONS.md — compact table TC→root mechanism→selected strategy→invariants→future touched symbols→fail-before/pass-after/oracles→dependencies and proof level.
2. OWNER_DECISION_BRIEF.md — exactly Q3/Q6/Q7-b as owner-facing options in Russian, recommended conservative defaults and effects. Do not claim owner approval.
3. IMPLEMENTATION_SEQUENCE.md — M231 observable-only instrumentation design then separately gated M232-A FIX_NOW packages, M232-B conditional post-instrument fixes, QA/CI and stopping conditions; explicit per-path future code permissions remain NONE now.
4. REPORT.md — exact source references, unresolved ARCH_QUESTIONs, OWNER_DECISIONS_PENDING, evidence/provenance matrix, final SHA and readiness for independent Sol architecture QA.

## Mandatory result format

TASK=M230-ARCH-R1
BASE_SHA=3c011e94263e16e5780936b4769d3490cd03b682
INPUT_M229_SHA=74588a219b0d055059f60185f51fd4bcf6efa6b1
FINAL_HANDOFF_SHA=<40-character SHA>
CHANGED_PATHS=<only handoff/m230/...>
PRODUCTION_DIFF=NONE
OWNER_DECISIONS_PENDING=Q3,Q6,Q7-b (unless explicitly answered by owner)
M231_OBSERVABILITY_GO=NO
M232_CODE_GO=NO
READY_FOR_SOL_ARCH_QA=YES/NO
BLOCKERS=<exact evidence/code questions, if any>

One bounded architecture pass. STOP for independent Sol QA and owner semantic decisions. No implementation until explicit next coordinator decision.
