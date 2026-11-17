# TASK M229 — Make pre-pool decisions observable without changing selected clips

**Execution:** Sonnet 4.6. **Independent review:** Sol 6.1. **Plan:** `handoff/m222/PLAN-M222-V2.md`. **Language:** task in English; Russian REPORT and owner-facing response. **Worktree/branch:** `task/m229`, based on the last reviewed integration; never edit or merge `main` directly. Read CLAUDE.md, findings ledger and previous PASS, work only after dependencies.

**Non-negotiable:** no render, real owner-data mutation, paid API, external model calls in the unit/regression suite, new unapproved dependencies. Permanent regressions go in `tests/` with **committed fixtures**; reproduction files may live in `handoff`. A behavior-changing change must first demonstrate a failing regression on the unmodified base, then show a green result. Every tool command has a logged exit code and `OK` / `FAIL`, never `| tee` for exit status. In `REPORT.md`, compare failure sets against `handoff/m222/baseline-failures.txt` with `handoff/m222/compare_failures.py`. Only the appointed integrator merges after Sol PASS.

**Prerequisite:** M227 repro + M228 ledger; CLAUDE policy integrated.

## Part 1 — baseline accounting
Capture exact input-unit/eligible-seed/attempted-seed counts and pre-pool reason map using existing CLI path. Write regression tests that assert current selected candidate IDs, refs, scores, order, titles, and `hooks` are identical with diagnostics enabled/disabled where relevant.

## Part 2 — add structured diagnostics
Instrument decisions before pool creation, including `build_clip`, `build_passage`, `taken`, `used_seeds`, overlap, fill-pool and early slice. Use deterministic bounded per-seed records, outcome codes and explicit `not_considered` vs `rejected`; do **not** log per-word noise. Missing/invalid data must produce an explicit reason.

## Part 3 — report counts + regression
Verify counts reconcile at each stage and teaser_misses does not falsely claim pass. Ensure the exact same final clip selection and no new model calls. Save before/after counts and baseline failure comparison.

## Review gate and delivery

Commit only intended source/tests/docs to `task/m229`; keep `handoff/` ignored by main. Supply commit SHA, diffstat, baseline-vs-current failing test **sets**, named tests/fixtures, measured outputs, flag OFF comparison, and any measured budget in Russian `handoff/m229/REPORT.md`. If a prerequisite finding is NOT REPRODUCED, **do not invent a fix**; issue a decision-only report. Ask Sol for independent `PASS / CHANGES_REQUIRED / BLOCKED` with evidence. Publish via `bash handoff/bin/report.sh m229 [evidence files]`. Do not claim the gate is closed or merge to main yourself.
