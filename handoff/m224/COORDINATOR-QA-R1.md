# Coordinator QA — M224 Stage A, R1

**Verdict:** CHANGES_REQUIRED (not Sol 6.1 PASS).  
**Reviewed:** `727364ec6974b0c8f07a6537168d21936ad16cf1` on `handoff` (2026-11-18).  
**Baseline:** `3c011e94263e16e5780936b4769d3490cd03b682`.  
**Files:** `handoff/m224/REPORT.md` blob `e99dc5a339eef08bd7c479ca6016a0fef6092677`; `REPRO.py` blob `9ef704b93c03ec93f6d24347c01109207af309a7`; `repro_stdout.txt` blob `4a404413e5aebe3ac460bb873f59b8834aa2e81c`.

**Review method:** independently inspected the published code, report, stdout and original source/config through GitHub. The 44/44 reported test assertions and exit 0 are **reported by the published log**, NOT independently rerun in this review. Production source was not modified in this artifact commit. Sol 6.1 has NOT given PASS on M224 in this review.

## Supported observations

1. **#5, helper-level mechanism confirmed:** `context_start` short-drop changes `t0` by `rows[0][1]` and contains no `min_sec` recheck; `propose` computes final `secs` and appends `Proposal(seconds=...)` without a visible post-repair min guard. The harness reports 23.0s against min 25.0s, but invokes `propose()` with separately constructed `prm_simple`.
2. **#6 end, helper-level mechanism confirmed:** `fix_open_end()` decreases `t1` by the sum of sentence durations, not a complete aligned gap-inclusive interval. Synthetic callback with `1.1=0–24`, pause `24–28`, `1.2=28–31` yields `t1=28` and a calculated 4s offset. The last spoken-word timestamp is a test literal, not measured from a CLI-created aligned sentence.
3. **#6 start, helper-level mechanism confirmed:** direct `context_start()` call produces `t0=2` in scenario with user-defined next-speech start at `6`, giving a calculated 4s offset. Combined 26s source yields a reported 24s post-drop candidate in `prm_simple`.

## Blocking findings

**A1 — No actual production CLI invocation.** `REPRO.py` imports and calls `context_start`, `fix_open_end`, and `propose` directly; it never invokes `cmd_autocut()` or parses actual CLI-generated sentence rows via `__main__.py`. Loading `config/r0.yaml` is **not sufficient** for the TASK-M224 CLI gate. Reclassify current `FINDING_*_CLI=CONFIRMED` to `HELPER_CONFIRMED/CLI_NOT_REPRODUCED` until a true CLI run exists.

**A2 — Production configuration is altered on the emission path.** `prm_simple = AutoParams(... generator="passage", end_tone=False, loop=False, prune=False, rhythm=False, hook_teaser=False, start_strict=False, answer_start=False, start_morph=False, ...)`. Actual config uses `generator=mixed`, and `cmd_autocut` constructs the params internally with additional callbacks, selection/validation. A direct `propose` result under `prm_simple` cannot be described as *production-CLI confirmed*.

**A3 — Audio timings and end-tone are fixtures, not real pipeline outputs.** `sentences_A/B/C/D` return hand-coded durations; `actual_last_word_end=24.0` and `actual_audio_start_1_2=6.0` are literals; `end_tone_B` is manually supplied. A real CLI run constructs `sentences()` from transcript words via `montage_blocks/merge_group_sentences` and `end_tone()` via `load_alignment/load_prosody/tone_lookup`. The 4s gaps might change segmentation/eligibility. This must be verified, not assumed. The final played window (including rendered refs, offsets and any padding) is not established by `t1-t0` alone.

**A4 — No full-path guard/check evidence.** Need exact CLI `r0.yaml`, actual branches visited, proposal `pieces`, `unit_refs`, `seconds`, selector and validator status, and aligned spoken-word start/end. Capture any rejection rather than forcing a synthetic acceptance.

## Acceptance for R2

- Use `cmd_autocut("synth", root=isolated_temp_root, llm="none")` or a genuine safe isolated CLI command with unmodified `r0.yaml`; build synthetic manifest, transcript words, map, and alignment/prosody if necessary. Do not render, call APIs, or touch owner media/artifacts.
- For #5, capture original `ProposalParams` from real CLI `propose` entry and assert `min_sec=25`, `generator=mixed`; show that the **actual CLI-produced** proposal survives with `seconds<25` or report `NOT_REPRODUCED`.
- For #6, ensure sentence IDs and their real merged boundaries from word timestamps are verified. Demonstrate the `fix_open_end` branch inside CLI with safely constructed real prosody, plus the start case; compare updated refs and time limits to word-aligned windows. If real tone map impossible, label end case `HELPER_ONLY`.
- Distinguish `proposal seconds`, media source span, aligned speech span, and final planned playback window. Show any 4-second pause actually survives downstream planning; do not claim rendered audio without rendering.
- Preserve a real negative test with nonzero exit and fail-closed stdout/stderr verification. Output precise exit codes, key config values, and SHA256 of published logs; no hidden test skips.
- Keep `src/`, `tests/`, owner assets unchanged. Publish R2 evidence and request fresh independent Sol 6.1 review. No algorithm fixes or M225 until PASS.

**Gate:** M224 Stage A = CHANGES_REQUIRED; production algorithm patching BLOCKED.
