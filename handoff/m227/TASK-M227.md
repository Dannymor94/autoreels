# TASK M227 — Inventory invisible refusals and incorrect diagnostics (#11)

**Assigned:** Sonnet 4.6. **Review:** Sol 6.1. **Baseline:** `main f92b4d2` algorithm with M222a policy integrated. **Language:** task in English, report and replies in Russian.

**Rules:** read `CLAUDE.md`, `handoff/m222/PLAN-M222-V2.md`, `handoff/m222/CODEX-REVIEW-2026-11-10.md`. Work in dedicated task worktree; take with `bash handoff/bin/take.sh m227` (copy handoff files to worktree if needed). For stage A: **do not fix algorithm code**, no full rendering, paid APIs, network LLM calls, or writes to real `reviews/`, `manifests/`, `transcripts/`, `reels-out/`. Never skip a failing proof.

**CLI-config requirement:** every reproduction must demonstrate actual production path through `__main__.py` using `load_r0_config(root / "config/r0.yaml")` or an isolated CLI invocation with matching parser/settings. Direct `AutoParams()` defaults are not evidence. Use only synthetic/committed or temporary copied inputs. If the CLI path cannot be reached without unsafe side effects, STOP and explain, rather than replacing it with a helper-only test.

## Part 1 — full refusal map
Enumerate pre-pool gates at `eligible`, seed filtering, `build_clip`, `build_passage`, `fit_rhythm`, `context_start`, `fix_open_end`, `propose`, `fill_pool`, `_hook_cands` and `short_variant`. Separate normal filtering from lost candidate and normal `None` success semantics.

## Part 2 — exact accounting
Run two synthetic maps under production CLI parameters and compare initial units, eligible seeds, attempted seeds, rejected proposals, pool entries, post-pool accepted/rejected/not-reached. Show which current counters cannot reconcile. Include the supplementary weak-seed `propose` path.

## Part 3 — misleading hook diagnostic
Prove or disprove `teaser_misses` claiming a passing phrase while actual `_hook_cands` rejects it for `start_pause` or `clauses`. Report which callback/flag is missing from the diagnostics and whether any model call is needed (it should not be).

## Evidence and delivery

Provide `handoff/m227/REPRO.py` (or a safer deterministic helper plus CLI integration test), `handoff/m227/REPORT.md` in Russian, command output and exit codes. A probe that does not reproduce the failure must be marked `NOT REPRODUCED`; static reading alone must remain `STATIC ONLY`. Store temporary outputs outside the repository while tests run; never edit the owner's artifacts. The report must state expected/actual refs, scores, durations, relevant config keys and concrete branches executed. For each command where success matters, save stdout/stderr to file, capture `$?` immediately (do not pipe into `tee`) and verify with a printed `OK` or `FAIL`. Publish via `bash handoff/bin/report.sh m227 [evidence filenames]`; ask Sol for independent verdict. No task is complete without that verdict.
