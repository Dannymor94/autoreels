> **SUPERSEDED 2026-11-19.** The authoritative execution specification is [`TASK-M228-R1.md`](TASK-M228-R1.md). The below historical task contains an obsolete baseline `f92b4d2` and must not be executed. Use frozen `main@3c011e94263e16e5780936b4769d3490cd03b682` and the independent M227 acceptance. Retained only for audit history.

# TASK M228 — Consolidate 12 findings and gate the change set

**Assigned:** Sonnet 4.6. **Review:** Sol 6.1. **Baseline:** `main f92b4d2` algorithm with M222a policy integrated. **Language:** task in English, report and replies in Russian.

**Rules:** read `CLAUDE.md`, `handoff/m222/PLAN-M222-V2.md`, `handoff/m222/CODEX-REVIEW-2026-11-10.md`. Work in dedicated task worktree; take with `bash handoff/bin/take.sh m228` (copy handoff files to worktree if needed). For stage A: **do not fix algorithm code**, no full rendering, paid APIs, network LLM calls, or writes to real `reviews/`, `manifests/`, `transcripts/`, `reels-out/`. Never skip a failing proof.

**CLI-config requirement:** every reproduction must demonstrate actual production path through `__main__.py` using `load_r0_config(root / "config/r0.yaml")` or an isolated CLI invocation with matching parser/settings. Direct `AutoParams()` defaults are not evidence. Use only synthetic/committed or temporary copied inputs. If the CLI path cannot be reached without unsafe side effects, STOP and explain, rather than replacing it with a helper-only test.

## Part 1 — evidence ledger
Read Sol reviews and the M223–M227 repro files. Create `handoff/m228/FINDINGS.md` (Russian) with exactly 12 rows: `CONFIRMED`, `NOT REPRODUCED`, `INTENTIONAL`, or `BLOCKED`; evidence command, CLI config values, expected vs observed, user-visible impact. Distinguish static proof from runtime proof.

## Part 2 — hook judge budget (#10)
Inspect `hook_judge_top: 6` in `config/r0.yaml`. Treat the seventh-candidate loss as a **known call budget**, not automatically a defect. If user-impact not measured, status `INTENTIONAL / PENDING MEASUREMENT` and no fix ticket.

## Part 3 — go/no-go
Map confirmed #1/#9 to bounded generation, confirmed #2/#4/#5/#6/#7/#8 to one final-validation architecture, confirmed #3 to existing clause flag wiring and confirmed #11 to observability-first. Note uncertainties requiring escalation. No algorithm code edits in M228.

## Evidence and delivery

Provide `handoff/m228/REPRO.py` (or a safer deterministic helper plus CLI integration test), `handoff/m228/REPORT.md` in Russian, command output and exit codes. A probe that does not reproduce the failure must be marked `NOT REPRODUCED`; static reading alone must remain `STATIC ONLY`. Store temporary outputs outside the repository while tests run; never edit the owner's artifacts. The report must state expected/actual refs, scores, durations, relevant config keys and concrete branches executed. For each command where success matters, save stdout/stderr to file, capture `$?` immediately (do not pipe into `tee`) and verify with a printed `OK` or `FAIL`. Publish via `bash handoff/bin/report.sh m228 [evidence filenames]`; ask Sol for independent verdict. No task is complete without that verdict.
