# Independent Sol 6.1 QA — M223-R3 (R4 verdict)

**Verdict: CHANGES_REQUIRED** on reviewed `handoff` commit `bafaaf2f45bf5b9ea4992fb1bb7369944071424d`. M224 BLOCKED until later independent PASS.

Production baseline `3c011e94263e16e5780936b4769d3490cd03b682`; `CLI_REPRO.py` blob `ed1938d8c2291bea49b7c51aff2683c396e66736`; `REPORT.md` blob `0f9e7a126c2966d3ae3539092e6296f5167e7b65`.

Independent execution on clean baseline `/tmp/m223-r3-sol-qa.EjS7Gt`: `exit=0`, **exactly 33 `check()` calls, all PASS**. Real `select_global` visited, original `_autocut_check` invoked transparently and both synthetic candidates PASS; same CLI callbacks prove u2-alone viable. Real late rejection with owner media remains **NOT_REPRODUCED** (acceptable stated limitation). The two hook-first-sound variants are correctly identified. Negative config subprocess `exit=1`, no paid API/render, no real assets touched.

## Blocking overclaim: P1 #3

- `CLI_REPRO.py:900-912` inserts long `2.5` into a **hand-built helper** `demo_sentences_with_long_after()` and returns hardcoded `[(5,8,4.5,"изменяется качество жизни навсегда.")]` from `demo_clauses_full`. The clause is **not** produced by the actual CLI alignment closure. The helper's candidate-loss comparison is useful, but cannot be reported as confirmed *real production CLI impact*.
- The requested **sentence starts before 50%, eligible clause starts after 50%** case is not covered. S4 sentence and clause both start before; `2.5` sentence and clause both start after. Actual CLI callback invocation is not proven.
- The missing `clauses` forwarding is strongly established by static signature and 6 actual `_hook_cands(clauses=None)` calls with align present. Claim `STATIC_ONLY`/`HELPER_ONLY` for candidate-loss impact, or construct a valid real callback demonstration. An honest limited-scope evidence package may pass, even while full impact remains `NOT_REPRODUCED`.

## P2 evidence hygiene

- Published log checksums from reviewed commit:
  - `baseline_stdout.txt`: `40fded80b11bc98a81153bdba1f97d0ada6bfb6de5cbead61dcd7d159c6c1f57`
  - `baseline_stderr.txt`: `95c8bff6a6649ab1b57a5199627eb12b9ec500e79d438bfea79340d7b125f306`
  - `noteaser_stdout.txt`: `b7cad1a2063c6485b784d5de540297aa17c9d293c4eefda22caac798c7a98608`
  - `negative_stdout.txt`: `b6ed48a3422a0c9e0f113524434c933e9fe46e6be877ac540ce170124c7d46fb`
  - `config/r0.yaml`: `efdef3adb0396e7e282553a8e3bfb0c690df015abdb8398cea1db5e642aeabba`
- REPORT contains a pending SHA placeholder, no published log blob SHAs, and omits exact published variable stdout hashes. Tmp-path runtime variance is acceptable, but already-published bytes are hashable.
- `handoff` is a separate artifact branch (root: `README.md`, `handoff/`); do not interpret `git diff main..handoff` as a production diff. Verify only M223 path scope and baseline separately.

**Gate:** fix proof claims/scope and report publication integrity, then request new Sol 6.1 verification. No production edits. Do not start M224.
