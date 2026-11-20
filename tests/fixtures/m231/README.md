# M231 trace fixtures

The regression fixtures for `tests/test_m231_trace.py` are **deterministic and
committed as code** — the units, maps and the montage project are built inline in
the test module (seeded `random.Random(11)` transcript via `tests.test_montage._source`),
so there is nothing hash- or clock-dependent to pin to a golden file.

`fx7l_units.json` is the FX-7L shape kept here for reference and reuse: unit 11
leans on unit 10 (`standalone: false`, `refers: 10`). When a stage drops unit 10
from the final clip, the CLI enrichment must observe `dep_broken = [[11, 10, "S5"]]`
(see `test_p8_dep_broken_when_support_dropped_at_s5`). A clean run preserves the
support and yields `dep_broken = []`.
