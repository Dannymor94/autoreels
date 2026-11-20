# M231 — Limited Code GO (coordinator; post Sol R4 PASS)

TASK=M231-OBSERVABILITY-IMPLEMENTATION
DECISION=M231_LIMITED_CODE_GO
ISSUED_DATE=2026-11-20
BASE_PRODUCTION_SHA=3c011e94263e16e5780936b4769d3490cd03b682
ARCH_QA_R4_SHA=8ee153a78a5917993842a2e86466b37a5781b54b
ARCH_QA_RESULT=PASS_ARCHITECTURE_ONLY
DESIGN_REFS=handoff/m230/IMPLEMENTATION_SEQUENCE.md §M231; handoff/m230/ARCHITECTURE_DECISIONS.md §M231; handoff/m230/ARCH-R4-CORRECTIONS.md; handoff/m230/M231-BUDGET-R4-CORRECTION.md
M231_OBSERVABILITY_GO=YES (LIMITED, CODE ONLY)
M232_CODE_GO=NO
M237_MEDIA_GO=NO
MERGE_GO=NO

The prior M231=NO gate is superseded **only for implementation of passive M231 observability** by this explicit, scope-pinned coordinator decision following independent Sol R4 architecture PASS. It does not assert implemented behavior, performance or media results and does not approve anything in M232. Owner Q3/Q6/Q7-b are not prerequisites for passive trace; conservative O1/V1/Б0 still apply.

## Exact edit allowlist

1. `src/autoreels/cloud/autocut.py`: `propose` signature adds only trailing optional `trace: list | None = None`; guarded local `_tr` fields/assignments reading existing locals without callback/new branches outside guards; exactly one `trace.append` per seed terminal path (nine exits) plus one final truncate event. Do not modify selection, scoring, context, safety predicates, I/O or any other `autocut.py` symbol.
2. `src/autoreels/__main__.py`: `cmd_autocut` main-call opt-in via `ARL_AUTOCUT_TRACE` only; passive, deterministic post-run enrichment from existing `sent_by_ref`; CLI select/fate events; JSONL deterministic encoding. No weak-seed trace, no scenario change, no additional stdout/stderr when env unset.
3. `tests/test_m231_trace.py`, `tests/fixtures/m231/**`: deterministic fake fixtures and regression tests. All output paths must be `tmp_path` in tests; no network, paid model, owner media, render or source file writes.
4. `handoff/m231/**`: new report, tests/log references and evidence only; may create this folder. Do not modify `handoff/m230/**` during code task.

**Excluded:** configuration and Pydantic Manifest schema, `teaser_misses`, `_hook_cands`, `build_passage`, `fit_rhythm`, `context_start`, `scenario.py`, CLI shared cache/publish/apply paths, M232 flags, any owner data.

## Mandatory verifications

- Baseline recorded **before** patch on exact base SHA; committed deterministic golden fixture/review hashes from frozen base, not generated after the change. Compare known failure set using `handoff/m222/baseline-failures.txt` and `compare_failures.py`.
- OFF parity: trace None vs [] Proposal objects equal; with env unset vs set review draft SHA, stdout/stderr and fake-provider request logs identical. No altered counts/arguments for `sentences`, `end_tone`, `judge`, `taste` callbacks.
- Exactly `|seeds|+1` per-call records in seed order (one per all nine terminal exits; final truncate); FX-T0 sparse timing `null` rather than 0 and coverage counts; independent `d0/d1` with same-shift `d0=d1=0.4` and aggregate error 0; repeat traces byte-identical.
- Preserve all existing tests and offline CI; test under explicit hash seeds 0/42/1337 when the project has that harness. Zero owner media, live model, S3 or local render.
- Report base/final SHA, branch, diffstat, exact tests and CI jobs, fixtures, all baseline failures, and protected path parity. **STOP_FOR_INDEPENDENT_SOL_CODE_QA**. Do not merge, deploy or open M232 code.

## Stop conditions

If baseline SHA changed, allowlist expansion is required, traces alter any OFF byte/request/callback, error set drifts, a callback is called during passive trace, nondeterministic output appears, user media/paid models are required, or CI cannot be run: **STOP**, do not claim PASS, ask coordinator for a new gate.

Authorized executor: code-capable Claude Code/Codex CLI agent in a dedicated task branch based on the pinned main SHA. The coordinator may execute only when the same tests and branch isolation can be run safely. The user performs final merge after independent PASS.
