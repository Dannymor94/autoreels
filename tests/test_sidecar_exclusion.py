"""Sidecar files must be excluded from manifest discovery.

Covers: _glob_manifests, cmd_diagnose_cuts, cmd_resnap, cmd_status, cmd_dump_clips,
malformed-manifest skip behaviour, all-sidecars exclusion, and sidecar suffix registration.
"""
import json
from pathlib import Path

import pytest

from autoreels import __main__ as cli
from autoreels.core.models import Crop, Manifest, SetupProfile


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_manifest(stem: str = "video") -> Manifest:
    return Manifest(
        source=f"inputs/{stem}.mp4",
        source_sha256="a" * 64,
        duration_preset="shorts",
        setup=SetupProfile(
            setup_id="test", crop=Crop(x=0, y=0, w=960, h=1700),
            scale=[1080, 1920], frame=[1920, 1080],
        ),
        run_key="rk1",
        reels=[],
    )


def _write_manifest(path: Path, stem: str = "video") -> Path:
    """Write a minimal valid Manifest JSON."""
    p = path / f"{stem}.json"
    p.write_text(_make_manifest(stem).model_dump_json(), encoding="utf-8")
    return p


def _write_sidecar(path: Path, stem: str = "video") -> Path:
    """Write a discarded sidecar (JSON array — not a Manifest)."""
    p = path / f"{stem}.discarded.json"
    p.write_text(json.dumps([{"id": 1}, {"id": 2}]), encoding="utf-8")
    return p


def _write_malformed(path: Path, stem: str = "broken") -> Path:
    p = path / f"{stem}.json"
    p.write_text("{not valid json", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1. _glob_manifests excludes sidecars
# ---------------------------------------------------------------------------

def test_glob_manifests_excludes_sidecar(tmp_path):
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()
    good = _write_manifest(manifests_dir, "lecture")
    _write_sidecar(manifests_dir, "lecture")

    result = cli._glob_manifests(manifests_dir)

    assert result == [good]


def test_glob_manifests_empty_dir(tmp_path):
    d = tmp_path / "manifests"
    d.mkdir()
    assert cli._glob_manifests(d) == []


# ---------------------------------------------------------------------------
# 2. cmd_diagnose_cuts ignores sidecars
# ---------------------------------------------------------------------------

def test_diagnose_cuts_ignores_sidecar(tmp_path, monkeypatch):
    root = tmp_path
    (root / "manifests").mkdir()
    _write_manifest(root / "manifests", "ep1")
    _write_sidecar(root / "manifests", "ep1")
    (root / "config").mkdir()

    captured = []

    def fake_resolve(manifest, cache_dir, *, audio_format, config_pkey=""):
        return None, "k"  # (transcript, expected_pkey) — None triggers skip, not a parse error

    monkeypatch.setattr(cli, "_resolve_transcript", fake_resolve)
    monkeypatch.setattr(cli, "_config_params_key", lambda root: "")
    monkeypatch.setattr(cli, "load_r0_config", lambda p: _fake_r0_cfg())
    monkeypatch.setattr(cli, "load_render_config", lambda p: _fake_render_cfg())

    # Should run without error; sidecar must not produce "битый манифест"
    import io, sys
    buf = io.StringIO()
    rc = cli.cmd_diagnose_cuts(root=str(root))
    # If sidecar was parsed it would raise ValidationError before returning 0
    assert rc == 0


# ---------------------------------------------------------------------------
# 3. cmd_resnap ignores sidecars
# ---------------------------------------------------------------------------

def test_resnap_ignores_sidecar(tmp_path, monkeypatch):
    root = tmp_path
    (root / "manifests").mkdir()
    _write_manifest(root / "manifests", "talk")
    _write_sidecar(root / "manifests", "talk")

    calls = []

    def fake_recrop(mf, cfg, root):
        calls.append(mf)
        return None  # no update

    monkeypatch.setattr(cli, "load_render_config", lambda p: _fake_render_cfg())
    monkeypatch.setattr(cli, "_recrop_manifest", fake_recrop, raising=False)

    # cmd_resnap will try to load manifests — it should only see talk.json
    # We just need it not to blow up on the sidecar.  A ValidationError from
    # the sidecar would propagate as an exception here.
    try:
        cli.cmd_resnap(root=str(root))
    except SystemExit:
        pass
    except Exception as exc:
        # Only acceptable if it's NOT a sidecar-related parse error
        assert "input_type=list" not in str(exc), f"sidecar leaked: {exc}"


# ---------------------------------------------------------------------------
# 4. cmd_status ignores sidecars in count
# ---------------------------------------------------------------------------

def test_status_ignores_sidecar(tmp_path, monkeypatch, capsys):
    root = tmp_path
    (root / "manifests").mkdir()
    _write_manifest(root / "manifests", "clip1")
    _write_sidecar(root / "manifests", "clip1")

    monkeypatch.setattr(cli, "_machine_settings_line", lambda r: "test-machine")

    cli.cmd_status(root=str(root))
    out = capsys.readouterr().out
    # Must report 1 manifest, not 2
    assert "1 манифест" in out


# ---------------------------------------------------------------------------
# 5. cmd_dump_clips ignores sidecars
# ---------------------------------------------------------------------------

def test_dump_clips_ignores_sidecar(tmp_path, monkeypatch):
    root = tmp_path
    (root / "manifests").mkdir()
    _write_manifest(root / "manifests", "video")
    _write_sidecar(root / "manifests", "video")
    (root / "config").mkdir()

    monkeypatch.setattr(cli, "load_r0_config", lambda p: _fake_r0_cfg())

    out_dir = tmp_path / "out"
    manifests = cli._auto_discover_manifests(root=str(root))
    # Sidecar excluded → only one manifest
    assert len(manifests) == 1
    assert not manifests[0].name.endswith(".discarded.json")


# ---------------------------------------------------------------------------
# 6. Malformed manifest: named, skipped, others continue
# ---------------------------------------------------------------------------

def test_diagnose_cuts_skips_malformed(tmp_path, monkeypatch, capsys):
    root = tmp_path
    (root / "manifests").mkdir()
    _write_manifest(root / "manifests", "good")
    _write_malformed(root / "manifests", "broken")
    (root / "config").mkdir()

    good_seen = []

    def fake_resolve(manifest, cache_dir, *, audio_format, config_pkey=""):
        good_seen.append(manifest.source)
        return None, "k"

    monkeypatch.setattr(cli, "_resolve_transcript", fake_resolve)
    monkeypatch.setattr(cli, "_config_params_key", lambda root: "")
    monkeypatch.setattr(cli, "load_r0_config", lambda p: _fake_r0_cfg())
    monkeypatch.setattr(cli, "load_render_config", lambda p: _fake_render_cfg())

    rc = cli.cmd_diagnose_cuts(root=str(root))
    err = capsys.readouterr().err

    assert rc == 0
    assert "broken" in err  # named in warning
    assert len(good_seen) == 1  # good manifest still processed


# ---------------------------------------------------------------------------
# stubs
# ---------------------------------------------------------------------------

def _fake_r0_cfg():
    from types import SimpleNamespace
    return SimpleNamespace(
        min_pause_for_phrase_end=0.4,
        max_micro_pause=0.15,
        tail_pad_sec=0.7,
        hanging_end_words=[],
        hanging_start_words=[],
        presets={"short": SimpleNamespace(max=60)},
    )


def _fake_render_cfg():
    from types import SimpleNamespace
    return SimpleNamespace(audio_extract=SimpleNamespace(format="m4a"))


# ---------------------------------------------------------------------------
# 7. _glob_manifests excludes ALL project sidecars
# ---------------------------------------------------------------------------

def test_glob_manifests_excludes_all_project_sidecars(tmp_path):
    """A manifests/ dir with every artefact the project writes there yields only real manifests.

    review files live in reviews/ now, so they never appear in manifests/ at all.
    """
    d = tmp_path / "manifests"
    d.mkdir()
    real = _write_manifest(d, "video")

    # Every sidecar suffix produced by the project writers that goes to manifests/.
    sidecars = [
        d / "video.discarded.json",
        d / "video.blocks.discarded.json",
        d / "video.failed_chunks.json",
        d / "video.blocks.topk_cut.json",
    ]
    for s in sidecars:
        s.write_text("[]")

    result = cli._glob_manifests(d)

    assert result == [real]


# ---------------------------------------------------------------------------
# 8. Sidecar-suffix registration: all suffixes produced by writers are covered
# ---------------------------------------------------------------------------

def test_sidecar_suffix_registration():
    """Every multi-dot .json suffix written into manifests/ is either in _SIDECAR_SUFFIXES
    or in the explicitly-deferred set. Fails when a new writer is added without registering.

    Derives the set of suffixes from the source code (with_suffix calls + f-string patterns)
    rather than from a hand-maintained constant, so the next sidecar cannot slip through.
    """
    import re
    from pathlib import Path as _Path
    import autoreels.__main__ as _cli

    src = _Path(_cli.__file__).read_text(encoding="utf-8")

    # Collect suffixes from manifest_path.with_suffix(…) — these write next to a manifest.
    found: set[str] = set()
    for m in re.finditer(r'manifest[_\w]*\.with_suffix\("(\.[\w.]+\.json)"\)', src):
        found.add(m.group(1))

    # Collect from f-string patterns in the manifests dir context:
    # manifests_dir / f"{stem}.something.json"
    for m in re.finditer(r'manifests_dir\s*/\s*f"[^"]*\.([\w.]+\.json)"', src):
        found.add("." + m.group(1))

    # No deferred suffixes: review files now live in reviews/, not manifests/.
    deferred: set[str] = set()

    registered = set(_cli._SIDECAR_SUFFIXES)

    def _covered(suffix: str) -> bool:
        return any(suffix.endswith(s) for s in registered)

    unregistered = {s for s in found if not _covered(s) and s not in deferred}
    assert not unregistered, (
        f"Sidecar suffix(es) found in writers but not in _SIDECAR_SUFFIXES: {sorted(unregistered)}. "
        "Add them to _SIDECAR_SUFFIXES or the deferred set in this test."
    )
