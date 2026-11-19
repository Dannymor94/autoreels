# M229-PREP-R1 — Independent Sol QA

VERDICT: **CHANGES_REQUIRED**  
TASK: M229-PREP-R1  
PRODUCTION_BASE: `3c011e94263e16e5780936b4769d3490cd03b682`  
HANDOFF_REVIEWED: `9fcb8159a217f517c1e141b96ea4c9ebbdc5712d`  
REVIEW_MODE: read-only, documentation/fixture contract review  
PRODUCTION_DIFF: NONE (GitHub comparison of handoff change: four new files only)  
M229_CODE_GO: NO; M230_GO: NO; M231_GO: NO; M232_CODE_GO: NO

## Scope and independent evidence

Reviewed the four files in handoff/m229: REGRESSION_CONTRACTS.md, FIXTURE_CATALOG.md, CALLGRAPH_AND_ARCH_QUESTIONS.md, REPORT.md; compared their causal mechanisms and claims against the accepted independent M223–M227 reviews and source locations at the pinned production baseline. No tests, renders or owner-data exercises were run in this QA; all test blueprints correctly remain SPECIFIED, not EXECUTED. The nine testcase IDs map nine FIX_NOW subcases; this mapping alone is not test adequacy.

## P1 blockers — amend together in one bounded R2

1. **TC-1 / FX-1: used_seeds causal mismatch.** The proposed u2 has a different topic and is not present in the accepted u1 clip. At autocut.py:1262–1264 only accepted clip IDs enter used_seeds/taken, so u2 cannot be marked used by u1. Reconstruct the original M223 bounded competing-candidate fixture: overlapping candidate enumeration is allowed, but final accepted dedup cannot overlap. Do not claim unobserved late rejections. Fix the invalid integer-versus-set negative assertion.
2. **TC-3 / FX-3: unreachable clause branch.** With a sole sentence, hook_teaser=true and hook_teaser_pos=0.5, the candidate at fraction zero is skipped by _hook_cands (autocut.py:1020–1021), before clauses are considered. Replace with an M223-proven multi-sentence candidate or adjust exact control parameters, and show a reachable clause candidate before any caller omission assertions. Keep HELPER versus CLI evidence separate.
3. **TC-7 / FX-7: no refers-bearing item lost.** Current middle is 25 seconds with only five-second gaps, so the documented loss is not triggered by default jump_sec=10; switching to jump_sec=4 still does not make the middle a short piece. Also references should be integer keys, not string "2". Restore M225 Case A timing: first 50–76, middle 90–95, third 160–193 seconds, integer refers=2, production parameter values; establish observed propose helper [1,3] and lost required #2. Do not call this proven final CLI.
4. **TC-8a / FX-8a: inverted question mechanism.** Accepted M225 Case B shows fit_rhythm APPENDS a question after build_passage, making question last. Rebuild fixture (first 50–76, conclusion 90–93, question 94–119) and align TC, call graph and report. Do not conflate with question-first being legitimate as the first selection.
5. **TC-8b / FX-8b: wrong rejection stage and outcome.** Accepted M225 Case C uses fix_open_end to trim the ending to 2.5 seconds, then final rhythm_why rejects below 4.09 seconds with rhythm_out recorded. Current fixture substitutes unrelated fit_rhythm middle-piece deletion and labels a logged failure as silent. Restore accepted posttrim/callback stage; repair-neighbor behavior is NOT_VERIFIED, reserved for M230 decision.
6. **Architecture source lines, graph labels and phase boundary.** Source definitions fix_open_end approximately line 625 and stands_alone approximately line 657, not ~1080/~800; verify exact pinned line numbers and code-level edges. Explicitly represent final validation; mark all unexecuted control-flow edges STATIC, and reserve OBSERVED only for concretely executed paths with citation. TC-9a may not propose naive break→continue without bounded termination and alternative-neighbor strategy, or it risks repeated overlong candidate looping. REPORT currently assigns semantic changes to M231; M231 is strictly observability-only, all behavior changes require separate M232 production gate.

## Secondary contract corrections

- TC-2: preserve legitimate question-first; separate baseline observed failures from prospective pass-after assertions, include exact strict configuration.
- TC-5: align 15 versus 23 seconds and restore accepted M224 observed output/callback/reference timing; do not promote helper observation to rendered playback evidence.
- TC-9b: answer-extension remains a hypothesis, not an authorized production fix.
- Preserve negative controls and feature-off parity; specify real assertable Python conditions, not type-incompatible pseudo-assertions.
- Reconcile exact proof levels for each TC: HELPER, BOUNDED_CLI or STATIC; no synthetic observation may imply final media or owner-data outcomes.

## Disposition and allowed action

CHANGES_REQUIRED is **document-level**, not an observed production regression from this review. Allowed next action: Sonnet M229-PREP-R2, editing only the four existing handoff/m229 docs, no new production code, tests, API, render, owner media, git merge or deployment. R2 must report exact updated SHA, location-level P1 resolution matrix, remaining assumptions and SPECIFIED/NOT_EXECUTED test status. Then independent Sol R2 QA. If R2 cannot fix a missing mechanism from accepted evidence, mark it ARCH_QUESTION rather than fabricate evidence; escalate instead of iterative R3 churn. M230 is held until coordinator explicitly records its release after QA.
