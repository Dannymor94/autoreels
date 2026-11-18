# M223 — final independent Sol 6.1 QA (R5)

**Verdict: PASS — limited-scope evidence package.** 2026-11-18. M224 may begin under its own proof-only stage A constraints; this is **not permission to edit production code or perform full rendering**.

## Pinned artifacts

- Reviewed `handoff` SHA: `9bb5667386b70ac93f041b8abb9f22359dbca286`.
- Corrected `handoff/m223/REPORT.md` Git blob: `e7faa0fd0fee424e5f0bc3ea88809f0b08721453`.
- Unchanged `handoff/m223/CLI_REPRO.py` Git blob: `ed1938d8c2291bea49b7c51aff2683c396e66736`.
- Production main baseline: `3c011e94263e16e5780936b4769d3490cd03b682`.

## Independent verification

- Earlier R3 script was executed on a clean production-baseline archive, `exit 0`, exactly **33/33 check() calls PASS**. Since reviewed updates after original R3 changed **documents only**, that execution remains applicable.
- Negative config subprocess: exit 1, real mismatch. Real `select_global()` invoked; original `_autocut_check()` called without replacing its implementation; only synthetic data was checked, no render, no paid API, no owner assets modified.
- Final corrected REPORT explicitly separates supported and unsupported findings:
  1. **#1 CONFIRMED:** `used_seeds` suppression of independently viable u2 under actual CLI callbacks. The **real-media late rejection consequence is NOT_REPRODUCED**.
  2. **#2 CONFIRMED:** body-start-rule bypass in synthetic CLI path. The actual first planned audible item is hook `2.1` / `1.2`, *not* the body opener `Да…`.
  3. **#3 CONFIRMED:** absent clause forwarding by static signature and actual CLI boundary trace; **candidate-loss comparison HELPER_ONLY** (hardcoded demo callback); **real production impact and sentence-before/eligible-clause-after teaser threshold NOT_REPRODUCED**.
- Published log SHA256 and Git blob SHA are reconciled in REPORT §8.

## Important boundary

`handoff` is an independent artifact branch (`README.md` + `handoff/`) without common ancestry with `main`; do not infer production parity from a direct diff between those branch tips. Reviewed changes were documentation-only and the executable proof remained unchanged. Owner-machine dirty/untracked file state was not directly inspected by Sol.

**Decision:** M223 diagnostic evidence workflow **DONE (PASS with explicit limitations)**; do not silently promote limited proof to confirmed production failure. M224 may start **stage A, proof-only**, with its own independent Sol gate before any code changes.
