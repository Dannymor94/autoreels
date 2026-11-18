# M223-R2 — Independent Sol 6.1 QA (R3 verdict)

**Verdict: CHANGES_REQUIRED. M224 BLOCKED.** 2026-11-18.

## Pinned sources

- `handoff` HEAD under review: `7f9bed58a1fd84e2fcb56eb01180bef17a7067d6`.
- Production baseline: `3c011e94263e16e5780936b4769d3490cd03b682`.
- `handoff/m223/CLI_REPRO.py` blob `6c7063b38d6fb07c83de4799bb3f7ee9c14a4c92`.
- `handoff/m223/REPORT.md` blob `6f81ce55624c04d1f704ace0c8daccc0c9e4843d`.

Independent Sol reran the unchanged harness on a clean baseline in `/tmp/m223-r2-sol-qa.uWFWkg`: `exit 0`, **38 printed OK checks**, not 35. Real global selector visited: weights `[89.0,81.0]`, `k=5`, selection `[0,1]`. Real alignment loaded. Negative subprocess `select=greedy` exits 1. No production code, media, paid API, or render changes.

## P1 blockers

1. **Late validation is mocked.** `CLI_REPRO.py:389-417` patches `autoreels.__main__._autocut_check` to issue a fabricated rejection rather than invoking the real validator. This does not substantiate the claimed real late-rejection consequence. `:515` and `:540` compare direct `_real_propose()` runs **without the actual CLI-provided sentence/pause callbacks**. While real global selection is now proven, the *same-callback counterfactual* and downstream rejection remain `NOT_REPRODUCED`.
2. **No decisive clause-threshold counterfactual.** CLI alignment loads and all six `_hook_cands` calls get `clauses=None`: the missing forwarding is supported. But the real CLI closure is not exercised; `demo_clauses` is reconstructed separately at `:775`. Fixture S4 and its `(4,7)` clause **both begin before the 50% teaser threshold**; `_hook_cands` skips S4 whether callback is present or absent. Required sentence-before-threshold / valid-clause-after-threshold case and an independent after-threshold candidate-loss case are missing. The impact claimed as `P1_3_CLI=CONFIRMED` is `NOT_REPRODUCED`.

## Evidence integrity and P2

3. No-teaser run still outputs hook `h:1.2`, yet `CLI_REPRO.py:640` prints first sound as body `Да, тревога…`. The hook is the first *planned* sound. Both variants use `check=False`; substring checks do not prove exact accepted plan/strict validation.
4. The harness reports 35 checks, but its run prints **38 OK**; `n_checks` does not actually count them. Assert the exact count from a counter incremented by `check()`.
5. Exact span `(61.6,65.0)`, duration `3.40`, score `4.80` are printed but not all asserted.
6. Actual SHA256 of **published files at pinned HEAD**, independently checked:

   - `baseline_stdout.txt`: `2413d70979f4b3d894b0d906e4a67789b7870a98e4ba70486ae82ba36d315b49`
   - `baseline_stderr.txt`: `95c8bff6a6649ab1b57a5199627eb12b9ec500e79d438bfea79340d7b125f306`
   - `noteaser_stdout.txt`: `665a5caf23b99272f628733adb642e1adb3ccd87f1f3782875a2118c9ef60dce`
   - `negative_stdout.txt`: `b6ed48a3422a0c9e0f113524434c933e9fe46e6be877ac540ce170124c7d46fb`
   - Production `config/r0.yaml`: `efdef3adb0396e7e282553a8e3bfb0c690df015abdb8398cea1db5e642aeabba`.

The two published stdout hashes **match neither** the summary nor REPORT §8 (the tmp path makes runtime stdout variable, but it does not excuse wrong checksums for *published* artifacts). `handoff/m223/cli_logs/*` still does not exist on published `handoff`; files are directly under `handoff/m223/`.

## Gate

Preserve confirmed improvements (true global selector, alignment load, negative exit and actual config hash). Repair evidence only; do not edit production algorithm or real media. Allow honest `NOT_REPRODUCED` / `STATIC_ONLY` where a safe real path cannot be exercised, but not blanket `CONFIRMED VIA CLI`. Request a fresh independent Sol review on exact new commit. **M224 must not start until PASS.**
