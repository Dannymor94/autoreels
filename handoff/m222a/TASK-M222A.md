# TASK M222a — bootstrap the evidence pipeline (Sonnet 4.6)

**Blocking prerequisite for all M223–M237 work.** Base source tree `main f92b4d2`. You implement and run the checks; Sol 6.1 independently reviews. All responses and REPORT.md are in **Russian**; this TASK alone is English by owner's explicit request. Do not modify algorithm code. No render, paid API, new videos, or user review files.

## Part 1 — verify sources and branch hygiene

Use a dedicated `task/m222a` worktree at `f92b4d2`; do not switch the existing main checkout. One safe bootstrap from the existing checkout (only if `task/m222a` does not exist yet):

```bash
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
git fetch -q origin '+refs/heads/handoff:refs/remotes/origin/handoff'
git restore --source=origin/handoff --worktree -- handoff/bin handoff/m221 handoff/m222 handoff/m222a
WT="${ROOT}-task-m222a"
git worktree add -b task/m222a "$WT" f92b4d2
mkdir -p "$WT/handoff"
cp -R handoff/bin handoff/m221 handoff/m222 handoff/m222a "$WT/handoff/"
cd "$WT"
```

If the task branch/worktree exists, use it without resetting it; STOP on conflicts. The handoff folder is ignored by main and must never be included in a source commit. Before doing anything else, run:

```bash
git fetch -q origin '+refs/heads/handoff:refs/remotes/origin/handoff'
for path in handoff/m221/REVIEW-autocut-rules.md handoff/m222/HANDOVER-2026-11-10.md handoff/m222/CODEX-REVIEW-2026-11-10.md handoff/m223/TASK-M223.md; do
  git cat-file -e "origin/handoff:$path" && echo "OK source $path" || { echo "FAIL source $path"; exit 1; }
done
base=$(git rev-parse --short=7 HEAD)
test "$base" = f92b4d2 && echo "OK base" || { echo "FAIL base $base"; exit 1; }
```

The first two sources were visible via live GitHub during preparation, but **your local origin/handoff may be stale**; do not rely on a previous report that it only has m220.

## Part 2 — run baseline before patching CLAUDE.md

Check no renderer is writing to `reels-out/`. Run `bash handoff/m222/run_baseline.sh` **before changing any tracked file**. It invokes `.venv/bin/python -m pytest -q -rf` and extracts `handoff/m222/baseline-failures.txt` + complete `pytest-baseline.log`. A test exit code `1` may be an expected baseline finding; any missing collection summary, wrong SHA, or error code beyond 1 is **STOP**. Record exact machine/Python version, command, date, and current failure set. Do not hardcode 7/8 failures or silently discard a flaky test.

## Part 3 — apply the scoped CLAUDE.md policy (documentation only)

```bash
git apply --check handoff/m222/CLAUDE-M222.patch && echo "OK patch-check" || { echo "FAIL patch-check"; exit 1; }
git apply handoff/m222/CLAUDE-M222.patch && echo "OK policy-applied" || { echo "FAIL policy-apply"; exit 1; }
git diff --check && echo "OK diff" || { echo "FAIL diff-check"; exit 1; }
git diff --name-only
```

Expected tracked file change: `CLAUDE.md` only. Commit **only** that tracked file on `task/m222a`, push branch for Sol review, **do not merge to main yourself**. User-appointed integrator merges after Sol PASS. The new policy must exist in main before M223 starts.

## Part 4 — publish and report

Write Russian `handoff/m222a/REPORT.md` with source SHA checks, baseline exact failure set, pytest exit, patch diff, branch commit. Also write Russian `handoff/m222/REPORT.md` explaining baseline capture. Publish the shared baseline using `bash handoff/bin/report.sh m222 baseline-failures.txt pytest-baseline.log` and M222a report with `bash handoff/bin/report.sh m222a`. Ask Sol for independent verdict. Mark `IMPLEMENTED, GATE PENDING` pending Sol and integration, not DONE.
