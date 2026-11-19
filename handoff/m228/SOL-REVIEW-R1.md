# M228 · Independent Sol 6.1 review, round 1

**VERDICT: CHANGES_REQUIRED** · 2026-11-19

- `BASE_SHA=3c011e94263e16e5780936b4769d3490cd03b682`
- `REVIEWED_HANDOFF_SHA=44086710a04af83ccbef41b8c491096349003e5a`
- `PRODUCTION_DIFF=NONE`
- `M229_CODE_GO=NO`, `RENDER_GO=NO`, `PAID_API_GO=NO`
- `NEXT=M228-R2 documentation-only correction`; M223–M227 accepted evidence is frozen.

Independent Sol read all four deliverables, `TASK-M228-R1.md`, accepted Sol M223–M227 reviews, and inspected pinned production source. No files changed and no reruns of settled diagnostic campaigns.

## P1 — Required corrections before PASS_SCOPED

1. **Proof promotion.** `GATES.md:13` claims 7 FIX_NOW findings have CLI_HELPER_BOUNDARY or stronger evidence. Accepted M225/M226 scope for #7/#8/#9 is **HELPER only**. Four parent IDs #1/#2/#3/#5 have bounded CLI/boundary evidence; three #7/#8/#9 remain HELPER. Repair claim without changing accepted evidence.
2. **Unresolvable gate contradiction.** `GATES.md:20,30–32` and `REPORT.md:97,101` disallow any `propose` modification before M230 architectural review, yet M229 assigns #1/#2/#8a whose implementation can change `propose` body (source `autocut.py:1175,1262–1264`). Disallowing only signature changes is insufficient. Choose one sequence unambiguously: move architecture review **before** any `propose` implementation; or move such findings to post-review scope. Add explicit recorded coordinator GO after independent Sol acceptance; a Sol PASS alone is not code authority.
3. **#1 design does not address observed suppression.** `ARCHITECTURE.md:33` retains `used_seeds -> continue`. The test `u2 appears in pool while u1 taken` in `FINDINGS.md:13/GATES.md:35` can violate intended overlap exclusion and does not demonstrate later downstream rejection. Specify bounded non-destructive alternative enumeration/reconsideration, stable IDs, dedup/final overlap, safe stop conditions, and a minimum regression contract. Maintain the scoped observation: downstream rejection NOT_REPRODUCED.
4. **Instrumentation vs mutation.** `ARCHITECTURE.md:133–134,163` proposes weak-seed callback wiring and post-select fallback as if part of observability #11/M231. `GATES.md:68` declares M231 observation only, M232 owns subsequent behavior fixes. Separate counters/reasons from selection/acceptance changes, and log alignment deltas without rejection during observational mode.
5. **Unsupported behavior invariant and premature contracts.** `ARCHITECTURE.md:49` prohibits a question as first unit; baseline `propose` intentionally supports question-led loops (`autocut.py:1183,1270,1298`). Remove blanket prohibition. `ARCHITECTURE.md:43–44` prescribes unconditional answer extension and changing `build_passage` to a tuple before decision; keep both bounded proposals behind architecture/compatibility gates.
6. **Owner media access gate.** `GATES.md:67,69` demands run on real owner video/logs despite exclusion of owner data and rendering in current GO. M231 initial validation must use synthetic/no-side-effect fixtures; any later real owner media or log use requires separate explicit owner authorization and privacy scope.

## R2 contract / required clarity

- `FINDINGS.md` must contain exactly **12 parent rows #1–#12**; nest #8a/b and #9a/b within their parent rows or an explicitly separate subcase table. The calculation is consistent if units are declared: **12 parents, 14 subcases; 7 FIX_NOW parents / 9 FIX_NOW subcases, 3 INSTRUMENT_FIRST, 2 NO_FIX**.
- #12 is **NOT_RUNTIME_PROVEN / DEFER** rather than `INTENTIONAL` order sensitivity. #10 budget six is the actual intentional limit.
- Regression tests: existing baseline suite PASS; new defect-focused regression FAIL-before / PASS-after. Expected fail-closed negatives are successful tests, not reasons to revert.
- `FINDINGS.md:21` does not prove a legal repair neighbor for #8b; reject with logged reason when repair not proven. Rename #4 to selector comparison only; late rejection never reproduced.
- The source/archive provenance, proof levels and artifact hashes must remain unchanged. Do not rerun M223–M227 or expand to user media.

## Pinned Git blobs

| Path | Blob SHA |
|---|---|
| `handoff/m228/FINDINGS.md` | `c4574b328d4d1e2004902e9e5c8f84db4ab98721` |
| `handoff/m228/ARCHITECTURE.md` | `37331b53b5f7f30ccd160ff4f716c3e1aaa205f2` |
| `handoff/m228/GATES.md` | `256fcd0180011487d8d9e0443838923266ecbcaf` |
| `handoff/m228/REPORT.md` | `a1533574af03cafe71938b4678ef1b8cde757886` |
| `handoff/m228/TASK-M228-R1.md` | `dcbc5d3ef6690694fb2b424684d4fb4a62b268a6` |

Verification: read-only `git show <sha>:<path>`, `git ls-tree <sha> <path>`, `git diff-tree --no-commit-id --name-only -r <sha>`. The reviewed commit changed exactly these four Markdown deliverables. The orphan `handoff` branch is **not** production main and must not be whole-tree-compared against main as evidence of deleted source.

**GATE=CHANGES_REQUIRED**  
**SCOPE=M228 documentation and future implementation authorization only; production unchanged**  
**NEW_FINDINGS=P1 proof-level promotion, contradictory M229/M230 permission, unresolved #1 architecture, instrumentation-vs-mutation, question-loop regression, owner-data gate**  
**NEXT=M228-R2 targeted docs correction, then independent Sol review**  
**STOP_REPEATING=M223-M227 yes; M228 max bounded R2**
