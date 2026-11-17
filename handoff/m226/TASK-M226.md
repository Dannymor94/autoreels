# TASK M226 — Prove global-after-rejection, passage early stop, and tie-break (#4/#9/#12)

**Assigned:** Sonnet 4.6. **Review:** Sol 6.1. **Baseline:** `main f92b4d2` algorithm with M222a policy integrated. **Language:** task in English, report and replies in Russian.

**Rules:** read `CLAUDE.md`, `handoff/m222/PLAN-M222-V2.md`, `handoff/m222/CODEX-REVIEW-2026-11-10.md`. Work in dedicated task worktree; take with `bash handoff/bin/take.sh m226` (copy handoff files to worktree if needed). For stage A: **do not fix algorithm code**, no full rendering, paid APIs, network LLM calls, or writes to real `reviews/`, `manifests/`, `transcripts/`, `reels-out/`. Never skip a failing proof.

**CLI-config requirement:** every reproduction must demonstrate actual production path through `__main__.py` using `load_r0_config(root / "config/r0.yaml")` or an isolated CLI invocation with matching parser/settings. Direct `AutoParams()` defaults are not evidence. Use only synthetic/committed or temporary copied inputs. If the CLI path cannot be reached without unsafe side effects, STOP and explain, rather than replacing it with a helper-only test.

## Part 1 — global vs late final rejection (#4)
Use A score 95 and B/C scores 60/60, with A conflicting with each of B and C but B/C mutually compatible. Show `select_global` choosing B+C, later C rejection, and actual acceptance loop result compared to greedy A. **Must exercise `__main__.py` acceptance path**; stand-alone `select_global` is insufficient.

## Part 2 — passage early stop (#9)
Two fixtures: (i) a preferred neighbor exceeds `max_sec` while the other fits, (ii) a run reaches target on a question and removes it instead of extending to an available answer. Show CLI-derived parameters and actual emitted refs.

## Part 3 — tie-break contract (#12)
Compare identical ordered input to itself (must match) and two intentional permutations with equal numeric score/energy/distance. If behavior differs only on permuted input, document explicitly; do not call it non-determinism under identical input, and do not propose a code change yet.

## Evidence and delivery

Provide `handoff/m226/REPRO.py` (or a safer deterministic helper plus CLI integration test), `handoff/m226/REPORT.md` in Russian, command output and exit codes. A probe that does not reproduce the failure must be marked `NOT REPRODUCED`; static reading alone must remain `STATIC ONLY`. Store temporary outputs outside the repository while tests run; never edit the owner's artifacts. The report must state expected/actual refs, scores, durations, relevant config keys and concrete branches executed. For each command where success matters, save stdout/stderr to file, capture `$?` immediately (do not pipe into `tee`) and verify with a printed `OK` or `FAIL`. Publish via `bash handoff/bin/report.sh m226 [evidence filenames]`; ask Sol for independent verdict. No task is complete without that verdict.
