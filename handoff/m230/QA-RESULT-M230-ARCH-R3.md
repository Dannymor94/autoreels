# M230 — independent architecture QA R3 (Sol 6.1)

TASK=M230-ARCH-QA-R3
REVIEWED_SHA=231b5dfa110749602cc295906e7bc4a07215ce2e
FROZEN_PRODUCTION_SHA=3c011e94263e16e5780936b4769d3490cd03b682
PRODUCTION_DIFF=NONE
VERDICT=CHANGES_REQUIRED
BLOCKERS=P1-R3-1(A3),P1-R3-2(A8),P2-R3-1(model-budget)
P1_R2_DISPOSITIONS=1:PARTIAL,2:PARTIAL,3:CLOSED_SCOPED
P2_DISPOSITIONS=trace:ACCEPTED_SPEC,sparse_timing:ACCEPTED_SPEC,model_budget:CHANGES_REQUIRED
M231_ARCHITECTURE_READY=NO
M232_A3_A8_ARCHITECTURE_READY=NO
M231_OBSERVABILITY_GO=NO
M232_CODE_GO=NO
OWNER_DECISIONS_PENDING=Q3,Q6,Q7-b

## P1-R3-1: semantic start after CLI shortening

R3's conditional A3 revalidation is too narrow if triggered only by a changed first ref. The predicate `stands_alone(text, following, p, judge, core)` depends on `following`, and M173 can remove an intervening sentence while keeping the first ref. Frozen `_drop_sentences`: `1.1-3 2.1 → 1.1 1.3 2.1`. Under a fake configured judge, old `following=1.2` and new `following=1.3` can disagree.

R4 requirement: revalidate the entire semantic-start input (including following, text, core and judge configuration) after accepted shortening, regardless of unchanged first ref; preserve the original non-mutating rejection and clear stage reason. Regression: same first ref, changed following, judge rejects shortened candidate, no acceptance.

Refs: R3 `ARCHITECTURE_DECISIONS.md` around lines 138/162; frozen `src/autoreels/__main__.py` around lines 1159–1183 and 8980–8991; `src/autoreels/cloud/autocut.py` around lines 657–672, 704–707.

## P1-R3-2: interviewer filter must precede any variant-model call

The proposed A8 filtering was after G2 `propose`. With `context_judge=true`, G2 may call the model before the CLI's `interviewer: off` guard. R4 requirement: apply interviewer guard to the refs actually proposed *before any model-dependent variant operation*, including contextual judge in G2, and recheck after structural mutation. A rejected interviewer candidate must incur exactly zero model calls. Test with fake provider and `interviewer: off; context_judge: true`.

Refs: R3 `ARCHITECTURE_DECISIONS.md` around 192–200 and 229–230; frozen `src/autoreels/cloud/autocut.py` around 669–672, 707 and 1208–1210; CLI `src/autoreels/__main__.py` around 8832–8837.

## P2-R3-1: upper model-call bound undercounted

Three frozen helpers internally call `provider.complete` up to twice on malformed/incomplete model answers: `rank_hooks` (around lines 1436–1458), `pick_keywords` (around 1534–1547), `check_seams` (around 1891–1918) in `src/autoreels/cloud/autocut.py`. In R3 `REPORT.md` §3 each was budgeted as one. Distinguish logical operations, application-level attempts, and provider transport-level retries. Correct baseline: up to 2 application calls per eligible rank, keywords or seam judgement; A8 variant Phase V also doubles seam budget. Apply to all configured optional paths rather than assuming `context_judge: false`.

R3 `ARCHITECTURE_DECISIONS.md` global invariant “No new LLM call inside propose” also conflicts with A8's G2 context judge. Rewrite as “M231 trace adds zero new LLM calls; with A8 flag off the request log is identical, while enabled A8 may generate bounded additional G2 judge requests after guard.”

## Additional scoped architecture gap (A8)

Frozen CLI initializes `_forms`, `_byid_h`, `_polish` / `_plate` only inside `if prov is not None and pool` (around `src/autoreels/__main__.py`: 8860–8896). After interviewer filtering, the legacy pool may become empty even when clean alternative descriptors remain. R4 must initialize variant-only processing independently after the fully completed legacy Phase L, without changing legacy request order or legacy OFF output. Include positive fake-provider test for this case.

## Accepted / not yet proven

- R3 trace design: accepted at spec level (one passive event per seed in seed order, one terminal event, nine exit paths, no callbacks); sparse timing/null/coverage design accepted at spec level.
- R3 A8 two-phase legacy isolation inventory accepted as *scoped specification*, not production parity proof.
- All synthetic findings are QA evidence, not real-media quality results. No audio or render tests run.
- Owner Q3/Q6/Q7-b remain pending, conservative defaults apply.

**Handoff decision:** STOP_FOR_ARCHITECTURE_R4. Do not start M231 or M232 code. R4 documentation must undergo another independent Sol QA; then record separate scoped code GO per package.
