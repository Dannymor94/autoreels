# TASK M223 — Prove three P1 findings in the real montage path

**Assigned:** Sonnet 4.6. **Review:** Sol 6.1. **Baseline:** `main f92b4d2` algorithm with M222a policy integrated. **Language:** task in English, report and replies in Russian.

**Rules:** read `CLAUDE.md`, `handoff/m222/PLAN-M222-V2.md`, `handoff/m222/CODEX-REVIEW-2026-11-10.md`. Work in dedicated task worktree; take with `bash handoff/bin/take.sh m223` (copy handoff files to worktree if needed). For stage A: **do not fix algorithm code**, no full rendering, paid APIs, network LLM calls, or writes to real `reviews/`, `manifests/`, `transcripts/`, `reels-out/`. Never skip a failing proof.

**CLI-config requirement:** `config/r0.yaml` currently specifies `auto_mode: scenario`; therefore explicitly select the autocut/montage CLI route after inspecting `--help` (do not invent a flag). Also read `handoff/m222/BASELINE-CONFIG.md`.  every reproduction must demonstrate actual production path through `__main__.py` using `load_r0_config(root / "config/r0.yaml")` or an isolated CLI invocation with matching parser/settings. Direct `AutoParams()` defaults are not evidence. Use only synthetic/committed or temporary copied inputs. If the CLI path cannot be reached without unsafe side effects, STOP and explain, rather than replacing it with a helper-only test.

## Part 1 — candidate loss before global selection (#1)
Construct 3–5 units representing a seed, neighboring example, and payoff with explicit refs/times. Reproduce `taken/used_seeds` or preselection overlap removing viable B+C before global selection. Show the candidate pool with and without the earlier seed (via CLI-configured path). No changes to code.

## Part 2 — start validator bypass (#2)
Use a self-contained first sentence beginning with an answer such as `Да, ...`. Confirm `start_strict:true`, `answer_start:true`, `start_morph:true` from `r0.yaml`, demonstrate that `propose()` emits the candidate while the configured scenario/CLI validator would reject this start. Include both body opening and actual first sound if a teaser exists.

## Part 3 — clause hooks lost in propose (#3)
Demonstrate `hook_clauses:true` from the real config; construct a long sentence containing an eligible 3-second clause after the required teaser position. Confirm CLI prepares the clauses callback but `propose` does not receive it. Compare actual CLI path and direct `_hook_cands(..., clauses=...)`, but do not treat helper-only success as CLI proof. Test the sentence starting before the threshold with a clause after threshold separately.

## Evidence and delivery

Provide `handoff/m223/REPRO.py` (or a safer deterministic helper plus CLI integration test), `handoff/m223/REPORT.md` in Russian, command output and exit codes. A probe that does not reproduce the failure must be marked `NOT REPRODUCED`; static reading alone must remain `STATIC ONLY`. Store temporary outputs outside the repository while tests run; never edit the owner's artifacts. The report must state expected/actual refs, scores, durations, relevant config keys and concrete branches executed. For each command where success matters, save stdout/stderr to file, capture `$?` immediately (do not pipe into `tee`) and verify with a printed `OK` or `FAIL`. Publish via `bash handoff/bin/report.sh m223 [evidence filenames]`; ask Sol for independent verdict. No task is complete without that verdict.
