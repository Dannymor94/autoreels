# TASK M224 — Prove final duration and refs/time discrepancies (#5/#6)

**Assigned:** Sonnet 4.6. **Review:** Sol 6.1. **Baseline:** `main f92b4d2` algorithm with M222a policy integrated. **Language:** task in English, report and replies in Russian.

**Rules:** read `CLAUDE.md`, `handoff/m222/PLAN-M222-V2.md`, `handoff/m222/CODEX-REVIEW-2026-11-10.md`. Work in dedicated task worktree; take with `bash handoff/bin/take.sh m224` (copy handoff files to worktree if needed). For stage A: **do not fix algorithm code**, no full rendering, paid APIs, network LLM calls, or writes to real `reviews/`, `manifests/`, `transcripts/`, `reels-out/`. Never skip a failing proof.

**CLI-config requirement:** every reproduction must demonstrate actual production path through `__main__.py` using `load_r0_config(root / "config/r0.yaml")` or an isolated CLI invocation with matching parser/settings. Direct `AutoParams()` defaults are not evidence. Use only synthetic/committed or temporary copied inputs. If the CLI path cannot be reached without unsafe side effects, STOP and explain, rather than replacing it with a helper-only test.

## Part 1 — min_sec after start repair (#5)
Build one 25-second seed with a 2-second dangling sentence then 23-second independent sentence, following actual CLI `r0.yaml` settings. Trace `context_start` and `propose` final duration. Do not assume Codex input is valid if real rules reject it; adapt facts and report changes.

## Part 2 — boundaries after removing phrases (#6)
Use at least one pause: sentence 1 spans 0–24 s, sentence 2 spans 28–31 s; open end at sentence 2, final end at sentence 1. Report `refs`, `t0`, `t1` and true audio-aligned windows after `fix_open_end`. Repeat for removing the first sentence with a pause before the next.

## Part 3 — independent baseline check
Check current validator behavior with original config, comparing `min_sec` against exact played duration, not approximations made from sentence durations. Ensure no files under `tests/` or source code are modified in stage A.

## Evidence and delivery

Provide `handoff/m224/REPRO.py` (or a safer deterministic helper plus CLI integration test), `handoff/m224/REPORT.md` in Russian, command output and exit codes. A probe that does not reproduce the failure must be marked `NOT REPRODUCED`; static reading alone must remain `STATIC ONLY`. Store temporary outputs outside the repository while tests run; never edit the owner's artifacts. The report must state expected/actual refs, scores, durations, relevant config keys and concrete branches executed. For each command where success matters, save stdout/stderr to file, capture `$?` immediately (do not pipe into `tee`) and verify with a printed `OK` or `FAIL`. Publish via `bash handoff/bin/report.sh m224 [evidence filenames]`; ask Sol for independent verdict. No task is complete without that verdict.
