#!/usr/bin/env python3
"""Verify integrity/consistency of an offline QA evidence bundle, not production correctness.

Usage: python evidence_consistency.py /path/to/evidence.json
File paths are relative to the evidence.json directory and cannot escape it.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_LEVELS = {"CLI", "HELPER", "STATIC", "NOT_REPRODUCED"}
_STATUSES = {"CONFIRMED", "NOT_REPRODUCED", "INTENTIONAL", "BLOCKED"}
_PASS = re.compile(r"^\s*PASS \[(\d+)\]", re.MULTILINE)
_FAIL = re.compile(r"^\s*FAIL \[(\d+)\]", re.MULTILINE)


def _file(root: Path, name: object) -> Path:
    if not isinstance(name, str) or not name or name.startswith("/"):
        raise ValueError(f"invalid relative file path: {name!r}")
    p = Path(name)
    if p.is_absolute() or not p.parts or any(part in {"..", "."} for part in p.parts):
        raise ValueError(f"path traversal: {name!r}")
    dest = (root / p).resolve()
    if not dest.is_relative_to(root) or not dest.is_file():
        raise ValueError(f"file missing/outside bundle: {name}")
    return dest


def validate(manifest: Path) -> list[str]:
    errors: list[str] = []
    root = manifest.resolve().parent
    try:
        obj = json.loads(manifest.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return [f"bad manifest: {exc}"]
    if not isinstance(obj, dict) or obj.get("schema") != 1:
        return ["schema must be 1"]
    if not isinstance(obj.get("task"), str) or not obj["task"].strip():
        errors.append("task missing")
    if not isinstance(obj.get("base_sha"), str) or not _SHA.fullmatch(obj["base_sha"]):
        errors.append("base_sha must be 40 lower-case hex digits")

    artifacts = obj.get("artifacts")
    paths: set[str] = set()
    if not isinstance(artifacts, list) or not artifacts:
        errors.append("artifacts must be nonempty list")
        artifacts = []
    for a in artifacts:
        if not isinstance(a, dict):
            errors.append("artifact must be object")
            continue
        p, digest = a.get("path"), a.get("sha256")
        if not isinstance(p, str) or p in paths:
            errors.append(f"duplicate/missing artifact path: {p!r}")
            continue
        paths.add(p)
        if not isinstance(digest, str) or not _HEX.fullmatch(digest):
            errors.append(f"{p}: invalid sha256")
            continue
        try:
            got = hashlib.sha256(_file(root, p).read_bytes()).hexdigest()
            if got != digest:
                errors.append(f"{p}: hash mismatch: got {got} expected {digest}")
        except (ValueError, OSError) as exc:
            errors.append(str(exc))

    runs = obj.get("runs")
    if not isinstance(runs, list) or not runs:
        errors.append("runs must be nonempty list")
        runs = []
    seen_runs: set[str] = set()
    for r in runs:
        if not isinstance(r, dict):
            errors.append("run must be object")
            continue
        name = r.get("name")
        if not isinstance(name, str) or not name or name in seen_runs:
            errors.append(f"invalid/duplicate run name: {name!r}")
            continue
        seen_runs.add(name)
        expected = r.get("expected_exit")
        if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
            errors.append(f"{name}: expected_exit must be nonnegative int")
        for key in ("stdout", "stderr", "exit_file"):
            p = r.get(key)
            if p not in paths:
                errors.append(f"{name}: {key} not hash-pinned in artifacts")
        try:
            stdout = _file(root, r.get("stdout")).read_text(encoding="utf-8")
            _file(root, r.get("stderr"))
            rc_text = _file(root, r.get("exit_file")).read_text(encoding="utf-8").strip()
            if not re.fullmatch(r"\d+", rc_text):
                errors.append(f"{name}: exit receipt is not decimal integer")
            elif isinstance(expected, int) and int(rc_text) != expected:
                errors.append(f"{name}: exit {rc_text} != expected {expected}")
            count = r.get("checks")
            if count is not None:
                nums = [int(x) for x in _PASS.findall(stdout)]
                if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                    errors.append(f"{name}: invalid checks count")
                elif nums != list(range(1, count + 1)):
                    errors.append(f"{name}: expected consecutive PASS [01..{count}], got {nums[:8]}... len={len(nums)}")
                if _FAIL.search(stdout):
                    errors.append(f"{name}: FAIL assertion present in stdout")
        except (ValueError, OSError, UnicodeError) as exc:
            errors.append(f"{name}: {exc}")

    claims = obj.get("claims")
    if not isinstance(claims, list) or not claims:
        errors.append("claims must be nonempty list")
        claims = []
    ids: set[str] = set()
    for c in claims:
        if not isinstance(c, dict):
            errors.append("claim must be object")
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not cid or cid in ids:
            errors.append(f"invalid/duplicate claim id: {cid!r}")
            continue
        ids.add(cid)
        if c.get("level") not in _LEVELS or c.get("status") not in _STATUSES:
            errors.append(f"{cid}: invalid level/status")
        if c.get("level") == "NOT_REPRODUCED" and c.get("status") == "CONFIRMED":
            errors.append(f"{cid}: NOT_REPRODUCED cannot be CONFIRMED")
        refs = c.get("evidence")
        if not isinstance(refs, list) or not refs:
            errors.append(f"{cid}: evidence must reference pinned artifacts")
        elif any(p not in paths for p in refs):
            errors.append(f"{cid}: unpinned evidence ref")
    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: evidence_consistency.py evidence.json", file=sys.stderr)
        return 2
    problems = validate(Path(argv[1]))
    for err in problems:
        print(f"FAIL: {err}", file=sys.stderr)
    if problems:
        print(f"FAIL: {len(problems)} inconsistency/integrity issue(s)", file=sys.stderr)
        return 1
    print("PASS: evidence artifact integrity and receipt consistency (not production QA)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
