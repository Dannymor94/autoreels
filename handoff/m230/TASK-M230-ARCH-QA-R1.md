# TASK: M230-ARCH-QA-R1 — Independent architecture review

ROLE: Independent Senior QA (Sol 6.1)
MODE: READ_ONLY; no production or handoff modifications
REPO: Dannymor94/autoreels
FROZEN_PRODUCTION_SHA: 3c011e94263e16e5780936b4769d3490cd03b682
ARCH_HANDOFF_SHA: 1cdfbfaa1fb138641ef1687f6be06457b79c346c
ORIGINAL_ARCH_BUNDLE_SHA: d4e192522b887b34767fa17ed2c85476c5d3530e
ORIGINAL_ARCH_TREE_SHA: 8883f3d9237401c6a56b0444beaefe4b89349594
ACCEPTED_M229_SHA: 74588a219b0d055059f60185f51fd4bcf6efa6b1
M231_OBSERVABILITY_GO=NO; M232_CODE_GO=NO

## Inputs

Read all four handoff/m230/ files pinned at ARCH_HANDOFF_SHA:
- ARCHITECTURE_DECISIONS.md
- OWNER_DECISION_BRIEF.md
- IMPLEMENTATION_SEQUENCE.md
- REPORT.md

Read the M230 task and coordinator gate under handoff/m230/TASK-M230-ARCH-R1.md and handoff/m229/COORDINATOR-DECISION-M230-ARCH-GO.md. Reconcile with M228 GATES and findings, accepted M223–M229 independent reviews and test contracts. Verify any code-level semantics read-only at main production SHA, not at handoff branch. Treat every documentation and model claim as untrusted until corroborated.

## Required independent checks

1. **Artifact integrity:** exact published handoff is one fast-forward commit from ff155de08305189d918c80d54672ace79e444539; only the four architecture files added. Original bundle commit differs from published SHA because the connector authored a new commit, but Git tree is 8883f3d9237401c6a56b0444beaefe4b89349594 and file blobs match. No production edits.
2. **Soundness of architecture:** verify the claim of exactly three missing invariant checks inside propose against pinned control flow; identify whether each proposed placement is actually reached and whether late mutation can bypass it. Catch any loss of test coverage.
3. **TC1:** overlapping candidate enumeration vs accepted dedup, precise taken/used_seeds semantics. Critically verify why u2-alone on reduced map need not imply u2-alone on full map; evaluate the suggested one-bounded-suppressed-seed alternative and any preservation risks.
4. **TC2/3/5/7/8a/8b/9a/9b:** compare every claimed defect mechanism, fix location and strategy with accepted Sol scoped evidence; no helper→CLI/render overclaim. Preserve question-first legal loop, caller signature boundaries, refers integer dependency, exact 25→23, posttrim rhythm_out already logged, termination bound <=len(units)+2 for TC9a if substantiated.
5. **#4/#6/#11 and M231:** assess whether #6 only affects duration accounting or could affect another output field; check the code before accepting a no-audio-impact statement. M231 observability-only and synthetic-only; no changes to teaser_misses/weak-seed signatures or selection.
6. **Owner decisions:** Q3 clause hook options, Q6 post-trim recovery, Q7-b answer extension must be labelled OWNER_PENDING, conservative safe defaults explicit, no silent authorization from the architect. Review for hidden coupling to feature-off parity or A/B outcome.
7. **Flag/parity correctness:** proposed flags must preserve exact byte-equivalence of feature-OFF output to pinned baseline, deterministic stage bounds, idempotence, manual selection and manifest invariants. Reject untestable assertions.
8. **Milestone precision:** distinguish M230 arch approval from explicit M231 observational GO, independent Sol M231 PASS, and separate M232 exact-path code GO; tests on M229 are SPECIFIED_NOT_EXECUTED. No owner media/render/paid API.
9. **Evidence and stopping:** 6 ARCH_QUESTIONs in REPORT §5 may remain if non-blocking; explicitly classify required-for-M231 versus required-for-M232, with bounded deterministic synthetic proof plans. Identify every P1 blocker with exact file/line plus minimally sufficient correction.

## Output

Return one of: PASS_SCOPED / CHANGES_REQUIRED / BLOCKED.

TASK=M230-ARCH-QA-R1
REVIEWED_SHA=1cdfbfaa1fb138641ef1687f6be06457b79c346c
PRODUCTION_DIFF=NONE/UNVERIFIED
VERDICT=<...>
BLOCKERS=<P0/P1 with exact location or NONE>
OWNER_DECISIONS_PENDING=Q3,Q6,Q7-b
M231_OBSERVABILITY_GO=NO
M232_CODE_GO=NO
READY_FOR_COORDINATOR_DECISION=YES/NO

Do not write code, tests, docs, commits, branches, issues or PRs. Do not use owner data or run any render. Report in Russian with evidence and a concise disposition.
