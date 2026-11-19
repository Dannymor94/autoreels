# Sol 6.1 — Independent QA, M224 Stage A R2

**Verdict: `CHANGES_REQUIRED` (bounded evidence correction; NO R3 reproduction).**

- `HANDOFF_EVIDENCE_SHA=d18627fb0fff56c4735b3c0462b1796337989715`
- `BASE_SHA=3c011e94263e16e5780936b4769d3490cd03b682`
- `REVIEW_SCOPE=read-only source + evidence inspection`
- `COORDINATOR_INDEPENDENT_REPRO=40/40 PASS, exit 0`
- `PRODUCTION_DIFF=none`
- `M225_GATE=BLOCKED`

## Verified at real CLI entry point

The R2 `REPRO.py` executes `cmd_autocut("synth", root=isolated_tmp, llm="none")`; the `context_start`, `fix_open_end`, and `propose` spies call their **original production functions**, and CLI `AutoParams.generator="mixed"` comes from the unchanged `config/r0.yaml` (SHA256 `efdef3adb0396e7e282553a8e3bfb0c690df015abdb8398cea1db5e642aeabba`).

The coordinator reproduced `40/40 PASS, exit 0` with an ephemeral merged archive of main `3c011e...` plus evidence `d18627f...` and the available test Python environment. This establishes:

- **Finding #5, CLI-mechanism confirmed:** `context_start` short-drop changes unit 1 refs `1.1-2 → 1.2` and span duration `25.0 → 23.0` seconds, below `min_sec=25`, without a guard in that helper.
- **Finding #6 start, CLI-mechanism confirmed:** resulting `t0=102.0` precedes retained S1.2's first word at `102.4` by **0.4s**.
- **Finding #6 end, CLI-mechanism confirmed:** `fix_open_end` changes unit 2 refs `2.1-2 → 2.1`, ending at `t1=229.0` although retained S2.1's last word ends at `228.0`, a **1.0s** difference. Synthetic prosody was used, not owner media.

These are valid **CLI-path observations of original helper return values**. They must not be upgraded to proof of the final rendered playback or a separately verified final `Proposal.seconds`.

## Remaining evidence inconsistencies (fix documentation, not algorithm)

1. `handoff/m224/repro_stdout.txt` is **stale R1** (44 checks), while R2 source and report claim 40. Replace with an actual R2 run log and publish its SHA256, or explicitly withdraw this path as evidence. Do not present the old log as R2.
2. R2 `spy_propose` captures actual `result`, but the tests do not assert final `Proposal.seconds/pieces/unit_refs`. The direct-helper H9 assertion uses literal `True`. Narrow the emitted-23s statement to an **observed helper-stage under-min span**. Final proposal duration is **NOT_VERIFIED** unless already captured evidence independently proves it.
3. R2 §3 is titled “negative subprocess,” but **does not invoke any subprocess** and does not assert a nonzero exit code. Relabel it a config-difference check. A fail-closed negative result is **NOT_VERIFIED**.
4. Exact post-validation/render playback intervals and perceived audio silence are **NOT_REPRODUCED**. This is not a blocker to accepting helper-boundary evidence if scope is stated honestly; do not render or use owner media.

## Stop rule / next action

Per `handoff/m222/QA-STOP-RULES.md`, R2 is the last targeted reproduction. **Do NOT request M224-R3 or rerun the diagnostic just to manufacture extra claims.** Publish an R2 erratum correcting statuses and log provenance; record unresolved final-proposal/negative/playback checks in M228 as `NOT_VERIFIED` or `NOT_REPRODUCED`. An independent Sol acceptance is still required before M225 Stage A can start. Until then: `M224=CHANGES_REQUIRED`, `M225=BLOCKED`, no production fixes.
