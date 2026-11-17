# TASK M231 — Introduce bounded candidate alternatives without early takeover

**Execution:** Sonnet 4.6. **Independent review:** Sol 6.1. **Plan:** `handoff/m222/PLAN-M222-V2.md`. **Language:** task in English; Russian REPORT and owner-facing response. **Worktree/branch:** `task/m231`, based on the last reviewed integration; never edit or merge `main` directly. Read CLAUDE.md, findings ledger and previous PASS, work only after dependencies.

**Non-negotiable:** no render, real owner-data mutation, paid API, external model calls in the unit/regression suite, new unapproved dependencies. Permanent regressions go in `tests/` with **committed fixtures**; reproduction files may live in `handoff`. A behavior-changing change must first demonstrate a failing regression on the unmodified base, then show a green result. Every tool command has a logged exit code and `OK` / `FAIL`, never `| tee` for exit status. In `REPORT.md`, compare failure sets against `handoff/m222/baseline-failures.txt` with `handoff/m222/compare_failures.py`. Only the appointed integrator merges after Sol PASS.

**Prerequisites:** confirmed #1/#9, M229 and M230 PASS.

## Part 1 — measure baseline cost
Before any logic change, record for fixture and available real inputs: eligible seeds, proposals by seed, pool size, number of potential candidates, judge calls and deterministic CPU time. Report current `clips`, `check_pool`, `select`, `close_by`, `generator` config.

## Part 2 — test then implement
Write failing regressions showing the missing alternative and passage trying the wrong side/ending at a question. Make candidate generation produce enough alternatives **within a finite budget** without claiming ownership before select. Any genuinely new generation mode must be gated OFF by default, with config-schema validation and bounded candidates per seed; if cap is exhausted, a visible `not_considered_budget` count is mandatory.

## Part 3 — cost/off baseline
Test `OFF` exact output against f92b baseline and new mode against fixture. Show quantitative growth and judge-call ceiling. Do not let generating alternatives automatically increase free-tier judge calls.

## Review gate and delivery

Commit only intended source/tests/docs to `task/m231`; keep `handoff/` ignored by main. Supply commit SHA, diffstat, baseline-vs-current failing test **sets**, named tests/fixtures, measured outputs, flag OFF comparison, and any measured budget in Russian `handoff/m231/REPORT.md`. If a prerequisite finding is NOT REPRODUCED, **do not invent a fix**; issue a decision-only report. Ask Sol for independent `PASS / CHANGES_REQUIRED / BLOCKED` with evidence. Publish via `bash handoff/bin/report.sh m231 [evidence files]`. Do not claim the gate is closed or merge to main yourself.
