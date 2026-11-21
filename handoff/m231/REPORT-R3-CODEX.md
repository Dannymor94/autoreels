# M231-R3 CODEX implementation handoff — 2026-11-21

**Result:** `R3_IMPLEMENTATION_READY_FOR_INDEPENDENT_QA`; not a Sol PASS. No merge, M232, media, live provider, or production changes.

## Identity
- Production remains `main@3c011e94263e16e5780936b4769d3490cd03b682`.
- Independently reviewed R2 remote parent: `f0c8bb3c1e40e0b1ac1b1154d19e314b2ea5d50b` ([Issue #19 R2 code-subset PASS](https://github.com/Dannymor94/autoreels/issues/19#issuecomment-7057563446)).
- Approved micro-spec with NO additional micro-gate: [Issue #17 architect sign-off](https://github.com/Dannymor94/autoreels/issues/17#issuecomment-7057536891).
- Local commit `45c64a970036efe8f84b6973ac2713e6c50f784c`. GitHub commit `07b24d30917cc45f5b1be32b9c2647b0835abc1c`.
- **Identical tree SHA**: `300f0008047cd0d25e99301335c1d98983a30e49`.
- Branch `task/m231-r3-codex`, [DRAFT PR #20](https://github.com/Dannymor94/autoreels/pull/20), base `main` only to trigger CI.
- Strict six changed files vs R2: `src/autoreels/cloud/autocut.py`, `tests/test_m231_trace.py`, `tests/fixtures/m231/{README.md,compare_cli_off_golden.py,compare_off_golden.py,frozen_production_off_golden.json}`; +437/-4.

## A: S0 proxy
- Within existing `trace is not None` guard, immediately after `snap.S0`: `proxy_q_after` reads tail ID, next thought question and the next thought non-question, precisely as architect pseudocode. No callbacks, scoring, selection, mutation or source helpers.
- Four reached passage oracles: FX-9b [1] => True with final `tail_question=False`; next nonquestion [1,2] => False; last question [1] => False; two questions [1] => False.
- Montage, build_none, skip_used and skip_taken => null. `mixed` continues following existing `passage` boolean used by architect pseudocode.

## B: schema1 null proxy
- `proxy_overlong_side` is initialized null and is never assigned in code.
- README states the value is unobservable without excluded `build_passage` (M232-A4), not inferred.
- New extended trace-on probe asserts null in every seed across 13 coverage cases.

## C: reproducible frozen golden waiver
Waiver verbatim in both fixture README and golden JSON:
`EVIDENCE=REPRODUCIBLE_FROZEN_GOLDEN — chronological pre-patch capture was NOT achieved; replaced by independent regeneration from immutable 3c011e9. No retroactive claim.`

- Provenance: source SHA, file/blob SHA of both generator scripts plus `tests/test_m231_trace.py`, `tests/test_montage.py` and `fx7l_units.json`; Python 3.12.14; hashseeds 0/42/1337; exact executed commands and date labelled POST_HOC.
- Both generator scripts refuse `--frozen-only` unless CWD has clean exact production HEAD and `autoreels.__file__` resolves inside its source tree; preflight prints HEAD/source/clean. Added explicit negative tests from candidate checkout.
- 13 fixtures: original four-callback nonvacuous base, passage with rhythm, question-loop, committed FX-7L with forced S5 reference drop, nine non-success exits and pooled success. ON probes assert each expected outcome; all scenarios hash complete Proposal serialization and ordered, deep-copied callback payload logs. No production `trace=` calls.
- **9/9 comparisons PASS**: frozen production OFF == R3 OFF == R3 ON for PYTHONHASHSEED 0, 42, 1337 (entire JSON result byte-equivalent per mode/seed). CLI review/stdout/stderr also 9/9 PASS with the same seeds.

## Tests
- Python3.12.14 `tests/test_m231_trace.py`: **45 passed per hashseed 0/42/1337**.
- Offline-smoke subset `tests/test_autocut.py tests/test_select_validate.py tests/test_config.py tests/test_models.py tests/test_models_m116.py`: **163 passed**.
- Full Linux suite (run BEFORE last two additional R3-only test cases): **29 failed, 2728 passed, 36 skipped, 9 deselected, 4 warnings**; exact failed-node-ID set == R2 Linux, **0 new failures**, compared using `.pytest_cache/v/cache/lastfailed` and `comm`. The last two added cases subsequently passed in all three focused seed runs (45 total). Full suite is not all green.
- R2 independent macOS environment reported 39 baseline failures, also zero new vs production in the same macOS environment. Do not conflate the two environment-specific counts.
- Python3.12 compile and `git diff --check` passed. Ruff unavailable locally (`No module named ruff`); no lint PASS claim.
- Local isolated R3 worktree clean after commit. Original user worktree unchanged.
- [R3 CI](https://github.com/Dannymor94/autoreels/actions/runs/44874193683): in progress at handoff creation.

## Mandatory next independent review
- Audit the six-file R2→R3 diff and source trace guard.
- Independently regenerate all 13 golden coverage cases from clean detached `3c011e9`, import source preflight, and compare complete bytes to R3 OFF and R3 ON for 0/42/1337. Test predicate A, null B, provenance SHA integrity and the waiver C without accepting implementer assertions. Check all ten labels and stage.
- Confirm CI and exact failing test set parity.
- Return `R3_SOL_CODE_QA=PASS | REQUEST_CHANGES | BLOCKED`. Do not merge or authorize M232.
