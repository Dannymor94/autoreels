# M222A — integration gate closure

Date (Europe/Moscow): 2026-11-18
Task: M222A
Status: **PASS / MERGED**
Repository: Dannymor94/autoreels

## Immutable evidence

- Starting baseline commit: `f92b4d206dfb3a3a281d21f19669db78fa65910e`.
- M222A policy commit, independently reviewed by Sol 6.1: `d4ee3edd76f00dba9b47d707df6cb0492efd9753`.
- CI bootstrap PR #10: https://github.com/Dannymor94/autoreels/pull/10
- CI bootstrap merge into main: `de127dfb6e34fa4563dd157dbeb4cc61b9a95006`.
- Final M222A QA head (CI main merged into task branch): `4759dfb69ce7b18ffea33827c7c3e86ac8118e3c`.
- Final M222A PR #9: https://github.com/Dannymor94/autoreels/pull/9
- Final Sol 6.1 verdict: **FINAL PASS** for `4759dfb`; diff against `de127dfb` contains only `CLAUDE.md`.
- GitHub Actions PR #9: https://github.com/Dannymor94/autoreels/actions/runs/44191540119 — **SUCCESS**, job `134421937101`: **163 passed in 30.43s**.
- M222A merge into main: `3c011e94263e16e5780936b4769d3490cd03b682`.
- Verified on main: `CLAUDE.md` contains the temporary M222–M237 contract; `.github/workflows/offline-smoke.yml` exists and runs 5 unit test files.

## Important limits

- Original full offline pytest on `f92b4d2` exited 1: 2697 passed, 29 failed, 24 skipped, 9 deselected. Original log, failure IDs and environment notes are published under `handoff/m222/`.
- Those 29 failures are historical environment-specific evidence, **not** a green baseline. The 163-test CI workflow is an **offline smoke gate only**, not a full pytest run, not hermetic network isolation, and not an A/B proof.
- No full render, paid model call or production autocut algorithm change was performed as part of M222A.

## M223 entry decision

The M222A prerequisite is **SATISFIED**. M223 can start from the current `origin/main` (at gate closure: `3c011e94263e16e5780936b4769d3490cd03b682`), after rechecking the SHA and preserving any dirty/untracked local data. Use a separate clean `task/m223` worktree. Do not rewrite or delete `data/token_scale.json` or any untracked manifests from an older local checkout. The task definition is `handoff/m223/TASK-M223.md`.
