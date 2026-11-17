# TASK M237 — Two-level A/B quality evaluation and owner gate

**Execution:** Sonnet 4.6. **Independent review:** Sol 6.1. **Plan:** `handoff/m222/PLAN-M222-V2.md`. **Language:** task in English; Russian REPORT and owner-facing response. **Worktree/branch:** `task/m237`, based on the last reviewed integration; never edit or merge `main` directly. Read CLAUDE.md, findings ledger and previous PASS, work only after dependencies.

**Non-negotiable:** no render, real owner-data mutation, paid API, external model calls in the unit/regression suite, new unapproved dependencies. Permanent regressions go in `tests/` with **committed fixtures**; reproduction files may live in `handoff`. A behavior-changing change must first demonstrate a failing regression on the unmodified base, then show a green result. Every tool command has a logged exit code and `OK` / `FAIL`, never `| tee` for exit status. In `REPORT.md`, compare failure sets against `handoff/m222/baseline-failures.txt` with `handoff/m222/compare_failures.py`. Only the appointed integrator merges after Sol PASS.

**Prerequisite:** M236 PASS and integration approved. No full render or mutation of owner review files without separate permission.

## Part 1 — deterministic A/B (mandatory)
On matching source maps, configurations and static fixtures, disable/mimic model judges and text polish through the CLI-configured path. Replay only already-recorded prompts. A cache miss => `BLOCKED` for that case, not an invitation to reach network. Compare symmetric difference of clips (stem+played refs), score sums, unique sentence coverage, start/end validity, missing/drop reasons, judge calls and runtime.

## Part 2 — model-inclusive comparison (optional)
If owner explicitly authorizes free model `record` for new prompts, capture model/provider/prompt hashes and complete provenance. Replay each version separately. Report unique-prompt differences as non-code-isolated, never as pure improvement; retain separate deterministic findings.

## Part 3 — fixed quality tools and decision
Identify the actual available reference gate (handover mentions 64 owner clips; verify filename/existence, never assume). In an isolated copy, run `python tools/score_gate.py <gate> --ref <ref_gate>` and `python tools/clip_checks.py <gate>`. Both write `reels-out/_score`, so guard against overwriting live runs. Lock metrics named in PLAN-M222-V2 before evaluating. List all new and missing clips with reasons; provide owner-review list and keep the new behavior OFF until the owner approves.

## Review gate and delivery

Commit only intended source/tests/docs to `task/m237`; keep `handoff/` ignored by main. Supply commit SHA, diffstat, baseline-vs-current failing test **sets**, named tests/fixtures, measured outputs, flag OFF comparison, and any measured budget in Russian `handoff/m237/REPORT.md`. If a prerequisite finding is NOT REPRODUCED, **do not invent a fix**; issue a decision-only report. Ask Sol for independent `PASS / CHANGES_REQUIRED / BLOCKED` with evidence. Publish via `bash handoff/bin/report.sh m237 [evidence files]`. Do not claim the gate is closed or merge to main yourself.
