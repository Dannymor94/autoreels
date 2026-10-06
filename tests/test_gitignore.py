"""Verify that key paths are covered by .gitignore."""
import shutil
import subprocess

import pytest

_PATHS = [
    "tails/x.wav",
    "music/x.mp3",
    "reviews/x.txt",
    "reels-out/x.mp4",
    "inputs/x.mov",
]


@pytest.fixture(scope="module", autouse=True)
def _require_git():
    if shutil.which("git") is None:
        pytest.skip("git not available")
    result = subprocess.run(["git", "rev-parse", "--git-dir"], capture_output=True)
    if result.returncode != 0:
        pytest.skip("not a git repo")


@pytest.mark.parametrize("path", _PATHS)
def test_path_is_ignored(path):
    result = subprocess.run(["git", "check-ignore", "-q", path], capture_output=True)
    assert result.returncode == 0, f"{path!r} is NOT ignored by .gitignore"
