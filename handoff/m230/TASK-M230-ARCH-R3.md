# TASK: M230-ARCH-R3 — Fix independent Sol R2 findings and M231 specification gaps

ROLE: Claude Opus, M230 architect
MODE: ARCHITECTURE_DOCS_ONLY; NO_CODE; NO_TEST_EXECUTION; NO_RENDER
REPO: Dannymor94/autoreels
FROZEN_PRODUCTION_SHA: 3c011e94263e16e5780936b4769d3490cd03b682
REVIEWED_R2_ARCH_SHA: d471f35536d270994c8a00805376eeade587f1c3
QA_R2_RESULT: CHANGES_REQUIRED (three new P1)
BASE_HANDOFF: current tip containing this task and the coordinator decision
M231_OBSERVABILITY_GO=NO
M232_CODE_GO=NO
OWNER_DECISIONS_PENDING=Q3,Q6,Q7-b (defaults O1/V1/B0)

## First read

- All four R2 architecture files at REVIEWED_R2_ARCH_SHA.
- `handoff/m230/QA-RESULT-M230-ARCH-R2.md` — full independent Sol R2 findings.
- `handoff/m230/COORDINATOR-AQ-DECISIONS-R2.md` — binding coordinator decisions on AQ1, AQ2, AQ7, AQ8. These are architecture choices, NOT code GO.
- M228 accepted evidence and M229 `SPECIFIED_NOT_EXECUTED` contracts.
- Actual frozen production source at FROZEN_PRODUCTION_SHA. Verify all proposed control-flow claims independently. Report if a finding is not reproducible; do not silently dismiss Sol.

## Mandatory P1 architecture changes

**P1-R2-1 / M232 A3 — body start becomes invalid after CLI shortening.**

`_drop_sentences` in `__main__.py:1159–1183` preserves `Proposal.units` but M173 at `:8984–8991` can remove the first played sentence; montage apply at `:6822` does not re-check strict body start. Sol reproduced `1.1-2 2.1 → 1.2 2.1` when `1.2` is `Да, конечно.`, violating `answer_start_reason`.

Specify an A3 flag-gated, fail-closed revalidation of the **actual first played sentence** before accepting M167/M173 shortened proposals. Re-use the exact semantic predicate of `context_start` with the same question-first exemption and morph dependency. Be precise about whether to skip a shortening, use the previous valid proposal, or fail the candidate when the new start is invalid; preserve deterministic bounded retry loops and legacy behavior with flag OFF. Extend A3 future changed-symbol allowlist to the relevant `_try_accept` slice. Synthetic fake-check CLI controls: invalid first played sentence after M173, valid shortening, valid first question, missing morph, valid timing-only soft fallback. Include both montage-origin main and weak-seed candidates.

**P1-R2-2 / M232 A8 — variants bypass interviewer-off guard.**

Frozen `__main__.py:8832–8837` filters legacy montage pool by `_other` and `_ivmode`; Phase V variants held outside that pool skip this filter. `_try_accept` cannot repair it. Explicitly apply the *same* interviewer-off policy to Phase V candidates before ANY polish/model calls; decide how filtering is reported in deterministic variant fate without changing the legacy report and OFF path. Tests: variant containing `12.1`, `_other={"12.1"}`, `_ivmode="off"`, free slot, for `check=False` and fake-check `True`; a clean variant must still pass.

**P1-R2-3 / M232 A8 — complete legacy finalization before Phase V.**

R2's Phase V was placed before late plate redo at `__main__.py:9076–9081`. The shared `_forms` at `:8864`, headline/polish at `:8893–8901`, and `autocut.py:1839–1848` allow variant polish to change existing legacy titles or consume provider responses before legacy redo.

Define a full Phase L boundary that includes legacy primary accept, hookless fallback, late plate redo, and legacy short-variant postprocessing BEFORE ANY variant provider/polish operation. Specify Phase V as a distinct continuation limited to remaining *main* slots, with separate forms/counters/reporting if necessary, and variant-only finalization. Preserve all serialized fields and the exact fake-provider request order of legacy accepted items ON vs OFF, even if variants are accepted, rejected, hookless deferred or only considered. Explicitly account for the `_forms` shared-state hazard and all operations after `:9081`. Do not assert monotonicity until the entire CLI lifecycle has been inventoried. Add negative fake-provider fixture and bytewise legacy-output comparisons in both greedy/global and fill/hookless cases.

## Mandatory M231 P2 spec clarifications

**Trace accumulation:** R2 `IMPLEMENTATION_SEQUENCE.md:31` limits changes to `trace.append()`, but `:43–51` requires terminal per-seed events containing S0…S6. Clarify permitted *passive* local snapshot variables/assignments plus deterministic terminal assembly, or private per-stage events with deterministic consolidation. Exact event count, ordering, missing stages, no side effects, no new provider call, no output changes when trace is absent. Reflect revised permitted symbols and negative/ON/OFF tests.

**Missing timing:** R2 `IMPLEMENTATION_SEQUENCE.md:54–58` fails to cover missing refs/sentences/word-times. Define availability, `null` fields, reason status, coverage counters, and per-boundary d0/d1/err/max/speed_secs semantics when observations are incomplete. Never coerce unknown to zero; never throw or suppress a legacy proposal solely because trace lacks timings. Add sparse/empty-sentences synthetic negative fixture. Keep the conservative evidence level.

**Model-call bound:** R2 `REPORT.md:49–50` omits context judge and plate-redo costs. State bounds parameterized by configuration and bounded iteration counts; production `context_judge:false` is just one configuration, not a universal guarantee.

## Requirements and stopping conditions

- Revise exactly the four existing files: `handoff/m230/ARCHITECTURE_DECISIONS.md`, `IMPLEMENTATION_SEQUENCE.md`, `OWNER_DECISION_BRIEF.md` (only if needed), `REPORT.md`. Preserve previous R1/R2 notes as provenance.
- Include a disposition table for each three P1 and each three P2, with frozen path/line, exact claimed invariant, future allowlist, fail-before/pass-after/negative/OFF oracles, and scope of proof. Reconcile all four files; no contradicted stage order or code GO.
- Keep R2 fixes: established-edge final validator incl. loop drop; strict predicate incl. soft/morph; speed @speed/score/k influence and d0/d1; two-phase TC1; TC9b question guard; TC9a O(n^2) with len(units)+2 iteration bound; TC5 25→23; TC8b rhythm_out, legal question-first, integer refers.
- Feature-OFF byte parity is a future test obligation only. M229 remains `SPECIFIED_NOT_EXECUTED`. No owner data, render, paid models/network, source/config/test modifications.
- Scope every change to future independent M231 and serial M232 gates. Coordinator AQ1 additive `propose(trace=None)` APPROVED IN PRINCIPLE but M231 code GO=NO. AQ2 one default-OFF flag per M232 package. AQ7 and AQ8 architecture contracts accepted with conditions from coordinator file. Q3/Q6/Q7-b remain owner decisions, conservative defaults O1/V1/B0. A5/A6/A7 not opened.
- If an implementation needs a new source path outside the approved future allowlist, document a new explicit gate; do not assume authorization.
- Publish the docs to `handoff` by ordinary fast-forward only if authorized. If push denied, supply four complete documents and a validated `git bundle` with exact parent SHA, tree SHA and commit SHA; no force push.

## Required handoff

TASK=M230-ARCH-R3
BASE_ARCH_SHA=d471f35536d270994c8a00805376eeade587f1c3
BASE_HANDOFF_SHA=<full SHA of this task's commit>
FINAL_HANDOFF_SHA=<full SHA or LOCAL_UNPUBLISHED>
CHANGED_PATHS=<exact four docs>
PRODUCTION_DIFF=NONE
P1_R2_DISPOSITIONS=<P1-R2-1,2,3>
P2_DISPOSITIONS=<trace,missing_timing,model_budget>
OWNER_DECISIONS_PENDING=Q3,Q6,Q7-b
M231_OBSERVABILITY_GO=NO
M232_CODE_GO=NO
READY_FOR_SOL_ARCH_QA_R3=YES/NO
BLOCKERS=<...>

Do not begin M231/M232 implementation or declare Sol PASS. Stop for independent Sol R3 review.
