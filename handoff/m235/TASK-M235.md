# TASK M235 — Decision gate for judge top-six and tie-break

**Execution:** Sonnet 4.6. **Independent review:** Sol 6.1. **Plan:** `handoff/m222/PLAN-M222-V2.md`. **Language:** task in English; Russian REPORT and owner-facing response. **Worktree/branch:** `task/m235`, based on the last reviewed integration; never edit or merge `main` directly. Read CLAUDE.md, findings ledger and previous PASS, work only after dependencies.

**Non-negotiable:** no render, real owner-data mutation, paid API, external model calls in the unit/regression suite, new unapproved dependencies. Permanent regressions go in `tests/` with **committed fixtures**; reproduction files may live in `handoff`. A behavior-changing change must first demonstrate a failing regression on the unmodified base, then show a green result. Every tool command has a logged exit code and `OK` / `FAIL`, never `| tee` for exit status. In `REPORT.md`, compare failure sets against `handoff/m222/baseline-failures.txt` with `handoff/m222/compare_failures.py`. Only the appointed integrator merges after Sol PASS.

**Prerequisite:** M228 ledger and M234 PASS. Default outcome is **decision only, no code change**.

## Part 1 — #10
Validate that `hook_judge_top:6` is a consciously configured budget. Measure, if safe and deterministic, how often valid seventh hooks are missed on existing fixtures without spending new judge calls. If no measured user-impact, classify `INTENTIONAL` and keep current budget.

## Part 2 — #12
Document the exact equal-score contract. Identical input must produce identical output; reordered equivalent input need not be invariant unless explicitly required. Recommend a stable tie-break only if it prevents observed harmful output without breaking OFF behavior.

## Part 3 — report
Issue `handoff/m235/DECISION.md` in Russian with explicit KEEP / FIX LATER decisions and source evidence. If new implementation is actually required, **do not** sneak code into this task; ask coordinator for a separately scoped numbered follow-up.

## Review gate and delivery

Commit only intended source/tests/docs to `task/m235`; keep `handoff/` ignored by main. Supply commit SHA, diffstat, baseline-vs-current failing test **sets**, named tests/fixtures, measured outputs, flag OFF comparison, and any measured budget in Russian `handoff/m235/REPORT.md`. If a prerequisite finding is NOT REPRODUCED, **do not invent a fix**; issue a decision-only report. Ask Sol for independent `PASS / CHANGES_REQUIRED / BLOCKED` with evidence. Publish via `bash handoff/bin/report.sh m235 [evidence files]`. Do not claim the gate is closed or merge to main yourself.
