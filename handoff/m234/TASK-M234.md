# TASK M234 — Close observability and enforce bounded cost in final pipeline

**Execution:** Sonnet 4.6. **Independent review:** Sol 6.1. **Plan:** `handoff/m222/PLAN-M222-V2.md`. **Language:** task in English; Russian REPORT and owner-facing response. **Worktree/branch:** `task/m234`, based on the last reviewed integration; never edit or merge `main` directly. Read CLAUDE.md, findings ledger and previous PASS, work only after dependencies.

**Non-negotiable:** no render, real owner-data mutation, paid API, external model calls in the unit/regression suite, new unapproved dependencies. Permanent regressions go in `tests/` with **committed fixtures**; reproduction files may live in `handoff`. A behavior-changing change must first demonstrate a failing regression on the unmodified base, then show a green result. Every tool command has a logged exit code and `OK` / `FAIL`, never `| tee` for exit status. In `REPORT.md`, compare failure sets against `handoff/m222/baseline-failures.txt` with `handoff/m222/compare_failures.py`. Only the appointed integrator merges after Sol PASS.

**Prerequisite:** M233 PASS and M229 diagnostics available.

## Part 1 — trace reconcilability
Using the final pipeline, require sum of eligible seeds and their `candidate/generated/skipped/budget-capped` transitions to reconcile; later `validated/selected/rejected/not-reached` must reconcile pool. Report mutation-specific reasons when a formerly valid candidate is finalized away.

## Part 2 — cap verification
Test the per-seed alternatives cap, per-source judge calls cap, fallback behavior, and no false `teaser_misses` pass. If the stronger architecture agent documented a fixed call budget, use that—not an invented constant. No additional gratuitous model use.

## Part 3 — exact outcome regression
Verify old mode OFF is unchanged and the enabled mode produces deterministic identical decisions and diagnostics for repeated input. Any newly ignored candidate must have explicit reason.

## Review gate and delivery

Commit only intended source/tests/docs to `task/m234`; keep `handoff/` ignored by main. Supply commit SHA, diffstat, baseline-vs-current failing test **sets**, named tests/fixtures, measured outputs, flag OFF comparison, and any measured budget in Russian `handoff/m234/REPORT.md`. If a prerequisite finding is NOT REPRODUCED, **do not invent a fix**; issue a decision-only report. Ask Sol for independent `PASS / CHANGES_REQUIRED / BLOCKED` with evidence. Publish via `bash handoff/bin/report.sh m234 [evidence files]`. Do not claim the gate is closed or merge to main yourself.
