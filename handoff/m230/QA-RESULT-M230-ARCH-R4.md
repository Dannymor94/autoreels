# M230 — independent Sol architecture QA R4 (final)

TASK=M230-ARCH-QA-R4
REVIEWED_HANDOFF_SHA=8ee153a78a5917993842a2e86466b37a5781b54b
FROZEN_PRODUCTION_SHA=3c011e94263e16e5780936b4769d3490cd03b682
VERDICT=PASS_ARCHITECTURE_ONLY
M231_ARCH_READY=YES
M232_A3_A8_ARCH_READY=YES
M231_OBSERVABILITY_GO=NO (at the time of this QA; separate coordinator gate required)
M232_CODE_GO=NO
BLOCKERS=NONE

Independent reviewer: Sol 6.1. Scope was read-only against the frozen source and R3 + normative R4 docs. No source, GitHub or media writes by the reviewer. Future integrated code and OFF parity were **not** executed; no runtime claim is implied.

## Closed at specification level

1. **P1-R3-1 / A3** — `ARCH-R4-CORRECTIONS.md:16–33` requires full semantic start input recomputation after *every* M167/M173 shortening, even with unchanged first ref, including actual following and original-seed/final-played-unit core; rejection before adoption. Frozen source `src/autoreels/cloud/autocut.py:657–673,696–707`, `__main__.py:1159–1183,8966–8991`.
2. **P1-R3-2 / A8** — R4 `:41–43` G2 with `judge=None`, complete played refs filter before any variant-model call; only then unmutating configured judge. No second live-judge `propose`. Frozen `autocut.py:724–742,1208–1222`.
3. **A8 empty legacy pool** — R4 `:48,54` lazy single closure initialization after V1; support fake/no provider and both check modes. Frozen `__main__.py:8860–8896` confirms old guarded setup gap.
4. **P2-R3-1 / model-call budget** — `M231-BUDGET-R4-CORRECTION.md:13–18,24–35,41–44` distinguishes logical operations, application attempts and transport retry. `rank_hooks`, `pick_keywords`, `check_seams` have up to two app attempts per eligible call; `headline` one. Full A3 2+2 bounds, A8 pure G2, post-filter additional judge/polish included.

## Independent deterministic helper execution

The reviewer executed the fetched frozen `autocut.py` **in memory** with fake providers (no repository files, network or paid models written/called):

| Helper | malformed → valid | exception first | malformed → exception |
|---|---:|---:|---:|
| `rank_hooks` | 2 | 1 | 2 |
| `pick_keywords` | 2 | 1 | 2 |
| `check_seams` | 2 | 1 | 2 |

Two R4 budget wording defects discovered during QA were corrected in handoff: `I_keywords=0` only if `n<=0` or no eligible rows; an exception on the second attempt still permits two total application calls. Reviewed blob `420f4c05fdb3bc38500fe7cec12d5379b38e59bc`.

## Limits and future checks

- No integrated A3/A8 runtime exists. Same-first/changed-following, interviewer zero-call, variant-only setup and legacy provider prefix are **future code regression tests**, not observed passes.
- R4 deltas explicitly supersede only conflicting R3 phrases; legacy lifecycle after M112 late redo, short variants and hook stats remains intact.
- For aggregated future model budget, `N` must include **all montage candidates** which enter A3 shortening, including future variants using `_try_accept`; eligible counts should be summed or conservatively maximized.
- Owner decisions Q3/Q6/Q7-b stay pending; conservative O1/V1/Б0 apply.

**Disposition:** Architecture PASS. The coordinator may open **only a separately pinned, explicit** code gate after reviewing this result. M232, merge, deploy, owner media and paid models are not authorized by this QA result.
