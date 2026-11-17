# TASK M236 — Integration gate: regression, manual-path isolation, flags

**Execution:** Sonnet 4.6. **Independent review:** Sol 6.1. **Plan:** `handoff/m222/PLAN-M222-V2.md`. **Language:** task in English; Russian REPORT and owner-facing response. **Worktree/branch:** `task/m236`, based on the last reviewed integration; never edit or merge `main` directly. Read CLAUDE.md, findings ledger and previous PASS, work only after dependencies.

**Non-negotiable:** no render, real owner-data mutation, paid API, external model calls in the unit/regression suite, new unapproved dependencies. Permanent regressions go in `tests/` with **committed fixtures**; reproduction files may live in `handoff`. A behavior-changing change must first demonstrate a failing regression on the unmodified base, then show a green result. Every tool command has a logged exit code and `OK` / `FAIL`, never `| tee` for exit status. In `REPORT.md`, compare failure sets against `handoff/m222/baseline-failures.txt` with `handoff/m222/compare_failures.py`. Only the appointed integrator merges after Sol PASS.

**Prerequisites:** M229–M235 done/reviewed; only appointed integrator may merge after Sol PASS.

## Part 1 — regression suites
Run all new tracked tests plus the full pytest with `-q -rf`, preserving complete log, return code, and compare using `handoff/m222/compare_failures.py compare handoff/m222/baseline-failures.txt <current.log>`. Any new failure is STOP; explain old failures removed and potential flaky exception explicitly.

## Part 2 — invariants
Assert OFF outputs equal baseline, no manual selection changes, all final windows grounded in sound, candidate accounting reconciles, CLI config validation is correct and model call budgets are bounded. Scan for secret leakage and accidental changes in `reviews/`, `manifests/`, `reels-out/`, configs.

## Part 3 — integration report
Give exact commit stack, change list, regression list and Sol independent verdict. Only then hand integration instructions to appointed integrator; never merge automatically. If risk remains, leave mode OFF, mark `IMPLEMENTED, GATE PENDING`.

## Review gate and delivery

Commit only intended source/tests/docs to `task/m236`; keep `handoff/` ignored by main. Supply commit SHA, diffstat, baseline-vs-current failing test **sets**, named tests/fixtures, measured outputs, flag OFF comparison, and any measured budget in Russian `handoff/m236/REPORT.md`. If a prerequisite finding is NOT REPRODUCED, **do not invent a fix**; issue a decision-only report. Ask Sol for independent `PASS / CHANGES_REQUIRED / BLOCKED` with evidence. Publish via `bash handoff/bin/report.sh m236 [evidence files]`. Do not claim the gate is closed or merge to main yourself.
