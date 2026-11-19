# Sol 6.1 — Final independent acceptance of M224 Stage A R2 (scoped)

**VERDICT=PASS_SCOPED**

- `BASE_SHA=3c011e94263e16e5780936b4769d3490cd03b682`
- `EVIDENCE_SHA=d18627fb0fff56c4735b3c0462b1796337989715`
- `PREVIOUS_SOL_REVIEW=a05624cd16fb4b9b588af8803f617c6c6b176908`
- `ERRATUM_SHA=78511b42887b5be7070b8241d30e6d7556e20568`
- `REPRO=40/40 PASS, exit 0 (coordinator independently executed in isolated archive)`
- `GATE_M224_STAGE_A=PASS_SCOPED`
- `GATE_M225_STAGE_A_DIAGNOSTICS=OPEN`
- `PRODUCTION_FIXES=NOT_AUTHORIZED`

Independent Sol reassessed the R2 evidence **after** the documentation-only erratum. The erratum closes the previous provenance and assertion-level ambiguities by withdrawing the stale R1 stdout and limiting the claim to actually measured original-helper boundaries within a real production-config CLI call.

## Accepted facts

- The real `cmd_autocut("synth", root=isolated_tmp, llm="none")` path calls original `context_start` and `fix_open_end` through transparent spies, with `AutoParams.generator="mixed"` sourced from production `r0.yaml`.
- **#5:** short-drop changes span duration **25.0→23.0s** despite `min_sec=25`, as measured at `context_start` return.
- **#6-start:** observed helper boundary `t0=102.0`, retained first-word time `102.4`: **0.4s** offset.
- **#6-end:** observed helper boundary `t1=229.0`, retained last-word time `228.0`: **1.0s** offset with synthetic prosody.

## Excluded / M228 residuals

- Final `Proposal.seconds`, `pieces` and final validator outcome: **NOT_VERIFIED**.
- Final rendered playback timing or audible silence: **NOT_REPRODUCED**, no render.
- Negative subprocess fail-closed behavior: **NOT_VERIFIED**; §3 was a config-difference check, not a subprocess.
- R1 `handoff/m224/repro_stdout.txt` is stale and **withdrawn as R2 proof**.

Do not silently promote these residuals to CLI-proven findings. Record them in M228 ledger.

## Stop rule and release decision

M224 diagnostics are **closed at the accepted scope**. No M224-R3, no further reproduction merely to restate already verified helper observations. **M225 Stage A diagnostics may start** with the actual production main SHA above. This PASS does **not** authorize production code changes, paid API calls, media render, or changes to owner artifacts. M225 must have its own independent Sol review before M226.
