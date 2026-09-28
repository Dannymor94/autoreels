"""Tests for --install guard: refuses gate/demo review files from being installed."""
from pathlib import Path

import pytest

from autoreels import __main__ as cli


def test_install_guard_refuses_gate_in_filename(tmp_path, capsys):
    """--install is refused when the review filename contains 'gate'."""
    gate_file = tmp_path / "reviews" / "PXL_gate_demo.review.json"
    gate_file.parent.mkdir(parents=True)
    gate_file.touch()
    ret = cli._blocks_do_apply(str(gate_file), root=tmp_path, install=True)
    assert ret == 1
    captured = capsys.readouterr()
    assert "gate" in captured.err.lower()
    assert "--install refused" in captured.err


def test_install_guard_refuses_file_outside_reviews(tmp_path, capsys):
    """--install is refused when the review file lives outside <root>/reviews/."""
    outside = tmp_path / "reels-out" / "_gate" / "PXL.review.json"
    outside.parent.mkdir(parents=True)
    outside.touch()
    ret = cli._blocks_do_apply(str(outside), root=tmp_path, install=True)
    assert ret == 1
    captured = capsys.readouterr()
    assert "--install refused" in captured.err


def test_install_guard_refuses_render_with_gate_file(tmp_path, capsys):
    """--render (which implies --install) is also refused for gate files."""
    gate_file = tmp_path / "reviews" / "stem_gate.review.json"
    gate_file.parent.mkdir(parents=True)
    gate_file.touch()
    ret = cli._blocks_do_apply(str(gate_file), root=tmp_path, render=True)
    assert ret == 1
    captured = capsys.readouterr()
    assert "--install refused" in captured.err
