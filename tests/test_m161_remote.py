"""M161: render on the remote machine (gamebox) — what goes there, what runs there, what comes back."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from autoreels.core.config import RemoteRender
from autoreels.local import remote as RM

CFG = RemoteRender(host="gamebox", root="/mnt/data/autoreels", encoder="h264_vaapi", profile="h264",
                   lock="/mnt/data/locks/heavy.lock")
STEM = "2026-08-08 09h 33m 14s"
SHA = "a" * 64


def _tree(tmp: Path) -> Path:
    for d in ("reviews", "transcripts", "data/cache", "data/models", "music"):
        (tmp / d).mkdir(parents=True, exist_ok=True)
    (tmp / "reviews" / f"{STEM}_m157.review.json").write_text("{}", encoding="utf-8")
    for suf in ("speechmap.json", "align.json", "map.json"):
        (tmp / "transcripts" / f"{STEM}.{suf}").write_text("{}", encoding="utf-8")
    (tmp / "transcripts" / "other.map.json").write_text("{}", encoding="utf-8")
    (tmp / "data" / "cache" / "x.k1.transcript.json").write_text(json.dumps({"source_sha256": SHA}), encoding="utf-8")
    (tmp / "data" / "cache" / "y.k1.transcript.json").write_text(json.dumps({"source_sha256": "b" * 64}), encoding="utf-8")
    (tmp / "data" / "cache" / "z.mp3").write_bytes(b"0")
    (tmp / "data" / "models" / "face.onnx").write_bytes(b"0")
    (tmp / "music" / "pad.m4a").write_bytes(b"0")
    return tmp


def test_m161_data_files_are_the_review_transcripts_cached_transcript_models_music(tmp_path):
    root = _tree(tmp_path)
    rel = RM.data_files(root, root / "reviews" / f"{STEM}_m157.review.json", STEM, SHA, music="pad.m4a")
    assert rel[0] == f"reviews/{STEM}_m157.review.json"
    assert {f"transcripts/{STEM}.speechmap.json", f"transcripts/{STEM}.align.json", f"transcripts/{STEM}.map.json"} <= set(rel)
    assert "transcripts/other.map.json" not in rel
    assert "data/cache/x.k1.transcript.json" in rel and "data/cache/y.k1.transcript.json" not in rel
    assert "data/cache/z.mp3" not in rel and "data/models" in rel and "music/pad.m4a" in rel


def test_m161_remote_command_quotes_and_takes_the_lock():
    line = RM.remote_render_cmd(CFG, f"reviews/{STEM}_m157.review.json", reels="1-9", gate="m161")
    assert line.startswith("cd /mnt/data/autoreels && flock /mnt/data/locks/heavy.lock .venv/bin/python -m autoreels render")
    assert f"'reviews/{STEM}_m157.review.json'" in line
    assert "--encoder h264_vaapi --profile h264" in line and "--gate m161" in line and "--reels 1-9" in line


class _Run:
    def __init__(self, probe_rc=0, fail=None):
        self.calls, self.probe_rc, self.fail = [], probe_rc, fail

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        rc = 0
        if argv[0] == "ssh" and "resolve_source" in argv[-1]:
            rc = self.probe_rc
        if self.fail and self.fail(argv):
            rc = 7
        return subprocess.CompletedProcess(argv, rc, stdout="a.py\0b.py\0" if argv[0] == "git" else "",
                                           stderr="boom" if rc else "")


def test_m161_render_remote_sequence_without_source_copy(tmp_path):
    root = _tree(tmp_path)
    run = _Run(probe_rc=0)
    out = RM.render_remote(CFG, root=root, review=root / "reviews" / f"{STEM}_m157.review.json", stem=STEM,
                           source_sha256=SHA, local_source=None, reels="1-9", gate="m161", run=run, log=lambda s: None)
    kinds = [c[0] for c in run.calls]
    assert kinds == ["ssh", "git", "rsync", "rsync", "ssh", "ssh", "sh"]
    assert run.calls[2][-1] == "gamebox:/mnt/data/autoreels/" and any(a.startswith("--files-from=") for a in run.calls[2])
    assert run.calls[3][:2] == ["rsync", "-aR"] and f"reviews/{STEM}_m157.review.json" in run.calls[3]
    assert "render" in run.calls[5][-1] and "flock" in run.calls[5][-1]
    pull = run.calls[6][-1]
    assert "tar -cf - ." in pull and "_gate/m161" in pull and STEM in pull
    assert out == root / "reels-out" / STEM / "_gate" / "m161" and out.is_dir()


def test_m161_source_copied_only_when_missing_there(tmp_path):
    root = _tree(tmp_path)
    src = root / "src.mp4"
    src.write_bytes(b"0")
    run = _Run(probe_rc=1)
    RM.render_remote(CFG, root=root, review=root / "reviews" / f"{STEM}_m157.review.json", stem=STEM,
                     source_sha256=SHA, local_source=src, reels="1-2", gate="g", run=run, log=lambda s: None)
    copies = [c for c in run.calls if c[0] == "rsync" and c[-1].endswith("/inputs/")]
    assert len(copies) == 1 and copies[0][-2] == str(src)


def test_m161_a_failed_step_is_named(tmp_path):
    import pytest
    root = _tree(tmp_path)
    run = _Run(fail=lambda a: a[0] == "ssh" and "render" in a[-1] and "resolve_source" not in a[-1])
    with pytest.raises(RM.RemoteRenderError, match="рендер: код 7"):
        RM.render_remote(CFG, root=root, review=root / "reviews" / f"{STEM}_m157.review.json", stem=STEM,
                         source_sha256=SHA, local_source=None, reels="1", gate="g", run=run, log=lambda s: None)


def test_m161_cmd_render_remote_needs_gate_and_config(tmp_path, capsys):
    from autoreels import __main__ as cli
    from tests.test_montage import REPO_ROOT
    root = _tree(tmp_path)
    (root / "config").mkdir()
    shutil.copy(REPO_ROOT / "config" / "render.yaml", root / "config" / "render.yaml")
    review = root / "reviews" / f"{STEM}_m157.review.json"
    review.write_text(json.dumps({"source": f"{STEM}.mp4", "source_sha256": SHA, "source_hash_scheme": "partial-p1",
                                  "duration_preset": "shorts", "run_key": "r",
                                  "setup": {"setup_id": "t", "crop": {"x": 0, "y": 0, "w": 960, "h": 1700},
                                            "scale": [1080, 1920], "frame": [1920, 1080]},
                                  "reels": [{"id": "r01", "start": 1.0, "end": 20.0, "score": 80, "hook": "h",
                                             "title": "", "description": ""}]}), encoding="utf-8")
    assert cli.cmd_render_remote(str(review), root=root, gate_name=None) == 2
    run = _Run()
    assert cli.cmd_render_remote(str(review), root=root, gate_name="m161", run=run) == 0
    assert any(c[0] == "ssh" and "--reels 1-1" in c[-1] for c in run.calls)
    cfg = (root / "config" / "render.yaml").read_text(encoding="utf-8")
    (root / "config" / "render.yaml").write_text(cfg.replace("  host: gamebox", '  host: ""'), encoding="utf-8")
    assert cli.cmd_render_remote(str(review), root=root, gate_name="m161", run=run) == 2
    assert "не настроен" in capsys.readouterr().err


def test_m161_config_off_in_code_and_gamebox_in_repo():
    from autoreels.core.config import RenderConfig, load_render_config
    from tests.test_montage import REPO_ROOT
    assert RenderConfig.model_fields["remote"].default_factory().host == ""
    r = load_render_config(REPO_ROOT / "config" / "render.yaml", local_path=REPO_ROOT / "nope.yaml").remote
    assert (r.host, r.root, r.encoder, r.profile) == ("gamebox", "/mnt/data/autoreels", "h264_vaapi", "h264")


def test_m161_auto_remote_renders_there(tmp_path, monkeypatch):
    from autoreels import __main__ as cli
    from tests.test_auto import _stub
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    calls = _stub(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "cmd_render_remote", lambda *a, **k: calls.append(("remote", a, k)) or 0)
    assert cli.cmd_auto([str(mpath)], root=tmp_path, remote=True, gate="g") == 0
    names = [c[0] for c in calls]
    assert "remote" in names and "render" not in names
    r = next(c for c in calls if c[0] == "remote")
    assert r[2]["gate_name"] == "g" and r[2]["reels_filter"] == "1-1"


def test_m161_cli_flags():
    from autoreels.__main__ import _build_parser
    p = _build_parser()
    assert p.parse_args(["render", "--manifest", "x", "--gate", "g", "--remote"]).remote is True
    assert p.parse_args(["auto", "x", "--remote"]).remote is True
