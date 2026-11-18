# TASK M223-R2 — Complete missing production CLI proof

Assigned: Claude Code Sonnet 4.6. Reviewer: independent Sol 6.1.
Language: TASK English; REPORT and owner communication Russian.
Status: READY FOR REWORK. M224 is BLOCKED until Sol PASS.

## Authoritative evidence

- Production base: `3c011e94263e16e5780936b4769d3490cd03b682` (recheck current main SHA before executing).
- Previous handoff: `2925a9b582c205fed94321602f7d4b5431158197`.
- Read `CLAUDE.md`, `handoff/m223/TASK-M223.md`, `handoff/m223/TASK-M223-R1.md`, `handoff/m223/SOL-REVIEW-R1.md`, `handoff/m223/SOL-REVIEW-R2.md`, `handoff/m223/CLI_REPRO.py`, `handoff/m223/REPORT.md`.
- Preserve the already independently verified real `cmd_autocut` entry, config construction, transparent `propose` spy, synthetic temp root, and top-level mismatch fail-closed behavior. Do not redo settled M222A or M223-R0 work.

## Scope and safety

Proof-only, no production `autocut.py`, `__main__.py`, `config/r0.yaml` edits. No paid APIs, LLM, full video render, or writes to real owner artifacts. Use isolated synthetic temp root; preserve unrelated dirty/untracked files. No destructive git commands. If an unsafe side effect is unavoidable, STOP with explicit BLOCKED and evidence. All baseline proof must preserve `generator=mixed`, `select=global`, `hook_clauses=True`, `start_strict=True`, `answer_start=True`, `start_morph=True`. Never silently substitute a handcrafted `AutoParams` or mock helper for actual production branches.

## R2.1 — Finding #1, exercise rejection + selection, not just propose

- The existing CLI call `cmd_autocut(check=False)` **skips** `_autocut_check` and cannot prove the later-rejection claim. Build a safe isolated fixture and exercise the actual validation path (or an instrumented integration test that invokes the real function without bypassing the branch). Do not change its production behavior.
- Construct enough CLI-eligible units to obtain **more than one** pool candidate and reach the real `select=global and len(pool)>1` condition; record branch visitation, input/output candidate refs, durations, scores, and reasons for exclusion.
- Capture the actual CLI-produced candidate pools with and without earlier seed u1 using the same callbacks/settings; a separate `_real_propose` call without CLI callbacks is only supplementary evidence.
- If the real later rejection/global selector cannot be reached safely, report `P1_1_CLI=NOT_REPRODUCED` or `BLOCKED`, never `CONFIRMED VIA CLI`.

## R2.2 — Finding #2, planned first audible content

- Run distinct CLI-configured **no-teaser** and **teaser-present** synthetic cases with strict checks enabled. Capture exact plan/order/refs and first **planned audible words**, separately from body opening. Do not render full videos.
- Current draft `1.1-4 2.1-4 | h:2.1!` implies first teaser words `Принятие тревоги снижает её интенсивность.`, not the body opener `Да, тревога…`. Fix the false statement in REPORT.
- Assert exact accepted/rejected result for both variants, including `answer_start_reason`, actual CLI validator behavior, and whether body-opening answer survives. Do not infer first sound from substring presence in draft.

## R2.3 — Finding #3, real clauses() construction and threshold

- Current fixture has **no alignment**; the CLI explicitly skips constructing `clauses()`. Add synthetic alignment/speechmap in the precise format validated by production `load_alignment` / `SpeechTimes` so the real `__main__.py` clause callback is prepared and exercised. Capture deterministic evidence of this branch.
- Instrument or observe real callback construction and transport to `propose`; do not replace it with `mock_clauses` for the decisive CLI proof.
- Create a separate fixture where the full sentence **begins before** teaser threshold but its eligible clause **begins after** it. Assert exact sentence/word span, ref `@i-j`, duration, score, and whether the production path emits/loses the candidate.
- A private `_hook_cands(mock_clauses)` demonstration may remain as explanatory comparison but is not CLI proof.
- If not attainable without unsafe writes/calls, honestly classify `STATIC_ONLY` / `NOT_REPRODUCED` with the precise blocker.

## R2.4 — Real negative config test and evidence integrity

- `--ac select=greedy` is a **valid CLI override** and can legitimately return CLI rc=0; printing `FAIL select` and checking mismatch truth does not prove that the harness exits nonzero. Add a distinct isolated negative test that feeds an unexpected config into the harness and **asserts actual process exit != 0**. Preserve the already fixed `verify_config` fail-closed logic.
- Compute `CLI_CONFIG_SHA256` from actual bytes of `config/r0.yaml` (or isolated verbatim copy), not `str(REQUIRED_CONFIG)`. Reference SHA256 on pinned baseline: `efdef3adb0396e7e282553a8e3bfb0c690df015abdb8398cea1db5e642aeabba`.
- Count assertions from actual executed checks, not a handwritten summary.
- Reconcile current published logs at `handoff/m223/baseline_stdout.txt`, `baseline_stderr.txt`, `negative_stdout.txt` (report incorrectly says `cli_logs/*`). Publish the next run's actual stdout/stderr and captured exit statuses via `report.sh`, pin blob SHA and SHA256. Remove stale hashes from REPORT. Preserve the prior run in git history.
- Command protocol: `cmd > logfile 2>&1; rc=$?`, verify with `OK/FAIL`; never capture `tee`'s exit by mistake. Explicitly document which hashes vary due temp paths.

## Finish gate

Run deterministic harness and focused checks in isolated environment. Report precisely:
```text
TASK=M223-R2
BASE_SHA=
HANDOFF_HEAD_SHA=
STATUS=READY_FOR_QA|BLOCKED
CONFIG_SHA256=
NEGATIVE_HARNESS_EXIT=
P1_1_CLI=CONFIRMED|NOT_REPRODUCED|STATIC_ONLY
P1_2_CLI=CONFIRMED|NOT_REPRODUCED|STATIC_ONLY
P1_3_CLI=CONFIRMED|NOT_REPRODUCED|STATIC_ONLY
GLOBAL_SELECTOR_EVIDENCE=
TEASER_VARIANT_RESULTS=
CLAUSE_ALIGNMENT_AND_THRESHOLD_EVIDENCE=
CHECK_COUNT=
LOG_PATH_SHA256_AND_EXIT=
PRODUCTION_DIFF=
OWNER_ARTIFACT_PARITY=
WORKTREE_CLEAN=
BLOCKERS=
```
Publish via `bash handoff/bin/report.sh m223 ...`. Request **new independent Sol 6.1 review on pinned final SHA**. Do not start M224 or merge anything without PASS.
