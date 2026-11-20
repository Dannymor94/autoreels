# TASK: M230-ARCH-QA-R3 — Independent Sol architecture verification

ROLE: Independent Senior QA (Sol 6.1), not the architect or R3 implementer
MODE: READ_ONLY; NO_GITHUB_WRITES; NO_CODE_CHANGES; NO_OWNER_MEDIA; NO_RENDER
REPOSITORY: Dannymor94/autoreels
FROZEN_PRODUCTION_SHA: 3c011e94263e16e5780936b4769d3490cd03b682
R2_ARCH_SHA: d471f35536d270994c8a00805376eeade587f1c3
R3_ARCH_SHA: 231b5dfa110749602cc295906e7bc4a07215ce2e
R3_PARENT_SHA: bfaf8fbd159d4d5f857c7caf801d4987d68a1435
R3_TREE_SHA: 980b928983d702faceef3345067e9b6a2b3b8bf7
R3_ORIGINAL_LOCAL_BUNDLE_SHA: 3cc8421d140e5f8750166917ff21c6cdf2259bbc
M231_OBSERVABILITY_GO=NO
M232_CODE_GO=NO

## Sources

Read from pinned R3_ARCH_SHA, not moving `handoff`:
- `handoff/m230/ARCHITECTURE_DECISIONS.md`
- `handoff/m230/IMPLEMENTATION_SEQUENCE.md`
- `handoff/m230/REPORT.md`
- `handoff/m230/OWNER_DECISION_BRIEF.md` (intentionally unchanged from R2).

Read `handoff/m230/TASK-M230-ARCH-R3.md`, `QA-RESULT-M230-ARCH-R2.md`, `COORDINATOR-AQ-DECISIONS-R2.md` and all prior M230 R1/R2 independent QA context. Read frozen production code at FROZEN_PRODUCTION_SHA plus accepted M223–M229 evidence. Do not treat architect claims as proof. Offline synthetic helper checks / deterministic fake-provider checks are allowed if source access supports them; no owner media/network/render/live model.

## Integrity

- Verify R3_ARCH_SHA is exactly one fast-forward commit after R3_PARENT_SHA, modifying ONLY the three documents named above. R3_TREE_SHA must equal the original bundle tree; published commit SHA differs because the GitHub connector reauthored the publication.
- Expected Git blobs: AD=`74dc993be4b51ee9695b2152a23639b43c46c80d`, IS=`b3f92ce00b4a67c748a92012d28ce85aa99b9588`, REPORT=`c9517f577540807aae0c0d813b5c653b0af9bc14`, OWNER (unchanged)=`938a9cdcadb4f6bbb4b0ec3ad45a4d86dc778930`. No source/config/test changes.

## P1-R2 corrections — independently verify

**A3 M167/M173 post-shortening strict starts (P1-R2-1).**
- Inspect the frozen `_try_accept`, `_drop_last_sentence`, `_drop_sentences`, `context_start` and montage apply. Verify the architecture checks actual FIRST PLAYED sentence (not unit ID) before any mutation of the accepted Proposal and rejects unsafe shortening without a broken side effect.
- Test logic for `pieces=1.1-2 2.1` → M173 drops `1.1`, leaving `1.2=Да, конечно.`; assert unchanged previous candidate/rejection with original check reason. Ensure semantically safe shortening accepted, legal question-first, soft glued-only fallback, missing pymorphy fail-closed, main AND weak-seed montage; scenario path unchanged.
- Check whether adding `Proposal.seed_id` and `core` reconstruct exact rule semantics without changing serialized line, score or legacy code when flag off, and whether callbacks can change judgments.

**A8 interviewer filter (P1-R2-2).**
- Check alternate proposal/descriptor phase against frozen `_other` / `_ivmode=off` legacy pool filter, including missing/sparse speaker metadata. The identical policy must run BEFORE any variant model/polish and must account for filtered fate. Validate `check=False` and `check=True` with fake check. A clean variant must still reach selection.

**A8 phase L complete isolation (P1-R2-3).**
- Verify the revised 16-stage CLI lifecycle against actual frozen code. Phase L MUST include legacy pool filtering, fill_pool sorts, global/greedy, _polish, hookless fallback, M112 plate redo, legacy short variants, all shared _forms and _jstore effects, and final report before ANY variant callback/model call.
- Is G1 merely descriptor collection with no side effects, no candidate ordering/counter mutation, and no calls to `context_start`/judge/keyword callbacks? Is G2 (variant construction) strictly Phase V, with distinct quota/reporting and no retroactive effect on legacy serialized bytes, `M1…Mk` numbering, provider request sequence or manual selection?
- Test/inspect variants ACCEPTED, REJECTED, HOOKLESS deferred and only considered; global/greedy; fill+hookless; shared `_forms`, _counted, plate redo, `_jstore` and short variants. If a legitimate path changes legacy behavior, report exact counterexample with source line.

## P2/M231 spec corrections

- Trace contract: all nine terminal seed exits, deterministic order and exactly one terminal event per seed plus one summary, S0…S6 snapshots including skipped stages=null, passive local state only under trace-enabled branch. Check consistency with allowed source symbols; no new provider or callback/side effects and strict feature-OFF parity test obligation.
- Sparse timings: `ok` / `no_refs` / `no_sentence` / `no_words`, `null` values not zeros, coverage, `d0,d1,err,secs_delta,max_abs,speed_secs` conventions for mixed coverage; no proposal rejection/exception on missing observation. Verify constraints with frozen code.
- Model budget: compare configured J, retries, context_back/context_later, polish, seam calls, M112 late plates and A8 G2/V. Ensure mathematical bounds match reachable loops for nonproduction configurations.

## Inherited contracts and gates

Independently check that the R3 changes do not regress:
- original R1 findings: TC7 established-edge final validator incl. loop question drop; TC2 soft semantic guard and morph; #6 durations affect `@speed`/score/keys, media impact UNKNOWN; TC1 complementary variants held outside full legacy path; TC9b question never appended as answer; TC9a ≤len(units)+2 iterations but O(n²); TC5 25→23; TC8b already `rhythm_out`; TC3 hook clauses under Q3.
- integer refers, legal question-first, no question tail, idempotence, manual selection and no owner/LLM/render in tests.
- No claim that feature-OFF parity or M229 synthetic tests were executed: they remain future acceptance obligations.
- AQ1 additive trace keyword is architecture-approved *in principle*, separate M231 code GO is not granted; AQ2/AQ7/AQ8 only architecture choices. Owner Q3/Q6/Q7-b conservative O1/V1/B0 remain pending. All M232 package gates serial and separately authorized.

## Output

Return PASS_SCOPED / CHANGES_REQUIRED / BLOCKED. Report any P0/P1 with precise R3 document section, frozen-source line, smallest testable counterexample and fix. Clearly distinguish an M231-blocking ambiguity from an M232-A3/A8-only concern. Separate actual verified helper/fake-provider evidence from merely reported evidence. No code/commit/branch/issue/PR writes.

Report in Russian with:

TASK=M230-ARCH-QA-R3
REVIEWED_SHA=231b5dfa110749602cc295906e7bc4a07215ce2e
PRODUCTION_DIFF=NONE/UNVERIFIED
VERDICT=<...>
BLOCKERS=<... or NONE>
P1_R2_DISPOSITIONS=<...>
P2_DISPOSITIONS=<...>
M231_ARCHITECTURE_READY=YES/NO
M232_A3_A8_ARCHITECTURE_READY=YES/NO
OWNER_DECISIONS_PENDING=Q3,Q6,Q7-b
M231_OBSERVABILITY_GO=NO
M232_CODE_GO=NO
READY_FOR_COORDINATOR_DECISION=YES/NO

Stop for coordinator decision; never grant implementation GO.
