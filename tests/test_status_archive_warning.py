"""cmd_status: archived sources must not trigger 'манифест без видео' warning."""
from pathlib import Path

import pytest

from autoreels import __main__ as cli
from autoreels.core.models import Crop, Manifest, SetupProfile


def _make_manifest(source_name: str = "video.mp4") -> Manifest:
    return Manifest(
        source=f"inputs/{source_name}",
        source_sha256="a" * 64,
        duration_preset="shorts",
        setup=SetupProfile(
            setup_id="test", crop=Crop(x=0, y=0, w=960, h=1700),
            scale=[1080, 1920], frame=[1920, 1080],
        ),
        run_key="rk1",
        reels=[],
    )


def _setup_root(tmp_path: Path, source_name: str = "video.mp4") -> Path:
    root = tmp_path
    for d in ("inputs", "manifests", "inputs-archive", "reels-out", "calibrations"):
        (root / d).mkdir()
    (root / "manifests" / "video.json").write_text(
        _make_manifest(source_name).model_dump_json(), encoding="utf-8"
    )
    return root


def _run_status(root: Path, monkeypatch) -> str:
    monkeypatch.setattr(cli, "_machine_settings_line", lambda r: "test-machine")
    import io, sys
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        cli.cmd_status(root=str(root))
    finally:
        sys.stdout = old
    return buf.getvalue()


def test_no_warning_when_source_in_archive(tmp_path, monkeypatch):
    root = _setup_root(tmp_path)
    (root / "inputs-archive" / "video.mp4").write_bytes(b"fake")

    out = _run_status(root, monkeypatch)
    assert "манифест без видео" not in out


def test_no_warning_when_source_in_inputs(tmp_path, monkeypatch):
    root = _setup_root(tmp_path)
    (root / "inputs" / "video.mp4").write_bytes(b"fake")

    out = _run_status(root, monkeypatch)
    assert "манифест без видео" not in out


def test_warning_when_source_missing_from_both(tmp_path, monkeypatch):
    root = _setup_root(tmp_path)
    # no video in inputs/ or inputs-archive/

    out = _run_status(root, monkeypatch)
    assert "манифест без видео" in out
    assert "inputs-archive" in out
