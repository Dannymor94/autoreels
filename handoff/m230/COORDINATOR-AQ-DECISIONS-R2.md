# M230 coordinator decision after independent R2 QA

DECISION_ID=M230-COORDINATOR-AQ-R2
R2_ARCH_SHA=d471f35536d270994c8a00805376eeade587f1c3
R2_QA_VERDICT=CHANGES_REQUIRED
QA_EVIDENCE=handoff/m230/QA-RESULT-M230-ARCH-R2.md
PRODUCTION_SHA=3c011e94263e16e5780936b4769d3490cd03b682
PRODUCTION_DIFF=NONE
M231_OBSERVABILITY_GO=NO
M232_CODE_GO=NO

This is a **decision about architecture contracts, not code execution authorization**. The published R2 remains CHANGES_REQUIRED pending R3 architect corrections and independent R3 QA. Any code execution requires a separate exact-SHA, exact-path GO.

## Coordinator decisions

| Question | Decision now | Hard boundary |
|---|---|---|
| **AQ1** `propose(trace=None)` | **APPROVED IN PRINCIPLE** as a final additive keyword, default `None`, with no changes to existing positional callers. For `trace is None`, the prior code path must be byte-identical. | **No M231 GO yet.** R3 must specify deterministic passive snapshot accumulation for exactly one terminal seed event, all S0…S6 and failure exits, missing-timing `null`/coverage, and OFF parity. Independent Sol review required before a separate M231 code gate. |
| **AQ2** flag policy | **One dedicated default-OFF flag per M232 package** (as R2 design). | Exact names and typed config wiring freeze only in each package's separate authorized M232 code gate; never grant blanket authorization for all packages. |
| **AQ7** established-edge asymmetry | **ACCEPTED for architecture**: if both ends coexisted in any S0…S6 snapshot, reject removal of its target while the dependent survives; a never-established edge is not a newly broken edge. | Only under `fix_final_integrity`; preserve question-first and integer `refers`; explicitly test introduced-then-removed loop target and never-established target. This approval does not open A2. |
| **AQ8** post-CLI-shortening recheck | **ACCEPTED for architecture, scoped to montage-origin proposals**, including main and weak-seed montage inputs; the scenario path stays untouched. | Recheck actual played refs after M167/M173; include both A2 final integrity **and A3 semantic start** once enabled. Prevent unsafe shortening or reject; no silent publish. Explicit origin classification and reversible acceptance must be shown before an A2/A3 code GO. |

## Remaining gates

- Three Sol R2 P1 findings must be corrected in the R3 documents: A3 post-shortening semantic start, A8 interviewer-off filter, A8 legacy plate-finalization/provider-order isolation.
- Three P2 design clarifications required before M231 code GO: trace snapshot-local statements/schema, missing timing null/coverage, configuration-dependent model budgets.
- Q3, Q6, Q7-b are **owner decisions** and remain unanswered. Conservative defaults O1 / V1 / B0 remain effective and do not implicitly open A5/A6/A7.
- AQ3 two-phase selector monotonicity is conditional on solving all remaining lifecycle defects; do not mark A8 approved merely due to the earlier fill/hookless correction.
- AQ4 #6 measure remains separate M232-B; AQ5 A/B on owner media remains M237; AQ6 ledger wording is documentation only.

## Release policy

1. Architect R3 docs-only correction.
2. Independent Sol R3 PASS_SCOPED (or repeat correction cycle if CHANGES_REQUIRED).
3. Coordinator issues a separate M231 observability-only GO at a pinned production SHA and exact changed-path allowlist if and only if all required trace proof obligations are satisfied.
4. M232 package gates remain separate, serial, default-OFF and require their own proofs. No owner media/render/live API.

STATUS=M230_ARCHITECTURE_REWORK
NEXT_TASK=M230-ARCH-R3
