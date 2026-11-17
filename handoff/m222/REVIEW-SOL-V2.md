# Independent review protocol — Sol 6.1 (instructions in English; report in Russian)

Review tasks in `handoff/m222a/` and `handoff/m223/` through `handoff/m237/` as an independent verifier. Read `CLAUDE.md` and `handoff/m222/PLAN-M222-V2.md`. Do not assume Sonnet's report is evidence. Do not fix code in the review worktree. Return `PASS`, `CHANGES_REQUIRED`, or `BLOCKED` with reasons in **Russian**.

## Mandatory checks

1. Verify base branch/commit and that original baseline came from `main f92b4d2` before fixes. Compare pytest **failure sets** against `handoff/m222/baseline-failures.txt` using `handoff/m222/compare_failures.py compare ...`; a known flaky test requires an explicit documented exclusion, not an ungrounded allowance.
2. Note `auto_mode: scenario` in actual `config/r0.yaml`; a default `arl auto` call does NOT demonstrate `propose`. For every finding, verify the reproducer travels through the CLI/config mapping from `config/r0.yaml` (not an invented `AutoParams()` default) and produces the claimed failure on baseline. A helper-only reproduction is insufficient for CLI-path claims, particularly #3 `clauses`.
3. For implementation tasks, demand proof the named regression fails on unchanged baseline and passes after changes. Inspect patches, tests in `tests/` with tracked fixtures, and guard against writes to reviews/manifests/reels-out outside a protected temporary area.
4. Require equality of previous behavior with existing feature flag OFF, when applicable. For existing enabled-but-broken `hook_clauses`, test `false` baseline and `true` working without a duplicate switch.
5. Inspect boundaries **after** all repairs and any CLI finalization; check `min_sec`, `refs`, `t0/t1`, independent start/end, preserved referential dependencies, dedup and `prm.clips` based on actual content.
6. Audit visibility: every emitted or excluded candidate and every bounded/blocked alternative has a deterministic reason; no misleading 'passed' message in `teaser_misses`; compare counts to the whole pipeline, not only post-generation pool.
7. Review cost: alternatives per seed, pool size and model-judge calls per source must have measured bounds; new flags only when new behavior is introduced, defaults OFF.
8. For M237, isolate deterministic A/B from model-dependent results. A replay miss is a failure, not a reason to silently access the network. Check `tools/score_gate.py ... --ref ...` and `tools/clip_checks.py ...`, including evidence of source gate availability and output isolation.
9. Record modified files and every missing proof. Never approve a claim based solely on Sonnet's prose or screenshots. No PASS for missing test logs, untracked test fixture, or unauthorized merge to main.

## Response template (Russian)

`VERDICT: PASS | CHANGES_REQUIRED | BLOCKED`

- `База / ветка / коммит:`
- `Повторено (команды, коды, ожидаемый/фактический выход):`
- `Baseline failures: новых <N>, прежних <N>, исчезнувших <N> (наборы):`
- `CLI конфиг: какие значения из config/r0.yaml и как дошли до вызова:`
- `Тесты, файлы, регрессии, OFF baseline:`
- `Замечания с приоритетом, конкретные условия принятия:`
