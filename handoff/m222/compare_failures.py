#!/usr/bin/env python3
"""Baseline pytest failure inventory. No network, never writes project data except explicit output."""
from __future__ import annotations
import argparse
import re
from pathlib import Path

PAT = re.compile(r"^\s*(FAILED|ERROR)\s+([^\s]+?)(?:\s+-|\s*$)")
SUMMARY = re.compile(r"\b(?:\d+\s+passed|\d+\s+failed|\d+\s+error|no tests ran|\d+\s+skipped)\b", re.I)


def failures(log: str) -> set[str]:
    return {f"{m.group(1)} {m.group(2)}" for line in log.splitlines() if (m := PAT.match(line))}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["extract", "compare"])
    p.add_argument("first", type=Path, help="extract: pytest.log; compare: baseline-failures.txt")
    p.add_argument("second", type=Path, help="extract: output .txt; compare: new pytest.log")
    args = p.parse_args()
    try:
        if args.command == "extract":
            raw = args.first.read_text(encoding="utf8", errors="replace")
            if not SUMMARY.search(raw) or "no tests ran" in raw:
                print("FAIL: pytest log lacks a valid non-empty test summary")
                return 2
            vals = failures(raw)
            args.second.write_text("# pytest -q -rf on main f92b4d2 (run date and environment in REPORT)\n" + "\n".join(sorted(vals)) + ("\n" if vals else ""), encoding="utf8")
            print(f"OK baseline parsed: {len(vals)} failed/error test identifiers")
        else:
            base = {s.strip() for s in args.first.read_text(encoding="utf8").splitlines() if s.strip() and not s.startswith("#")}
            raw = args.second.read_text(encoding="utf8", errors="replace")
            if not SUMMARY.search(raw) or "no tests ran" in raw:
                print("FAIL: new pytest log lacks a valid non-empty test summary")
                return 2
            now = failures(raw)
            new = sorted(now - base)
            gone = sorted(base - now)
            print(f"Baseline failures={len(base)}; current={len(now)}; new={len(new)}; disappeared={len(gone)}")
            for label, rows in (("NEW", new), ("DISAPPEARED", gone)):
                for row in rows:
                    print(f"{label}: {row}")
            if new:
                print("FAIL: new test failure identifiers were introduced")
                return 1
            print("OK: no new failures relative to baseline")
    except OSError as exc:
        print(f"FAIL: cannot open file: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
