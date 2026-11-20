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
