# Sol 6.1 — Independent M225 Stage A acceptance

**VERDICT=PASS_SCOPED**  
**BASE_SHA=3c011e94263e16e5780936b4769d3490cd03b682**  
**EVIDENCE_SHA=af35a30b7e522d344dcac41ce9c2b9e4b32ea8af**  
**REPRO_BLOB=370bd5d9a094095afe70d5a5fcadf88768d3f035**  
**REPORT_BLOB=3909d1ca7769afea58bdd2acca455fbb48413fe5**  
**REPRO_SHA256=0295cc4fd44ad3ebb31f5c51df28468913ab47db79381183cd9269d9e3c04f30**  
**CONFIG_SHA256=efdef3adb0396e7e282553a8e3bfb0c690df015abdb8398cea1db5e642aeabba**

Independent read-only source review plus an isolated full repeat on the production archive (only the absolute fixture root path adapted in memory) returned **exit 0, 16 PASS, 0 FAIL**. No production files, user media, paid calls, or render were changed.

## Accepted findings — helper level ONLY

- **#7 HELPER_CONFIRMED:** real `propose()` emitted units `[1,3]` after rhythm repair, with `#3.refers=2` unsatisfied because `#2` was removed.
- **#8a HELPER_CONFIRMED:** real `propose()` emitted `[1,2,3]` ending on `role="question"`.
- **#8b HELPER_CONFIRMED:** with synthetic sentence and end-tone callbacks, original trimming left a **2.5s** final piece shorter than the **4.09s** minimum rhythm requirement and rejected the candidate; no final proposal.

## Explicit exclusions (carry to M228)

1. **Final CLI effect is NOT_REPRODUCED.** Cases A/B call real `cmd_autocut`, exit 0, but the synthetic block-ref validator rejects output; **zero proposals accepted**. The exit checks do not prove a user-facing clip defect.
2. R2 REPORT's statement that no parameters were manually replaced is **incorrect**. Case A/B set `end_tone=False`, and A/B/C set `start_pause_min=0.0` (production setting `0.15`). Treat those as isolated helper fixtures with production-derived *other* fields.
3. Case C uses synthetic sentence and tone callbacks, not actual alignment/prosody. It proves original helper branch behavior only.
4. **Recoverability after trim is NOT_VERIFIED:** Case C contains no legal neighbor whose insertion would restore the rejected candidate. Withdraw the assertion that the lost candidate could certainly be saved.
5. Missing alignment/prosody warnings occurred in A/B CLI fixtures; voice ending and start-pause checking were not exercised. There is no immutable published stdout/stderr with SHA256 for this historical handoff. The independent repeat supports the accepted *limited* result.
6. The script's absolute path `/private/tmp/m225/repo` requires adaptation for other hosts; the independent reviewer adapted only the path in memory. No literal `True` assertions found.

## Gate and stop rule

`GATE_M225_STAGE_A=PASS_SCOPED`; `GATE_M226_STAGE_A=OPEN` for **diagnostics only**. No M225 R2/R3 recreation of these already proven helper observations. No production fixes, model API, video render or modification of owner artifacts. Keep unverified CLI effects and recoverability in M228; the model's next task is M226 #4/#9/#12 with clear proof levels.
