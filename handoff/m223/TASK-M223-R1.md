# TASK M223-R1 — Repair proof quality, not production behavior

Assigned: Claude Code Sonnet 4.6.
Reviewer: independent Sol 6.1.
Language: task English; REPORT and owner communication Russian.
Status: READY FOR REWORK; M224 remains BLOCKED until Sol PASS.

## Baseline and evidence

- Repository: `Dannymor94/autoreels`.
- Pinned production baseline: `3c011e94263e16e5780936b4769d3490cd03b682`. Revalidate the current `origin/main` before working and report if it advanced.
- Previous handoff commit: `20fc8be744a827a084d6ec0b37c5edec9c6dfd5c`.
- Read `CLAUDE.md`, `handoff/m223/TASK-M223.md`, `handoff/m223/REPRO.py`, `handoff/m223/REPORT.md`, and `handoff/m223/SOL-REVIEW-R1.md`. The last file contains blocking independent QA findings.
- Existing helper-based evidence is useful but **does not pass** the stage A acceptance gate.

## Scope and safety

You are repairing the M223 **evidence harness**. Do not modify production `autocut.py`, `__main__.py`, `config/r0.yaml` or any user data. Work in an isolated clean task worktree, preserving any dirty/untracked files in other worktrees (notably `data/token_scale.json` and untracked manifests). Do not use `git clean`, `git reset --hard`, full renders, paid APIs, cloud LLM calls, or write to real `reviews/`, `manifests/`, `transcripts/`, `reels-out/`. All synthetic I/O must be contained in a temporary isolated root outside the repo, with no dependence on untracked owner artifacts.

## Required fixes and acceptance

### R1. Real configured CLI path — P1

1. Inspect the actual `arl autocut --help`, relevant parser, and `__main__.py` execution branches before constructing fixtures. Do not invent CLI flags.
2. Build deterministic synthetic/committed or copied fixtures sufficient to exercise the **actual production entry path** through `__main__.py`, using `load_r0_config(root / "config/r0.yaml")` and the same production parameter construction. A subprocess CLI run or a test harness invoking the real CLI handler with instrumentation/spies is acceptable; a helper-only `propose()` call is **not** sufficient.
3. Preserve the production configuration in the proof. Explicitly prove `generator=mixed`, `select=global`, `hook_clauses=True`, `start_strict=True`, `answer_start=True`, `start_morph=True`. Do not silently switch generator or disable validations. Any isolated override must be listed as a deliberate test variable with both before/after values; no such override may substitute for the baseline CLI proof.
4. For each P1 #1/#2/#3, record the exact CLI branch reached and whether the issue is CONFIRMED, NOT REPRODUCED, or STATIC ONLY. Do not call a direct helper invocation CLI proof.
5. If a safe CLI run cannot be achieved, **STOP as BLOCKED** with exact side effect/path blocker; do not fake successful evidence.

### R2. Configuration fail-closed — P1

- Wire failed `REQUIRED` comparisons into the final failures and nonzero exit code.
- Add a negative offline test (e.g. injecting `select=greedy` at the config loading boundary) demonstrating `FAIL select` and nonzero exit. The production config file must remain unchanged.
- Derive and report the actual assertion count; no hardcoded misleading `11/11`.

### R3. Complete three findings — P2

- #1: Capture pool before global selection, demonstrate seed #2 is skipped with all units and viable without #1, and show the actual **configured CLI later rejection/global selection consequence**. Give exact unit refs, candidate set, durations, scores and responsible branch.
- #2: Reproduce with answer-start sentence while strict validators are on. Add both no-teaser and teaser-present cases; separately record the **first audible words** and body opening. Show whether the configured CLI validator bypasses each.
- #3: Exercise actual clause preparation from synthetic speech alignment/speech map through the CLI. Compare its handoff to `propose`, not only the private `_hook_cands` helper. Add a separate sentence-start-before-teaser-threshold / eligible-clause-after-threshold case and verify what the real implementation returns. Assert exact clause ref, span, duration, and score; mark any unreproduced branch honestly.

### R4. Measured evidence and review handoff

- Keep `handoff/m223/REPRO.py` as the reproducible entry or add a deterministic CLI-integration test/script with explicit documented invocation. Do not erase original evidence history.
- Update `handoff/m223/REPORT.md` in Russian with actual observed vs expected output per finding; correct 11/11 claim, environment, branch/ref/SHA, exact config values and intentional overrides (if any).
- For each relevant command save stdout/stderr to a named file and capture `$?` immediately (no `tee`), print an explicit `OK` / `FAIL` expectation, and include exit code and SHA256. Publish logs or deterministic excerpts (with hashes) as handoff artifacts.
- Verify no change to production code, owner files, or unrelated worktrees; report `git status --short`. Publish via `bash handoff/bin/report.sh m223 ...`. A task branch PR is needed only if tracked test code changed; do not invent a PR URL.
- Request a **new independent Sol 6.1** review on pinned final artifact SHA. Do not merge or start M224 without PASS.

## Final report contract

```text
TASK=M223-R1
BASE_SHA=
HANDOFF_HEAD_SHA=
STATUS=READY_FOR_QA|BLOCKED
CLI_ENTRY_COMMAND=
CLI_CONFIG_SHA256=
CONFIG_NEGATIVE_TEST=
P1_1_CLI=
P1_2_CLI=
P1_3_CLI=
TEASER_VARIANTS=
CLAUSE_THRESHOLD_CASE=
ASSERTIONS_PASSED=
COMMAND_LOGS_AND_SHA256=
CHANGED_PATHS=
WORKTREE_CLEAN=
PR_URL=NONE|URL
BLOCKERS=
```
