"""Frozen M231 synthetic CLI review/stdout probe (no provider or owner data)."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path

from tests.test_m231_trace import _montage_project


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    os.environ.pop("ARL_AUTOCUT_TRACE", None)
    os.environ.pop("GROQ_API_KEY", None)
    os.environ.pop("OPENROUTER_API_KEY", None)
    with tempfile.TemporaryDirectory(prefix="m231_cli_baseline_") as dirname:
        directory = Path(dirname)
        proj = _montage_project(directory)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = proj["cli"].cmd_autocut("v", root=directory, cache_dir=str(directory / "cache"),
                                         check=False, clips=2)
        review = directory / "reviews" / "v_auto_m56.txt"
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
