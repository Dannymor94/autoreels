# TASK M233 — Fix existing clause hook wiring and placement

**Execution:** Sonnet 4.6. **Independent review:** Sol 6.1. **Plan:** `handoff/m222/PLAN-M222-V2.md`. **Language:** task in English; Russian REPORT and owner-facing response. **Worktree/branch:** `task/m233`, based on the last reviewed integration; never edit or merge `main` directly. Read CLAUDE.md, findings ledger and previous PASS, work only after dependencies.

**Non-negotiable:** no render, real owner-data mutation, paid API, external model calls in the unit/regression suite, new unapproved dependencies. Permanent regressions go in `tests/` with **committed fixtures**; reproduction files may live in `handoff`. A behavior-changing change must first demonstrate a failing regression on the unmodified base, then show a green result. Every tool command has a logged exit code and `OK` / `FAIL`, never `| tee` for exit status. In `REPORT.md`, compare failure sets against `handoff/m222/baseline-failures.txt` with `handoff/m222/compare_failures.py`. Only the appointed integrator merges after Sol PASS.

**Prerequisite:** M232 PASS; #3 confirmed.

## Part 1 — prove CLI mismatch again
Read `hook_clauses:true` and matching `hook_*` settings from actual `r0.yaml`. Show `__main__.py` creates `clauses` while the montage `propose` invocation does not currently pass it; compare to scenario path without assuming helper defaults.

## Part 2 — fix only existing behavior
Pass the callback through the montage path and use it in `_hook_cands`, including diagnostics where necessary. The teaser position of a clause is measured relative to the **clause start**, not always the beginning of its sentence, while keeping audio/word provenance. Do not introduce any new `hook_clauses_v2` flag, external model calls or generated hooks.

## Part 3 — regression
`hook_clauses:false` produces identical existing output, `hook_clauses:true` detects a valid later clause, and start-pause checks still exclude glued clauses. Tests in `tests/` with tracked fixture; compare baseline failure sets.

## Review gate and delivery

Commit only intended source/tests/docs to `task/m233`; keep `handoff/` ignored by main. Supply commit SHA, diffstat, baseline-vs-current failing test **sets**, named tests/fixtures, measured outputs, flag OFF comparison, and any measured budget in Russian `handoff/m233/REPORT.md`. If a prerequisite finding is NOT REPRODUCED, **do not invent a fix**; issue a decision-only report. Ask Sol for independent `PASS / CHANGES_REQUIRED / BLOCKED` with evidence. Publish via `bash handoff/bin/report.sh m233 [evidence files]`. Do not claim the gate is closed or merge to main yourself.
