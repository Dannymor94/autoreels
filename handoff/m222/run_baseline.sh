#!/usr/bin/env bash
# Run once on unchanged main f92b4d2. Exit 0 for a valid inventory even if pytest has baseline failures.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
head=$(git rev-parse --short=7 HEAD)
if [[ "$head" != "f92b4d2" ]]; then echo "FAIL: need baseline main f92b4d2, got $head"; exit 1; fi
if [[ -n "$(git status --porcelain --untracked-files=no -- . ':!data/token_scale.json')" ]]; then
  echo "FAIL: tracked source has uncommitted changes"; exit 1
fi
if [[ ! -x .venv/bin/python ]]; then echo 'FAIL: .venv/bin/python not available'; exit 1; fi
mkdir -p handoff/m222
log=$(mktemp "${TMPDIR:-/tmp}/autoreels-m222-pytest.XXXXXX")
trap 'rm -f "$log"' EXIT
set +e
.venv/bin/python -m pytest -q -rf > "$log" 2>&1
rc=$?
set -e
cp "$log" handoff/m222/pytest-baseline.log
if ((rc > 1)); then echo "FAIL: pytest did not complete normally (rc=$rc)"; tail -40 "$log"; exit 1; fi
.venv/bin/python handoff/m222/compare_failures.py extract handoff/m222/pytest-baseline.log handoff/m222/baseline-failures.txt
printf 'OK baseline recorded, pytest exit code=%s\n' "$rc"
