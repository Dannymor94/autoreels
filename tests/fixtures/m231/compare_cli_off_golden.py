"""Frozen M231 synthetic CLI review/stdout probe (no provider or owner data)."""
from __future__ import annotations

import contextlib
import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import autoreels
from tests.test_m231_trace import _montage_project


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-on", action="store_true")
    parser.add_argument("--frozen-only", action="store_true")
    args = parser.parse_args()
    if args.frozen_only:
        repo = Path.cwd().resolve()
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo,
                                       text=True).strip()
        status = subprocess.check_output(["git", "status", "--porcelain=v1"],
                                         cwd=repo, text=True)
        source = Path(autoreels.__file__).resolve()
        print(f"FROZEN_PREFLIGHT HEAD={head} SOURCE={source} CLEAN={not status}",
              file=sys.stderr)
        if (head != "3c011e94263e16e5780936b4769d3490cd03b682"
                or status or not source.is_relative_to(repo / "src")):
            raise RuntimeError("frozen CLI golden requires clean production imports")
    os.environ.pop("ARL_AUTOCUT_TRACE", None)
    os.environ.pop("GROQ_API_KEY", None)
    os.environ.pop("OPENROUTER_API_KEY", None)
    with tempfile.TemporaryDirectory(prefix="m231_cli_baseline_") as dirname:
        directory = Path(dirname)
        proj = _montage_project(directory)
        if args.trace_on:
            os.environ["ARL_AUTOCUT_TRACE"] = str(directory / "trace.jsonl")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = proj["cli"].cmd_autocut("v", root=directory, cache_dir=str(directory / "cache"),
                                         check=False, clips=2)
        review = directory / "reviews" / "v_auto_m56.txt"
        if args.trace_on:
            trace = [json.loads(line) for line in (directory / "trace.jsonl").read_text().splitlines()]
            if not trace or sum(e["event"] == "truncate" for e in trace) != 1:
                raise AssertionError("CLI trace missing single propose truncate event")
        clean_stdout = stdout.getvalue().replace(dirname, "<TMP>").encode("utf-8")
        clean_stderr = stderr.getvalue().replace(dirname, "<TMP>").encode("utf-8")
        print(json.dumps({
            "returncode": rc,
            "review_sha256": _sha(review.read_bytes()) if review.exists() else None,
            "stdout_sha256": _sha(clean_stdout),
            "stderr_sha256": _sha(clean_stderr),
        }, sort_keys=True))


if __name__ == "__main__":
    main()
