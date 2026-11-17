# TASK M225 — Prove rhythm repairs can invalidate meaning or ending (#7/#8)

**Assigned:** Sonnet 4.6. **Review:** Sol 6.1. **Baseline:** `main f92b4d2` algorithm with M222a policy integrated. **Language:** task in English, report and replies in Russian.

**Rules:** read `CLAUDE.md`, `handoff/m222/PLAN-M222-V2.md`, `handoff/m222/CODEX-REVIEW-2026-11-10.md`. Work in dedicated task worktree; take with `bash handoff/bin/take.sh m225` (copy handoff files to worktree if needed). For stage A: **do not fix algorithm code**, no full rendering, paid APIs, network LLM calls, or writes to real `reviews/`, `manifests/`, `transcripts/`, `reels-out/`. Never skip a failing proof.

**CLI-config requirement:** every reproduction must demonstrate actual production path through `__main__.py` using `load_r0_config(root / "config/r0.yaml")` or an isolated CLI invocation with matching parser/settings. Direct `AutoParams()` defaults are not evidence. Use only synthetic/committed or temporary copied inputs. If the CLI path cannot be reached without unsafe side effects, STOP and explain, rather than replacing it with a helper-only test.

## Part 1 — dependent meaning loss (#7)
Construct `standalone:false, refers:<id>` where a short intervening thought supports a later conclusion. Show the dependency closure, intermediate `fit_rhythm` decisions, and whether final proposal keeps an unsupported sentence. Use real CLI-derived `rhythm` params.

## Part 2 — dangling question after fit_rhythm (#8a)
Build a distant 5-second payoff and nearby eligible question, then inspect if rhythm extends the final piece and leaves a question last. Record role, exact final refs and whether configured end-tone logic catches it.

## Part 3 — after-end-cut rhythm regression (#8b)
Start with a valid last piece that becomes too short after `fix_open_end`. Show whether a legal additional neighbor exists yet final `rhythm_why` rejects without repair. Do not assume this is a bug before seeing realistic config and trace.

## Evidence and delivery

Provide `handoff/m225/REPRO.py` (or a safer deterministic helper plus CLI integration test), `handoff/m225/REPORT.md` in Russian, command output and exit codes. A probe that does not reproduce the failure must be marked `NOT REPRODUCED`; static reading alone must remain `STATIC ONLY`. Store temporary outputs outside the repository while tests run; never edit the owner's artifacts. The report must state expected/actual refs, scores, durations, relevant config keys and concrete branches executed. For each command where success matters, save stdout/stderr to file, capture `$?` immediately (do not pipe into `tee`) and verify with a printed `OK` or `FAIL`. Publish via `bash handoff/bin/report.sh m225 [evidence filenames]`; ask Sol for independent verdict. No task is complete without that verdict.
