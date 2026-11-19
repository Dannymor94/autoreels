# M229-PREP-R2 — Independent Sol 6.1 QA

VERDICT: **CHANGES_REQUIRED**  
PRODUCTION_BASE_SHA: `3c011e94263e16e5780936b4769d3490cd03b682`  
REVIEWED_HANDOFF_SHA: `37dbf7579c82c699e8a10984a0801a7873fec432`  
HANDOFF_PARENT_SHA: `5309093f0f35853dc7ea8bda578aa78dca2b4a04`  
MODE: read-only; documentation/fixture evidence QA; no new runs  
TEST_STATUS: SPECIFIED_NOT_EXECUTED; PRODUCTION_DIFF=NONE  
M230_GO=NO; M231_GO=NO; M232_CODE_GO=NO

## Verified

GitHub compare shows one commit modifying only the four existing handoff/m229 documents. P1-A/B core fixture fixes are coherent; primary TC7/FX7, TC8a/FX8a, TC8b/FX8b mechanisms significantly improved. No valid evidence was provided for final rendered/media outcomes; helper/CLI/static separation mostly preserved. TC9a bounded termination remains ARCH_QUESTION and TC9b answer extension remains an unapproved hypothesis.

## Remaining blockers in R2

1. **Stale TC8 mapping alters future fix target.** REPORT.md lines 37–38, 56–57, 108 and REGRESSION_CONTRACTS.md lines 210–211 still claim TC8a = build_passage post-loop pop and TC8b = fit_rhythm silent removal. Actual accepted M225: TC8a fit_rhythm appends question after build_passage; TC8b fix_open_end trim to 2.5s followed by logged final rhythm_why rejection in rhythm_out.
2. **Incorrect implementation gate.** REPORT.md:129 says owner decisions block implementation in M231. M231 is observability-only; all semantic fixes require M230 architecture approval, independent M231 Sol PASS and separately granted M232 code GO.
3. **TC5 internal contradiction.** REGRESSION_CONTRACTS.md:91 describes 25→15 (10s drop); line 92 and accepted M224 prove 25→23 (2s drop), already correctly represented in FIXTURE_CATALOG.md:159,167–179.
4. **TC2 proof inflation and assertion reversal.** REGRESSION_CONTRACTS.md:51 calls body opener first planned audible sound; accepted M223 SOL-REVIEW-R5 establishes first hook 2.1 (teaser) or 1.2 (no-teaser), with answer-start body 1.1 retained but not first. FIXTURE_CATALOG.md:97–103 places prospective pass-after rejection under fail-before. State exact start_strict, answer_start, start_morph flags and mark new fixture unexecuted.
5. **Arch semantic mismatch.** CALLGRAPH_AND_ARCH_QUESTIONS.md:169 describes refers as string `"2"` while accepted M225 TC7 uses integer ID 2; lines 178–181 discuss silent fit_rhythm removal under Q6/#8b when actual Case C is fix_open_end trim → rhythm_why reject.

## Disposition

These contradictions are material to architecture/test implementation despite mostly correct central fixtures. A single coordinator-owned, line-targeted documentation alignment may close them without commissioning another broad Sonnet R3. Such editorial alignment must be independently rechecked at its exact resulting SHA. No production changes, owner-data or render. Keep M230/M231/M232 on HOLD until a scoped Sol acceptance and explicit coordinator phase authorization.
