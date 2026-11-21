# M231 trace fixtures

The synthetic units, maps and montage project are **deterministic** and built
inline in `tests/test_m231_trace.py` (seeded `random.Random(11)` transcript via
`tests.test_montage._source`). The OFF golden below separately pins the frozen
production comparison.

`fx7l_units.json` is the FX-7L shape kept here for reference and reuse: unit 11
leans on unit 10 (`standalone: false`, `refers: 10`). When a stage drops unit 10
from the final clip, the direct seed event must observe `dep_broken = [[11, 10, "S5"]]`
(see the two P8 regression tests). A clean run preserves the
support and yields `dep_broken = []`.

M231-R2 also requires the direct `propose(..., trace=[])` event to carry
`[[11, 10, "S5"]]` **before** CLI enrichment (P8 direct contract regression).

`compare_off_golden.py` produces a non-vacuous synthetic Proposal SHA256 and
callback-argument log SHA256. `frozen_production_off_golden.json` records the
output recomputed on pinned production `3c011e94263e16e5780936b4769d3490cd03b682`
and compared to R2. This was recomputed during R2, **not** captured before the
original M231 implementation; it does not retroactively satisfy the original
pre-patch evidence-timing requirement.

`compare_cli_off_golden.py` similarly checks the real offline CLI review bytes
and normalized stdout/stderr against that pinned production SHA. It disables
provider keys and uses `check=False` on a synthetic `tmp_path` project.

## M231-R3 architect decision (Issue #17)

`proxy_q_after: bool | null` is a **PROXY**, observed on the raw passage S0
snapshot only. It is true iff the thought immediately after the S0 tail is a
question followed by a non-question. It does **not** prove that `build_passage`
visited or removed this question; it is separate from final `tail_question`.
For montage or an unreached S0 it is null.

`proxy_overlong_side: always null in schema 1 — unobservable without a
build_passage symbol (excluded by CODE-GO-M231-LIMITED); see M232-A4`.
No trace code assigns it and the expanded ON probes assert null for every
seed event (including all nine failure exits and pooled success).

Architect-approved waiver (verbatim):

EVIDENCE=REPRODUCIBLE_FROZEN_GOLDEN — chronological pre-patch capture was NOT achieved; replaced by independent regeneration from immutable 3c011e9. No retroactive claim.

The complete `frozen_production_off_golden.json` now records the exact frozen
source SHA, local reproduction commands, generation date (POST_HOC), Python
version, hashseeds, and Git blob hashes for the generator scripts and imported
test/fixture helpers (including `tests/test_m231_trace.py`, which supplies the
CLI `_montage_project`). The extended proposal/callback golden checks the
original non-vacuous callback case, a passage with rhythm, a question-loop,
FX-7L with a synthetic S5 support drop, and each of ten outcome labels
(nine non-success exits plus `pooled`). Both scripts accept `--frozen-only`
which refuses a non-clean/non-production/non-production-import worktree,
printing its HEAD and imported package path. On the candidate implementation
`compare_off_golden.py --trace-on` exercises those same cases, asserts exact
outcome labels, and verifies byte-for-byte parity with OFF and frozen source.
These are synthetic offline probes only, never provider calls.
