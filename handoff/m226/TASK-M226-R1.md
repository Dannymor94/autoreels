# TASK M226-R1 — bounded diagnostics #4 / #9 / #12

**Executor:** Claude Code Sonnet 4.6. **Independent reviewer:** Sol 6.1.  
**Production baseline:** `3c011e94263e16e5780936b4769d3490cd03b682` (this replaces the stale `f92b4d2` in `TASK-M226.md`).  
**Precondition:** M225 `PASS_SCOPED`, see `handoff/m225/SOL-REVIEW-STAGE-A.md`.  
**Scope:** Stage A evidence ONLY; no production algorithm edits, no paid API, no video render or owner media/files, no access attempts to blocked macOS Documents folders.

## 0. Read and pin

Read `CLAUDE.md`, `handoff/m222/QA-STOP-RULES.md`, `handoff/m226/TASK-M226.md`, M224/M225 final independent scoped reviews, and `handoff/m228/COORDINATOR-LEDGER-DRAFT.md`.

Use a clean, permitted isolated checkout/worktree. Make the Python harness portable: locate the repo via `__file__` / a documented `--repo-root` option. **No hard-coded `/private/tmp/m225/repo` or `~/Documents` paths.** Provenance needs exact main/handoff SHA, `config/r0.yaml SHA256`, argv and actual `AutoParams` source. All synthetic inputs and CLI outputs must live under `TemporaryDirectory`, with no owner-file access.

## 1. Mandatory small preflight, once

Build one **actual synthetic** `cmd_autocut(stem, root=tmp, llm="none")` fixture using unchanged `config/r0.yaml`, with sentence/block numbering, word timestamps, alignment and (where needed) prosody consistent enough to reach the validator without the M225 `M1: block 1 not in review numbering` false block. Confirm whether **at least one valid final candidate** can reach `_autocut_check` and the final selection/report path. Any spy on `propose`, selection, or validation **must call the original** and record exact result, not replace production behavior.

If this cannot safely be achieved without real media, explicitly mark full CLI final-acceptance effects `NOT_REPRODUCED` with the exact guard. Continue **clearly labelled** helper-only tests rather than creating another fixture revision loop.

## 2. #4 — selection before late rejection

Use deterministic A(95), B(60), C(60), A conflicting with B and C, B/C compatible. Separate:
- `select_global` choosing B+C at the real selector boundary;
- actual final validation rejecting C (if reachable);
- whether the real final path then misses or recovers A.

`CLI_CONFIRMED` requires **actual production command and final acceptance decision**, not a monkeypatched validator that returns a fabricated rejection. If late validation requires unavailable media, report `SELECTOR_HELPER_CONFIRMED / LATE_REJECTION_NOT_REPRODUCED`. Do not promote this to a user-visible defect.

## 3. #9 — build_passage early stop

Test **two distinct fixtures** using CLI-derived (not default) settings:
- Preferred next candidate exceeds `max_sec` but another eligible candidate fits;
- `target_sec` is reached at a question that is dropped while an available answer would extend the clip.

Trace candidate order, distances, score, `max_sec`, `target_sec`, actual branch taken, exact `refs` of produced candidates. If `build_passage` helper reproduces but `cmd_autocut` cannot, label `HELPER_CONFIRMED`. Include a passing control that does not trigger the hypothesized failure.

## 4. #12 — tie-break determinism

- Run identical ordered input repeatedly with fixed seed/config: results **must be byte-for-byte identical**.
- Run at least two deliberate permutations with equal numeric score/energy/distance; record IDs/order, candidate scores, selected IDs and any permutation-dependent differences.
- Never equate order-dependence under *different input order* with non-determinism for *the same input*; distinguish `DETERMINISTIC_ORDER_SENSITIVE` versus `NONDETERMINISTIC_SAME_INPUT` (if provable).
- For helper-only evidence, state `HELPER_CONFIRMED`.

## 5. Evidence / acceptance (no loops)

Publish `handoff/m226/REPRO.py`, `REPORT.md`, R1 stdout/stderr logs (real captured rc and SHA256; no stale M225/M224 logs). Every important assertion must test real returned values rather than literal `True` or repeated exit checks. Provide one line per finding:
`F4=CLI_CONFIRMED|HELPER_CONFIRMED|NOT_REPRODUCED|STATIC_ONLY`;
`F9A/F9B=...`;
`F12=...`.

**Acceptable result:** honest bounded proof, including `NOT_REPRODUCED` for unreachable media/CLI effects; **not all hypotheses must reproduce**. Preserve `PRODUCTION_DIFF=none` and owner-artifact parity; do not rerun settled stages, no more than two targeted reworks per `QA-STOP-RULES.md`.

Publish handoff HEAD SHA and exact log hash values. Stop for independent **Sol 6.1** review. **Do not start M227 or production fixes** without M226 gate. Owner communication/report in Russian; task execution instructions in English.
