"""M63: arl auto — a source end to end (stages in order, combined draft, stop on failure)."""
from __future__ import annotations

from pathlib import Path


def _stub(monkeypatch, tmp_path, *, apply_rc=(0,), fail=None):
    from autoreels import __main__ as cli
    calls = []

    def rec(name, rc=0):
        def f(*a, **k):
            calls.append((name, a, k))
            return 1 if fail == name else rc
        return f
    monkeypatch.setattr(cli, "cmd_prepare", rec("prepare"))
    monkeypatch.setattr(cli, "cmd_tx_check", rec("tx-check"))
    monkeypatch.setattr(cli, "cmd_map", rec("map"))

    def autocut(m, **k):
        calls.append(("autocut", (m,), k))
        (tmp_path / "reviews" / "v_auto_m56.txt").write_text(
            "# head\n# fingerprint: abc\n\n# --- M1\nM1 80 | 2.1-3 | t: Тест\n", encoding="utf-8")
        return 0
    monkeypatch.setattr(cli, "cmd_autocut", autocut)
    rcs = list(apply_rc)

    def apply(path, **k):
        calls.append(("apply", (path,), k))
        (tmp_path / "reviews" / "v.review.json").write_text(_manifest_json(), encoding="utf-8")
        return rcs.pop(0) if rcs else 0
    monkeypatch.setattr(cli, "_blocks_do_apply", apply)
    monkeypatch.setattr(cli, "cmd_render", lambda **k: calls.append(("render", (), k)) or [Path("x.mp4")])
    monkeypatch.setattr(cli, "cmd_review_sheet", rec("sheet"))
    return calls


def _manifest_json():
    import json
    return json.dumps({"source": "v.mp4", "source_sha256": "f" * 64, "source_hash_scheme": "partial-p1",
                       "duration_preset": "shorts", "run_key": "r",
                       "setup": {"setup_id": "t", "crop": {"x": 0, "y": 0, "w": 960, "h": 1700},
                                 "scale": [1080, 1920], "frame": [1920, 1080]},
                       "reels": [{"id": "r01", "start": 1.0, "end": 20.0, "score": 80, "hook": "h",
                                  "title": "", "description": ""}]})


def test_auto_runs_every_stage_in_order_and_merges_the_drafts(tmp_path, monkeypatch, capsys):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    (tmp_path / "reviews" / "v_auto.txt").write_text("# label head\n# fingerprint: abc\n# format: compact\n2 80\n",
                                                     encoding="utf-8")
    calls = _stub(monkeypatch, tmp_path)
    assert cli.cmd_auto([str(mpath)], root=tmp_path, music="pad.m4a", gate="g1") == 0
    names = [c[0] for c in calls]
    assert names == ["prepare", "tx-check", "map", "autocut", "apply", "render", "sheet"]
    combined = (tmp_path / "reviews" / "v_auto_all.txt").read_text(encoding="utf-8")
    assert combined.startswith("# label head") and "2 80" in combined and "M1 80 | 2.1-3" in combined
    assert combined.count("# fingerprint:") == 1
    render = next(c for c in calls if c[0] == "render")[2]
    assert render["gate_name"] == "g1" and render["music"] == "pad.m4a" and render["reels_filter"] == "1-1"
    assert "✓ v: готово" in capsys.readouterr().out


def test_auto_falls_back_to_the_autocut_draft(tmp_path, monkeypatch, capsys):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    (tmp_path / "reviews" / "v_auto.txt").write_text("# h\n\n2 80\n", encoding="utf-8")
    calls = _stub(monkeypatch, tmp_path, apply_rc=(1, 0))
    assert cli.cmd_auto([str(mpath)], root=tmp_path) == 0
    applies = [c[1][0] for c in calls if c[0] == "apply"]
    assert applies[0].endswith("v_auto_all.txt") and applies[1].endswith("v_auto_m56.txt")
    assert "взят только черновик сборок" in capsys.readouterr().out


def test_auto_stops_a_source_at_a_failed_stage(tmp_path, monkeypatch, capsys):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    calls = _stub(monkeypatch, tmp_path, fail="map")
    assert cli.cmd_auto([str(mpath), "nope"], root=tmp_path) == 1
    assert [c[0] for c in calls] == ["prepare", "tx-check", "map"]
    out = capsys.readouterr().out
    assert "✗ v: остановлен на «map»" in out and "✗ nope: остановлен на «manifest»" in out


def test_auto_starts_from_a_video_with_arl_run(tmp_path, monkeypatch):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"VIDEO")
    seen = []
    monkeypatch.setattr(cli, "cmd_run", lambda v, **k: seen.append((v, k)) or mpath)
    calls = _stub(monkeypatch, tmp_path)
    assert cli.cmd_auto([str(video)], root=tmp_path, render=False) == 0
    assert seen and seen[0][1]["archive"] is False
    assert [c[0] for c in calls][:1] == ["prepare"] and "render" not in [c[0] for c in calls]


def test_auto_tx_switch_sets_the_backend_for_a_new_video(tmp_path, monkeypatch):
    import os
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"VIDEO")
    seen = []
    monkeypatch.setenv("TRANSCRIBE_BACKEND", "groq")     # teardown restores the original (cmd_auto sets it)
    monkeypatch.setattr(cli, "cmd_run", lambda v, **k: seen.append(os.environ.get("TRANSCRIBE_BACKEND")) or mpath)
    _stub(monkeypatch, tmp_path)
    assert cli.cmd_auto([str(video)], root=tmp_path, render=False, tx="local") == 0
    assert seen == ["whispercpp"]
