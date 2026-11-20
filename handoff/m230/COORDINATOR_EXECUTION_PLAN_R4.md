# M230-R4 → M231 → M232 — Coordinator execution plan

PLAN_VERSION=2026-11-20-R4
REPO=Dannymor94/autoreels
PRODUCTION_BASE=main@3c011e94263e16e5780936b4769d3490cd03b682
ARCH_R3=231b5dfa110749602cc295906e7bc4a07215ce2e
SOL_R3=CHANGES_REQUIRED
M231_OBSERVABILITY_GO=YES (LIMITED; gate `CODE-GO-M231-LIMITED.md`)
M232_CODE_GO=NO
OWNER_DECISIONS_PENDING=Q3,Q6,Q7-b (conservative O1/V1/B0)

## Outcome of independent R3 audit

- P1-R3-1: A3 post-M173 validation was gated only on changed first ref; `following` can change with first ref unchanged. R4 design correction in `ARCH-R4-CORRECTIONS.md`.
- P1-R3-2: A8 G2 could invoke contextual judge before interviewer:off guard. R4 uses pure G2 with judge=None, then full refs filter, then optional unmutating judge.
- P2-R3-1: budget undercounted repeated `provider.complete` in rank_hooks, pick_keywords, check_seams. R4 fix in `M231-BUDGET-R4-CORRECTION.md`.
- Additional A8 empty legacy-pool closure gap included in R4 design. Trace (9 exits) and sparse timing were accepted at **spec level only**.
- R3 finding/evidence filed at `QA-RESULT-M230-ARCH-R3.md`. No production change.

## Work queue and ownership

| Lane | Ticket | Owner | Scope | Depends on | Status |
|---|---|---|---|---|---|
| 0 | coordinator direct | ChatGPT | Publish Sol R3 result, R4 A3/A8 spec and corrected model budget; create tracked issues/prompts; verify no main changes | frozen source | DONE (docs only) |
| 1 | [#11](https://github.com/Dannymor94/autoreels/issues/11) | Independent Sol 6.1 | Read-only R4 architecture QA, source and fake-provider logic, conflict audit | R4 docs | DONE: PASS_ARCHITECTURE_ONLY at `8ee153a`; issue closed |
| 2 | [#13](https://github.com/Dannymor94/autoreels/issues/13) | Claude Code implementer | M231 passive trace and sparse timing with zero model-call delta | Sol R4 PASS + `CODE-GO-M231-LIMITED.md` (`da8f4d0`) | READY_FOR_LIMITED_IMPLEMENTATION; no code started here |
| 2.5 | [#14](https://github.com/Dannymor94/autoreels/issues/14) | Independent Sol code QA | Reproduce M231 fail-before, OFF/trace parity, sparse timing and source allowlist | executor final SHA, tests and CI handoff | WAITING_FOR_IMPLEMENTATION_SHA |
| 3 | [#12](https://github.com/Dannymor94/autoreels/issues/12) | Claude Code implementer | M232 default-OFF A1, A2, A3, A4, then conditional A5–A7, and A8 separately; one package/code gate at a time | M231 evidence + independent QA + separate GO | BLOCKED |
| 4 | `OWNER_DECISION_BRIEF.md` | Owner | Q3 / Q6 / Q7-b only; O1 / V1 / Б0 until explicit choice | independent M231 signals useful | OPEN; not blocking R4 docs |
| 5 | M237 | Owner / media QA | Real owner-media validation, live models, rendering if separately approved | prior gates + explicit media authorization | NOT AUTHORIZED |

**Parallel rule:** independent QA can review documentation while coordinator prepares prompts, scopes and fixtures. Production implementation packages share `propose` and `cmd_autocut` and must **not** execute in parallel. No two agents edit the same production tree or handoff path concurrently. New feature flags remain default OFF. Architecture review can proceed without owner Q3/Q6/Q7-b; A5/A6/A7 cannot.

## Exit criteria / hard stops

1. **DONE:** Sol returned independent architecture PASS for M231 and A3/A8 R4 design, reviewed handoff SHA `8ee153a`, evidenced in `QA-RESULT-M230-ARCH-R4.md`. This is architecture-only, not integrated code PASS.
2. **DONE for M231 only:** Coordinator published `CODE-GO-M231-LIMITED.md` at `da8f4d0`, with pinned base/source allowlist. **M232_CODE_GO=NO**; every A1–A8 package still needs a separate gate.
3. Implementer on code GO captures fail-before deterministic baseline; OFF golden JSON/review bytes/request log; correct on-flag cases; no owner data/cloud audio/video/render; run offline tests + CI. `STOP_FOR_INDEPENDENT_QA` before merge or next package.
4. If known failure set differs from `handoff/m222/baseline-failures.txt`, production diff escapes allowlist, flag-OFF changes one byte, or any issue requires real media/paid model, STOP and report.
5. Architect should record all source-level assumptions (especially judge retries and `_forms` lazy setup); Sol must not treat agent summaries as evidence.

## English prompts

The exact English QA and implementation prompts are in Issues [#11](https://github.com/Dannymor94/autoreels/issues/11), [#13](https://github.com/Dannymor94/autoreels/issues/13), and [#12](https://github.com/Dannymor94/autoreels/issues/12). They are **staged tasks**: limited M231 code GO is now active under `CODE-GO-M231-LIMITED.md`; all M232 and media NO gates remain authoritative. The coordinator may copy an issue prompt to a subscription CLI agent after its gate opens; no paid API is assumed.

## Current source boundary

- `main`: frozen production at the SHA above.
- `handoff`: documentation-only commits for R3 QA, R4 corrections, owner alternatives and agent prompts.
- No merges, deploys, owner-data reads, generated media or production changes in this coordinator cycle.
