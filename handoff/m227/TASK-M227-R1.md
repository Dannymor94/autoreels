# TASK M227-R1 — refusal accounting and teaser diagnostics (#11)

**Executor:** Claude Code Sonnet 4.6. **Reviewer:** independent Sol 6.1.  
**Production baseline:** `main 3c011e94263e16e5780936b4769d3490cd03b682`; supersedes stale `f92b4d2` in `TASK-M227.md`.  
**Gate:** M226 `PASS_SCOPED` in `handoff/m226/SOL-REVIEW-STAGE-A.md`.  
**Scope:** Stage A diagnosis ONLY. No production code edits, no paid LLM calls, no video render and no owner media, `manifests`, `reviews` or real transcript writes.

## 0. Pin and reuse known-safe CLI fixture

Read `CLAUDE.md`, `handoff/m227/TASK-M227.md`, `handoff/m222/QA-STOP-RULES.md`, M223–M226 independent scoped reviews and `handoff/m228/COORDINATOR-LEDGER-DRAFT.md`.

Use `handoff/m226/REPRO.py` preflight as an example of an **accepted synthetic CLI M1 review line**. Reuse its isolated `TemporaryDirectory`, matching map refs and transcript sentence numbering. Implement a portable `REPRO.py` (repo root by arg/file, no hard-coded Mac paths). Record exact immutable baseline SHA, handoff SHA, config hash and real CLI `AutoParams`.

## 1. Full refusal map — static inventory first

Map pre-pool decisions at `eligible`, seed filters, `build_clip`, `build_passage`, `fit_rhythm`, `context_start`, `fix_open_end`, `propose`, `fill_pool`, `_hook_cands`, and `short_variant`.

For each branch distinguish:
- `FILTERED_INTENTIONALLY` — no candidate expected, not an error;
- `REJECTED_EXPLICIT` — reason already counted/logged;
- `REJECTED_UNACCOUNTED` — candidate was attempted but disappeared without a useful reason;
- `NOT_REACHED` or `NOT_REPRODUCED` — no evidence of effect under tested input.

A production `None` result is not automatically an error. Do **not** claim all refusal paths executed merely because they were statically enumerated.

## 2. Two CLI synthetic fixtures, actual accounting

Use two deterministic maps under unchanged `config/r0.yaml`: (A) baseline accepted M1 and (B) a mixed input with intentional seed filtering and at least one rejected candidate.

At **actual** `cmd_autocut(..., llm="none")` boundaries record, when reachable:
`total units → eligible units → attempted seeds → proposal successes/failures → fill_pool weak-seed attempts → pool entries → selected IDs → validator accepted/rejected/not-reached`.

Instrument only with transparent spies calling originals; do not monkeypatch a callback to fabricate acceptance or rejection. Print and assert a conservation/accounting ledger with **named unknown buckets** rather than forcing every difference to be a bug. Distinguish `REVIEW_DRAFT_WRITTEN` from an actual rendered/validated video.

If the synthetic fixture cannot safely reach a stage, label that row `NOT_REPRODUCED` and give precise guard/why. The stage can pass as a bounded investigation without manufacturing complete CLI coverage.

## 3. Teaser_misses mismatch candidate

Test the current diagnostic counter with a concrete synthetic hook that meets a basic phrase test but is rejected by **original** `_hook_cands` due to `start_pause` or `clauses`, using the **same callbacks/flags** for candidate and diagnostic whenever possible.

Separate: `STATIC_CONFIRMED` missing callback, `HELPER_CONFIRMED` counter mismatch, `CLI_CONFIRMED` when the actual command path executes it. No paid model invocation. If no safely constructible candidate triggers mismatch, `NOT_REPRODUCED` with a one-line reason; no new fixture iteration loop.

## 4. Explicit deliverables / stop rule

Publish `handoff/m227/REPRO.py`, `REPORT.md` (Russian), `repro_stdout.log`, `repro_stderr.log`, SHA256, observed **exit code** and total number of real assertions. Be explicit when a log from a previous task is reused for baseline context; never present it as a new execution. If there is no negative subprocess test, do not claim one.

Report:
`TASK=M227-STAGE-A`; `BASE_SHA`; `HANDOFF_HEAD_SHA`; `PRODUCTION_DIFF=none`; `ASSERTIONS_PASS/FAIL`; `CLI_ENTRY_STATUS`; `ACCOUNTING_STATUS`; `PRE_POOL_REFUSALS_STATUS`; `TEASER_MISSES_STATUS`; `NOT_REPRODUCED_SCOPE`; `STDOUT/STDERR_SHA256`.

**Acceptable verdict includes STATIC_ONLY, HELPER_CONFIRMED and NOT_REPRODUCED** for unreachable user effects; do not label all findings CLI just because the CLI itself returned rc0. Do not alter tests/requirements after the task begins without a newly demonstrated risk. One targeted rework per independent QA finding; hard limit is two reworks, then carry limits to M228.

**Next:** publish to `origin/handoff` and stop for independent Sol 6.1. **M228 formal synthesis cannot start before M227 scope gate.** Production fixes remain prohibited.
