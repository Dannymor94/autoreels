# M223-R1 — независимый Sol 6.1 QA (R2 verdict)

Date: 2026-11-18 (Europe/Moscow)
Verdict: **CHANGES_REQUIRED**. M224 remains BLOCKED.

## Pinned artifacts

- Production main: `3c011e94263e16e5780936b4769d3490cd03b682`.
- Handoff HEAD: `2925a9b582c205fed94321602f7d4b5431158197`.
- `handoff/m223/CLI_REPRO.py` blob: `cc58ef8e99902eb7839447345ba3ab47201709c7`.
- `handoff/m223/REPORT.md` blob: `a47d5ef757d4933fa593fa0c4bb4e1b80ad70abe`.

Sol independently executed unchanged CLI_REPRO in clean isolated baseline environment, exit 0, 29 OK checks. The real `cmd_autocut` function and production `AutoParams` construction are reached through a transparent `propose` spy. This is a genuine improvement from the earlier helper-only evidence.

## Blocking P1

1. `CLI_REPRO.py:305` calls `cmd_autocut(check=False)`, skipping `_autocut_check`. Fixture produces one proposal and does not reach the global selector `select=global and len(pool)>1`. Finding #1's claimed late rejection/global-selection consequence remains **NOT REPRODUCED**. Spy records proposal arguments only; subsequent `_real_propose` calls are helper-only, missing CLI callbacks.
2. Finding #3 intentionally lacks `align.json`: the CLI never creates its real `clauses()` callback. The actual decisive comparison again uses handcrafted `AutoParams(generator=montage, validators off)` and `mock_clauses` with private helper `_hook_cands`. Missing actual CLI callback construction, a sentence beginning before teaser threshold with an eligible clause after it, and exact span/time/score. Status for required branch **STATIC ONLY / helper reproduction**, not CONFIRMED VIA CLI.

## P2 corrections

3. Draft contains `h:2.1!`, so first planned audible teaser is `Принятие тревоги снижает её интенсивность.`. `Да, тревога…` is body opening, not first audible sound. Separate teaser-present/no-teaser CLI runs and exact plan assertions missing.
4. Negative embedded `select=greedy` test: `cmd_autocut` returns 0, harness prints `FAIL select` but asserts mismatch as successful and exits PASS. Top-level fail-closed configuration gate **was** independently proven to return 1 under injected mismatched config. Fix the claim and make the negative exit an actual measured assertion.
5. `CLI_CONFIG_SHA256` is hash of `str(REQUIRED_CONFIG)`, **not** config file. Actual SHA256 of `config/r0.yaml`: `efdef3adb0396e7e282553a8e3bfb0c690df015abdb8398cea1db5e642aeabba`.
6. Logs are published at `handoff/m223/baseline_stdout.txt`, `baseline_stderr.txt`, `negative_stdout.txt` (flattened), not `cli_logs/*`; their valid SHA256 are in REPORT §8, while §§3/7 contain stale hashes and report header has stale handoff SHA.
7. No production code changes detected in reviewed proof scope; no model API or full render.

## Measured published log hashes

- baseline_stdout: `021225d41799af71d2dd84dd6297c462c0956ba1e1cf98b9582c243703bd9274`
- baseline_stderr: `ebd22ab9669bb52099fe6378f20b02b03be6efc2d88cbe47cb252c3d77e3a473`
- negative_stdout: `ad8bafce2d398a161b80093fba1f0af53a09575da3b7da73fad4a1a9006e9860`
- draft content: `8de872d4d6c7a0b8d1377a05eb0fc22c87ef6a8631077c8428d391c6d4444dfd`

## Decision

Preserve verified CLI entry/config and top-level fail-closed fix. Repair specific missing branches in `handoff/m223/TASK-M223-R2.md`. Explicit NOT REPRODUCED/STATIC ONLY statuses are acceptable if a safe production route cannot be exercised; fabricated CONFIRMED is not. No M224 until new Sol PASS.
