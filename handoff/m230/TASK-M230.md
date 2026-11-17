# TASK M230 — Design review of the unified select-after-finalize pipeline (strong model)

**Execution:** Sonnet 4.6. **Independent review:** Sol 6.1. **Plan:** `handoff/m222/PLAN-M222-V2.md`. **Language:** task in English; Russian REPORT and owner-facing response. **Worktree/branch:** `task/m230`, based on the last reviewed integration; never edit or merge `main` directly. Read CLAUDE.md, findings ledger and previous PASS, work only after dependencies.

**Non-negotiable:** no render, real owner-data mutation, paid API, external model calls in the unit/regression suite, new unapproved dependencies. Permanent regressions go in `tests/` with **committed fixtures**; reproduction files may live in `handoff`. A behavior-changing change must first demonstrate a failing regression on the unmodified base, then show a green result. Every tool command has a logged exit code and `OK` / `FAIL`, never `| tee` for exit status. In `REPORT.md`, compare failure sets against `handoff/m222/baseline-failures.txt` with `handoff/m222/compare_failures.py`. Only the appointed integrator merges after Sol PASS.

**Prerequisites:** M228 evidence and M229 observability PASS. **This is a design review, not an implementation task.**

## Part 1 — prepare architecture evidence
Create a compact English dossier for a stronger architecture agent containing the confirmed minimal failing fixtures (#1/#2/#4/#5/#6/#7/#8/#9), real CLI data flow and existing invariants. Compare designs: (A) bounded generation → finalize → validate → global select, (B) incremental repair of current greedy path. Include sound-time window correctness, manual-path separation, deterministic identifiers, mutable titles, hook evaluation and termination of repair loops.

## Part 2 — cost and complexity budget
Measure current seeds/pool/judge calls per source (or mark unavailable). Set **provisional** per-seed alternative cap and per-source judge call cap, with testable worst-case estimates and explicit handling when capped. Check config validation; no made-up final key names. Preserve existing `hook_clauses` semantics.

## Part 3 — get independent architecture verdict
Submit dossier to stronger agent arranged by owner; record outcome in `handoff/m230/ARCHITECTURE.md` in Russian: chosen sequence, invariants, input/output contract, tie-break rules, cost ceiling, fallback, recommended flags. If stronger agent not available: `BLOCKED`, and request owner selection. Do not write code. Sol reviews design conformance afterward.

## Review gate and delivery

Commit only intended source/tests/docs to `task/m230`; keep `handoff/` ignored by main. Supply commit SHA, diffstat, baseline-vs-current failing test **sets**, named tests/fixtures, measured outputs, flag OFF comparison, and any measured budget in Russian `handoff/m230/REPORT.md`. If a prerequisite finding is NOT REPRODUCED, **do not invent a fix**; issue a decision-only report. Ask Sol for independent `PASS / CHANGES_REQUIRED / BLOCKED` with evidence. Publish via `bash handoff/bin/report.sh m230 [evidence files]`. Do not claim the gate is closed or merge to main yourself.
