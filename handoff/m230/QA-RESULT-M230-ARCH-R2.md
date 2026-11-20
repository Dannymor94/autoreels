# M230-ARCH-QA-R2 — independent Sol result (coordinator capture)

TASK=M230-ARCH-QA-R2
ROLE=INDEPENDENT_SENIOR_QA (Sol 6.1)
REVIEWED_SHA=d471f35536d270994c8a00805376eeade587f1c3
FROZEN_PRODUCTION_SHA=3c011e94263e16e5780936b4769d3490cd03b682
PRODUCTION_DIFF=NONE
VERDICT=CHANGES_REQUIRED
BLOCKERS=P1-R2-1(A3),P1-R2-2(A8),P1-R2-3(A8)
OWNER_DECISIONS_PENDING=Q3,Q6,Q7-b
M231_OBSERVABILITY_GO=NO
M232_CODE_GO=NO
READY_FOR_COORDINATOR_DECISION=YES

This record is a coordinator capture of the completed independent Sol subagent review. The reviewer made no GitHub or source changes, used no owner media/render/live LLM, and checked the frozen source. Do not misrepresent synthetic helper and fake-provider evidence as CLI/media acceptance.

## Integrity

- Published R2 is a one-commit fast-forward from `f037c5ffa2a6816357bf22808bf9f0887a0a124d`.
- Four modified paths only: `handoff/m230/ARCHITECTURE_DECISIONS.md`, `OWNER_DECISION_BRIEF.md`, `IMPLEMENTATION_SEQUENCE.md`, `REPORT.md`; all four blobs exactly match the QA task.
- M229 tests remain `SPECIFIED_NOT_EXECUTED`.

## New P1 findings

### P1-R2-1 — strict body start bypassed after CLI shortening (blocks M232-A3)

- R2 architecture `ARCHITECTURE_DECISIONS.md:80,122–125,197`; `IMPLEMENTATION_SEQUENCE.md:91`.
- Frozen `__main__.py:8984–8991`: M173 removes arbitrary phrases. Frozen `__main__.py:1159–1183`: `_drop_sentences` preserves `Proposal.units`. Frozen montage apply path `__main__.py:6822` skips strict-start checking.
- Independently reproduced with frozen helper: `1.1-2 2.1` shortened to `1.2 2.1` when `1.1` is removed; units remain `[1,2]`. If `1.2` is `Да, конечно.`, `answer_start_reason` rejects it, while A2 final integrity sees neither broken unit edge nor question ending.
- Required: when `fix_body_start` is enabled, revalidate the ACTUAL first played sentence before accepting M167/M173 shortening. If unsafe, keep/reject the shortening without publishing an invalid start. Extend A3 allowlist to appropriate `_try_accept` segment. Add deterministic fake-check CLI test, legal question-first and glued-only fallback controls.

### P1-R2-2 — Phase V skips interviewer=off filter (blocks M232-A8)

- R2 architecture `ARCHITECTURE_DECISIONS.md:164–178`, `IMPLEMENTATION_SEQUENCE.md:96`.
- Frozen `__main__.py:8832–8837` filters montage pool by `_other` and `_ivmode`; Phase V variants bypass this pool. Frozen `_try_accept:8955–8963` does not apply it; with `check=False`, it directly accepts. The apply path `:6817–6838` does not replace this filter.
- Counterexample: `_other={"12.1"}`, `_ivmode="off"`, `variant.pieces="12.1"`, empty accepted, one slot. Phase V accepts an interviewer segment forbidden by legacy.
- Required: same interviewer filter as frozen legacy pool applied to variants before polish; explicit fate for filtered variants; positive/negative tests at `check=False` and fake-check true, without provider.

### P1-R2-3 — Phase V mutates legacy plates via shared forms / late redo (blocks M232-A8)

- R2 architecture `ARCHITECTURE_DECISIONS.md:171–184`, `REPORT.md:41–42`.
- Frozen `__main__.py:8864,8893–8901` uses shared `_forms` for headline/polish; late redo of accepted legacy plates at `:9076–9081` runs after proposed Phase V. `autocut.py:1839–1848` uses forms to change score/choice and mutates legacy Proposal.
- Reviewer reproduced frozen headline with deterministic fake provider (same response in both cases): `_forms=[]` kept original legacy title; `_forms=["statement"]` selected `Почему практика раскрывает потенциал?`. A variant can also change provider call order before legacy redo.
- Required: finish complete legacy finalization including plate redo and legacy short variants BEFORE any variant model/polish calls; finalize only new variants afterwards. Track main-slot versus short-variant capacity. Test legacy serialized bytes and provider-call sequence with flag ON/OFF for accepted, rejected and hookless variants.

## Dispositions of the previous five P1

- R1 P1-1 TC7/TC8a: R2 snapshot/final-integrity specification accepted in its declared established-edge scope; AQ7/AQ8 code-gate choices still required.
- R1 P1-2 TC2 soft: original soft bypass closed, but new P1-R2-1 remains.
- R1 P1-3 #6: duration influences @speed, score, keyword count and verdict; helper speed 1.05→1.08 independently reproduced; actual media effect UNKNOWN.
- R1 P1-4 TC1: fill/hookless ordering improved, but P1-R2-2 and P1-R2-3 invalidate complete legacy isolation.
- R1 P1-5 TC9b: explicit non-question answer and independent question-tail test accepted; B0 until owner decision.

Other confirmations: TC9a at most len(units)+2 iterations with O(n^2) worst-case; TC5 exact 25→23; TC8b already logged to rhythm_out; TC3 owner gate; OFF parity remains a future test obligation, not proven.

## P2 — clarify before M231 code gate

1. `IMPLEMENTATION_SEQUENCE.md:31` allows only append statements, but `:43–51` demands one terminal per-seed event containing S0–S6. Define passive snapshot-local assignments or private stage records and deterministic consolidation, with zero control-flow effect.
2. `IMPLEMENTATION_SEQUENCE.md:54–58` needs missing refs/timing policy: null/status and coverage counts; never turn missing d0/d1, maxima or speed_secs into zero. Frozen `context_start:702–703` can return a clip with no sentence rows. Add negative fixture.
3. `REPORT.md:49–50` model call budget must qualify non-production context judge and plate redo; `context_judge:false` in production does not imply the same bound in every config.

Recommendations: AQ1 additive trace keyword may be approved once schema clarified, still requiring separate M231 GO. AQ7 accept intentionally asymmetric previously-established-edge policy; AQ8 accept montage-only CLI recheck INCLUDING main and weak-seed pools, preserving scenario path.

NO implementation or gate permission is granted by this result.
