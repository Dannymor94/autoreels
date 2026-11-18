# TASK M224-R2 — Close the actual CLI proof gap

**Assigned:** Claude Code Sonnet 4.6. **Reviewer:** independent Sol 6.1 after publication. **Production baseline:** `3c011e94263e16e5780936b4769d3490cd03b682`. **Previous evidence:** `handoff/m224/REPORT.md`, `REPRO.py`, `repro_stdout.txt` at `727364ec6974b0c8f07a6537168d21936ad16cf1`. **Required QA feedback:** `handoff/m224/COORDINATOR-QA-R1.md`.

Stage A stays **evidence-only**. Do not fix source or tests; do not touch owner manifests, reviews, transcripts, source media, or reels-out. Do not call any paid API or render a video. Work in a dedicated task worktree, publish only `handoff/m224/` artifacts using `report.sh`.

## Mandatory reproduction

1. Read `CLAUDE.md`, `TASK-M224.md`, `COORDINATOR-QA-R1.md` and the actual `__main__.py:cmd_autocut` path before modifying the test harness.
2. Build a disposable CLI root with real-shaped synthetic manifest, transcript words with precise timestamps, map, and real alignment/prosody where required. Use `load_r0_config(root/config/r0.yaml)` and **actual `cmd_autocut("synth", root=..., llm="none")`**. Do not claim a direct helper invocation as an end-to-end CLI test.
3. Spy with transparent wrappers if necessary, but invoke the original production implementation and retain real parameters/callbacks. Assert production generator `mixed`, min_sec=25, original runtime switches, sentence refs, pool candidates, selector, validator behavior, exit codes and final proposals. Do NOT silently substitute `AutoParams(generator="passage", end_tone=False, ...)` for CLI proof.
4. For finding #5: prove or disprove 25.0s seed → short-drop → **CLI-produced** 23.0s output (or another fully explained legal fixture). Capture real `pieces`, `unit_refs`, `seconds` and any filtering.
5. For finding #6 start/end: use words and aligned audible intervals to prove that a real 4s pause exists in the generated sentence rows and after CLI repair; supply a synthetically generated *real* prosody map for the open-end path, if supported. Verify exact refs/time and downstream planned playback intervals. Do not equate `t1-t0`, sentence-duration sum and playable speech duration.
6. Preserve direct-helper cases as supportive unit checks, labelled `HELPER_CONFIRMED`. Where actual CLI branch cannot safely be entered, explicitly report `NOT_REPRODUCED` and show which precondition failed.
7. Provide executable `REPRO.py`, Russian `REPORT.md`, published stdout/stderr, SHA256/blob hashes and actual process return codes. Include a deterministic **negative** test proving fail-closed behavior. No misleading claims or skipped assertions.

**Acceptance:** all claims have evidence matching the exact path asserted; no external side effects; independent Sol 6.1 PASS specifically on the new immutable handoff SHA. Do not start production fixes or M225 before this gate.
