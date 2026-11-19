# TASK: M230-ARCH-R2 — Address all independent Sol R1 P1 findings

ROLE: Claude Opus — independent architect (the M230-R1 author)
MODE: ARCHITECTURE_DOCS_ONLY; NO_CODE; NO_TEST_EXECUTION; NO_RENDER
REPOSITORY: Dannymor94/autoreels
FROZEN_PRODUCTION_SHA: 3c011e94263e16e5780936b4769d3490cd03b682
REVIEWED_ARCH_SHA: 1cdfbfaa1fb138641ef1687f6be06457b79c346c
QA_RESULT: M230-ARCH-QA-R1 = CHANGES_REQUIRED (5 P1)
GATES: M231_OBSERVABILITY_GO=NO; M232_CODE_GO=NO
OWNER_DECISIONS_PENDING: Q3, Q6, Q7-b (defaults O1 / V1 / B0)
TARGET_BRANCH: handoff (additive docs correction; preserve R1 provenance)

## Objective

Revise the M230 architecture so that every claimed invariant is true on every reachable frozen-code path, independently testable, and safely flag-gated. Respond to all five Sol P1 findings and the complexity correction. Do not implement fixes, run the pipeline or use owner media.

Start by reading the four R1 files under `handoff/m230/` at REVIEWED_ARCH_SHA:
- ARCHITECTURE_DECISIONS.md
- OWNER_DECISION_BRIEF.md
- IMPLEMENTATION_SEQUENCE.md
- REPORT.md

Read `handoff/m230/TASK-M230-ARCH-QA-R1.md`, accepted M223–M229 evidence, and actual source pinned to FROZEN_PRODUCTION_SHA. The descriptions below are reported QA findings; independently trace each path before choosing a correction. Do not upgrade HELPER/STATIC/CLI evidence to media or production evidence.

## Mandatory P1 corrections

**P1-1 · TC7: final dependency integrity must be checked after all transformations.**
- `context_start` can drop the loop question in `autocut.py:763` through `u.id == loop_id`, bypassing `needed`. This happens AFTER the proposed `fit_rhythm` post-check at `:1206`. Sol reproduced a remaining dependent `#11.refers=10` after dropping question `#10`.
- Update the transform inventory and remove/qualify the "exactly three gaps" statement. Define an explicit FINAL pre-publication invariant check after `context_start`, `fix_open_end`, final rhythm, and any later structural mutation. The dependency predicate must preserve integer refers semantics, distinguish originally absent edges from edges broken by a transform, and detect a lost loop-question dependency. State the failure channel/reason and which dedicated flag gates it.
- Retain the earlier rhythm-local check only if its added diagnostic value justifies it; it cannot be the only guard.
- Required synthetic negative: removed loop-question still referred to by a kept unit; required negative control: valid question-first loop survives.

**P1-2 · TC2: soft fallback can bypass strict rejection.**
- `context_start:711` caches `soft` when `_alone is None`, then `:768–772` can return that cached clip even if a newly strict-invalid start remains.
- Define one composable semantic start predicate used by normal acceptance, repairs, and soft capture/return. `soft` may relax ONLY glued timing, never `strict_start_reason`, `answer_start_reason`, or `start_morph`. If no valid repair exists, return `no_start` with cause; do not silently publish a semantic-invalid start.
- Preserve question-first exemption precisely. Ensure `require_morph()` is enforced before early returns when `start_strict && start_morph`, matching scenario.py:197–199.
- Required negative: glued + strict-invalid + no repair; missing pymorphy3 fail-closed; valid glued but semantically acceptable soft fallback; legal question-first loop.

**P1-3 · #6: duration can affect serialized output, not only bookkeeping.**
- `_speed(clip,p)` uses `_dur` at `autocut.py:1133` and `Proposal.line()` emits `@speed`. Sol's synthetic HELPER case changed speed 1.05→1.08 by changing one duration 0.4s; duration also affects score and rule-keyword count.
- Retract claims that playback effect is "unreachable" or that #6 is "only seconds bookkeeping"/"no audio impact". Distinguish (a) proven code-level output influence, (b) unknown real-media playback effect.
- Revise M231 metrics to include **per-boundary** t0 and t1 deltas (or equivalent explicitly defined offsets) alongside secs_delta. Explain how equal/opposite boundary errors may yield secs_delta=0. Preserve only-observe semantics, no new signatures outside the approved trace keyword, and no hidden production behavior changes.
- Update all contradictory claims in ARCHITECTURE_DECISIONS, IMPLEMENTATION_SEQUENCE, REPORT (and owner brief if applicable).

**P1-4 · TC1: variant tail ordering fails with fill_pool and hookless fallback.**
- `fill_pool` re-sorts candidates by score (`autocut.py:1325`), and `__main__.py:9065` runs a second acceptance pass over deferred hookless candidates. A variant with hook can be accepted before a legacy hookless candidate even when variants were sorted last, changing legacy decisions.
- Specify the complete selection lifecycle, including `out.sort`, `fill_pool`, every CLI pool sort, global/exact selection, late `_polish`, primary accept, `hookless_last` deferred accept, and `_try_accept`.
- Preferred bounded semantics: complete the legacy selection (including hookless fallback) before admitting variants to remaining slots, with explicit dedup/conflict rules; if infeasible, explicitly withdraw the legacy-monotonicity guarantee and re-gate the behavioral choice. Do not claim preservation on unverified paths.
- Required negative: `fill_pool` + `hookless_last=true`, 1 available slot, legacy hookless candidate versus conflicting hooked variant; verify legacy acceptance unchanged with feature on/off in both greedy and global modes. Include pool-size >30 limits and M231 observability prerequisite.

**P1-5 · TC9b: eligible() may admit another question as the "answer".**
- `eligible()` does not exclude `role="question"`. For owner-conditional B2, explicitly reject question-as-answer and independently check the final role is not question EVEN IF the rhythm flag is OFF.
- Required negative: two consecutive questions; positive: one eligible non-question answer within gap/time limits; no more than one extension.
- Until owner chooses, B0/no extension remains the behavior. Do not open this implementation package.

## Additional required corrections

- TC9a: keep the sound bound of at most `len(units)+2` iterations, but remove/qualify claimed O(n). Recomputing jumps and copying `run` can make time O(n^2).
- Maintain precise TC8b diagnosis (already logged `rhythm_out` after trim), TC5 25→23, integer refers, question-first negative, no changes to TC3/TC5/TC8a semantics without an explicit rationale.
- Update M231 event schema and acceptance tests for final dependency integrity where applicable, t0/t1 boundary metrics and trace signature approval. Explicitly decide/mark coordinator-pending the six ARCH_QUESTIONs according to when they block M231 vs M232 vs M237.
- All M232 packages must remain default-OFF with frozen-output byte-parity, no LLM/network/owner data, committed synthetic fixtures and fail-before/pass-after/negative proof plans.
- Respect a future separate M231 GO and future separate M232 code GO. Q3/Q6/Q7-b remain owner-pending: no silent default change.

## Deliverables and review process

1. Make a **docs-only R2** revision of the same four `handoff/m230/` documents. Prefer minimal, internally consistent corrections; identify all changed statements and why. No production code, tests, config, or other paths.
2. Publish to `handoff` only if your environment has ordinary write access; if blocked, produce a git bundle fast-forwarding the exact verified handoff base, plus attach the four complete documents. Never force-push.
3. In REPORT add an explicit P1-1…P1-5 disposition table, revised complexity, exact `BASE_ARCH_SHA`, `FINAL_HANDOFF_SHA` or local pending SHA, changed paths, proof status and how off-parity remains testable rather than already proven.
4. Stop for **independent Sol R2 QA**. Do not self-declare QA PASS or authorize M231/M232.

Return:

TASK=M230-ARCH-R2
BASE_ARCH_SHA=1cdfbfaa1fb138641ef1687f6be06457b79c346c
FINAL_HANDOFF_SHA=<full SHA or LOCAL_UNPUBLISHED>
PRODUCTION_DIFF=NONE
P1_DISPOSITIONS=P1-1..P1-5
OWNER_DECISIONS_PENDING=Q3,Q6,Q7-b
M231_OBSERVABILITY_GO=NO
M232_CODE_GO=NO
READY_FOR_SOL_ARCH_QA=YES/NO
BLOCKERS=<...>
