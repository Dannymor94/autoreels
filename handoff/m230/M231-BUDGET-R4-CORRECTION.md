# M230-R4 — normative M231 model-budget correction (COORDINATOR)

STATUS=DESIGN_ONLY
FROZEN_PRODUCTION_SHA=3c011e94263e16e5780936b4769d3490cd03b682
SOL_R3_FINDING=P2-R3-1 ACCEPTED
M231_OBSERVABILITY_GO=NO
M232_CODE_GO=NO

This document supersedes only the *model-call budget* §3 of R3 `REPORT.md`, and the conflicting `ARCHITECTURE_DECISIONS.md` §3(5) line “No new LLM call inside propose”. No runtime edits are authorized. The independent R4 reviewer must compare it against the frozen implementation, not merely accept the formulas.

## Accounting units

- A *logical operation* is one check/polish invocation, irrespective of internal retries.
- An *application attempt* is an actual call to `provider.complete`. It is what fake-provider logs count; a logical operation may produce 0, 1 or 2 attempts.
- A *transport attempt* is an SDK/network retry internal to `provider.complete`; multiply the application-attempt bound by the configured provider transport-retry bound **only when that bound is known**. Do not conflate it with application-level retry.
- `r_j ≤ 2` is the maximum application attempts for one `make_judge` verdict. Cached judge results lower realized attempts; cold upper bounds never assume cache hits.

Definitions: `J` = 1 iff `context_start && context_judge`; `S` = seeds reaching `context_start`; `B` = `context_back`; `L` = later context rows; `N` = montage candidates reaching possible CLI shortening; `P` = legacy pool size after interviewer filtering; `C` = requested clips; `K` = `seed_alt_max`; `K_clean ≤ K` = variants actually surviving the full-ref interviewer guard; `A` = accepted for late plate redo; `H` = maximum eligible hook-judge choices (`hook_judge_top` when configured); `I_rank`, `I_title`, `I_keywords`, `I_seam` are 0/1 indicators **per candidate** that the helper is actually called and eligible. `R ≤ K_clean` is accepted variants requiring late plate redo.

## Corrected upper bounds, in application attempts

| Path | Cold upper bound of `provider.complete` calls |
|---|---|
| frozen main + weak-seed `propose` contextual judge | `J * S * 6 * (2+B+L) * r_j` (previous config-dependent bound retained) |
| **A3 after M167/M173** | `J * N * 4 * r_j` (both loops: 2+2 candidate shortenings; even if first ref unchanged, following/core can change) |
| each eligible `_polish(pr)` | `H * r_j + 2*I_rank + I_title + 2*I_keywords`; `H=0` when hook judge disabled; `I_rank=0` when fewer than two hook candidates; `I_keywords=0` when `n<=0` or there are no eligible rows. |
| legacy `check_seams` | `2 * I_seam * min(P, 2*C)` (one operation per checked clip, not per seam pair) |
| M112 late plate rewrite | at most `A` eligible single `headline` calls (configured title/plate mode) |
| A8 G2 **pure build** | **0**: call `propose(..., judge=None)`, materialize complete refs, interviewer-filter before any variant-model call |
| A8 V1b configured judge on a frozen clean shape | `J * K_clean * r_j` (one unmutating start-adjudication per clean variant, subject to policy) |
| A8 Phase V `check_seams` | `2 * I_seam * K_clean` |
| A8 Phase V polish | `≤ K_clean * (H*r_j + 2*I_rank + I_title + 2*I_keywords)` |
| A8 late plate rewrite | at most `R` eligible single `headline` calls |

The bound is deliberately conservative. A `provider.complete` exception returns without a further application attempt in these helpers. Configured `context_judge: false` zeros only judge-related rows; it does **not** zero rank/keywords/seam helpers. Actual call totals require a fake-provider log and config snapshot, not a sum based on the production default alone.

Frozen evidence: `src/autoreels/cloud/autocut.py` `rank_hooks:1436–1458`, `pick_keywords:1534–1547`, `check_seams:1891–1918` each contains a `for _ in range(2)` around `provider.complete`; `headline:1810–1836` contains one call. `src/autoreels/__main__.py:8860–8923` controls legacy polish/seams and optional models.

## QA obligations

1. Fake provider returns malformed JSON on the first application attempt and valid JSON on the second for each of `rank_hooks`, `pick_keywords`, `check_seams`; exact count = 2 per eligible operation. An exception is at most one.
2. Verify baseline main and weak-seed, context-judge-on and -off, hook judge/title/keywords/seams combinations, M112 late redo, and A8 variant-only clean path.
3. Compare literal provider-request sequence with flags OFF; trace ON vs OFF must add **zero** model calls. For A8 flag ON the legacy request log must be an unmodified prefix of the new full request log.
4. Explicitly assert rejected interviewer variants produce **zero** variant-attributed model calls (including the contextual judge); positive clean variants may make bounded extra calls **after** Phase L and V1.
5. No owner media, real model, network, render or production edits. All assertions require independent Sol QA before a scoped gate.

**Status:** Correction prepared by coordinator. No assertion of independent PASS or M231 code GO.
