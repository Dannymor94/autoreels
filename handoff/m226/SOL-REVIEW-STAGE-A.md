# Sol 6.1 — Independent M226 Stage A acceptance

**VERDICT=PASS_SCOPED**  
`BASE_SHA=3c011e94263e16e5780936b4769d3490cd03b682`  
`EVIDENCE_SHA=e1be1b74cb033a8575d3967eceb8b06c3800f790`  
`CONFIG_SHA256=efdef3adb0396e7e282553a8e3bfb0c690df015abdb8398cea1db5e642aeabba`

**Independent repeat:** exact production archive + immutable R1 `REPRO.py` on isolated synthetic data: **exit 0, 26 PASS, 0 FAIL**. No owner media, paid model, production write or video render.

| Artifact | Git blob | SHA256 |
| --- | --- | --- |
| `REPRO.py` | `452548843f26564121002e45604d940b2d752ab0` | `66c7d4061c0e10ddfe41dcb72ea11ac11723774929177c73535aaea102441b65` |
| `REPORT.md` | `efadc8de3f2a2fe8bc8f0b574a8eafcf68114670` | `def08d6dfdb2414a491cc1c4306de2e95a9b8c97321754ca70c189fb86733f5a` |
| `repro_stdout.log` | `733734d3666fb97f1ee1bd07e775ab02d8cd1052` | `cd3bf3f870d0dfdbe82a0710116341cf6858a1a8775c7b5d9b1b57147f034c41` |
| `repro_stderr.log` | `7b18bb7e8e1007352a38151d40012964afa00776` | `80aa10d654a7e8414528c917c0f5ab58b4b8b363712eec53678b237ef450eec8` |

## Accepted outcomes

- **Preflight CLI_CONFIRMED:** original `cmd_autocut(..., root=TemporaryDirectory, llm="none")` returned rc 0 and produced an M1 proposal line in a synthetic review plan. Fingerprint `cec9bad0fef7a11e` and independently repeatable review SHA256 `95350aa04a173a9c1d81d767c04c6e29a035905c6b1fe5f908c165cf7c1ff60f`.
- **F4 SELECTOR_HELPER_CONFIRMED:** original `select_global` selected B+C = 120 over conflicting A = 95; real `too_close` confirmed intended conflicts. **LATE_REJECTION_NOT_REPRODUCED**.
- **F9A HELPER_CONFIRMED:** `build_passage` stops on an overlong preferred next unit and never tries the previous eligible unit, though it fits; control case passes.
- **F9B HELPER_CONFIRMED:** question brings passage to target, is removed post-loop, and available following answer is not considered; control case passes.
- **F12 HELPER_CONFIRMED/DETERMINISTIC_SAME_INPUT:** identical ordered input produced the same result repeatedly.

## Scope exclusions / M228 ledger

1. **F12 ORDER_SENSITIVE=STATIC_INFERRED_ONLY.** Reversal of `[60,60,60]` produces an identical numeric array. No explicit candidate-identity permutation was tested. It is logically index-tie preference, not experimentally proven permutation behavior. **Never** call same-input behavior nondeterministic.
2. F4 late rejection after global selection **not reproduced**. The report's idea that real audio is the only possible path is **not established**; only this fixture did not exercise it.
3. Preflight generated a *review plan* with a valid M1 line, **not a rendered/validated finished video** nor proof of F4/F9/F12 final CLI effects.
4. No alignment/prosody was loaded. CLI stderr warns start-pause and voice-ending checks were unavailable.
5. Published logs have matching SHA256 but no independent historical shell exit receipt; independent QA ran the script and verified exit 0.
6. The synthetic F4 `conflict` callback is a test input, not the production CLI conflict boundary. Production `select_global` and `too_close` functions themselves were not patched.

## Stop rule and gate

`GATE_M226_STAGE_A=PASS_SCOPED`. `GATE_M227_STAGE_A_DIAGNOSTICS=OPEN` **after publication of this review**. Do not replay M226 simply to expand a concluded claim; unresolved user effects remain in M228 with their limited proof levels.

**M227 production changes and M228 algorithmic fixes are NOT authorized.** M227 may run diagnostics only; do not start M228 formal acceptance before M227 gate.
