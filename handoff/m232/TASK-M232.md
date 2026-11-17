# TASK M232 — One structural finalization and selection fix

**Execution:** Sonnet 4.6. **Independent review:** Sol 6.1. **Plan:** `handoff/m222/PLAN-M222-V2.md`. **Language:** task in English; Russian REPORT and owner-facing response. **Worktree/branch:** `task/m232`, based on the last reviewed integration; never edit or merge `main` directly. Read CLAUDE.md, findings ledger and previous PASS, work only after dependencies.

**Non-negotiable:** no render, real owner-data mutation, paid API, external model calls in the unit/regression suite, new unapproved dependencies. Permanent regressions go in `tests/` with **committed fixtures**; reproduction files may live in `handoff`. A behavior-changing change must first demonstrate a failing regression on the unmodified base, then show a green result. Every tool command has a logged exit code and `OK` / `FAIL`, never `| tee` for exit status. In `REPORT.md`, compare failure sets against `handoff/m222/baseline-failures.txt` with `handoff/m222/compare_failures.py`. Only the appointed integrator merges after Sol PASS.

**Prerequisites:** M230 architecture approval, M231 PASS, confirmed #2/#4/#5/#6/#7/#8. **This is the single owner of these related bugs; do not split them into separate `propose()` patches.**

## Part 1 — define and test final state
Create tracked tests and fixtures for final content boundaries after dropping first/last sentence, a pause between phrases, a removed dependency, a question introduced by rhythm, ending changed after intonation repair, and global conflict after late rejection. Every test must show the failure on the unchanged baseline first.

## Part 2 — implement finite finalize → validate → select
Adopt the architecture from M230. Build each candidate's final representation; after every mutation that can affect played content, perform one strict final validation using **actual played refs and aligned sentence time** (not stale `t0/t1`). Recheck start, end, `min_sec/max_sec`, dependencies, rhythm, speaker, and conflict keys. Run global selection on valid finalized candidates; avoid a rejected candidate blocking an available better combination. Include finite iteration/termination and deterministic ordering. Manual selection path must remain untouched.

## Part 3 — negative and OFF tests
Verify the old mode (`new feature flag=false`) is byte-identical in deterministic proposal output (including ordering/notes when possible); validate new mode against all six proof types, B/C vs A counterexample, baseline pytest failure sets and no new judge calls beyond M230 budget. Stop if finalization requires uncontrolled model calls.

## Review gate and delivery

Commit only intended source/tests/docs to `task/m232`; keep `handoff/` ignored by main. Supply commit SHA, diffstat, baseline-vs-current failing test **sets**, named tests/fixtures, measured outputs, flag OFF comparison, and any measured budget in Russian `handoff/m232/REPORT.md`. If a prerequisite finding is NOT REPRODUCED, **do not invent a fix**; issue a decision-only report. Ask Sol for independent `PASS / CHANGES_REQUIRED / BLOCKED` with evidence. Publish via `bash handoff/bin/report.sh m232 [evidence files]`. Do not claim the gate is closed or merge to main yourself.
