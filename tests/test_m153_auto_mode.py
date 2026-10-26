"""M153: who writes the reels in arl auto — the scenarist (owner 2026-10-26, config) or the free autocut."""
from __future__ import annotations

from tests.test_auto import _stub


def _autocut_kw(calls):
    return [c[2] for c in calls if c[0] == "autocut"]


def _set_mode(tmp_path, mode):
    cfg = tmp_path / "config" / "r0.yaml"
    text = cfg.read_text(encoding="utf-8")
    assert "  auto_mode: scenario\n" in text
    cfg.write_text(text.replace("  auto_mode: scenario\n", f"  auto_mode: {mode}\n"), encoding="utf-8")


def test_m153_config_default_is_off_in_code_and_scenario_in_repo_config():
    from autoreels.core.config import AutocutConfig
    from autoreels.__main__ import load_r0_config
    from tests.test_montage import REPO_ROOT
    assert AutocutConfig().auto_mode == "autocut"          # flag off in code = the M63 sequence
    ac = load_r0_config(REPO_ROOT / "config" / "r0.yaml").autocut
    assert ac.auto_mode == "scenario" and ac.scenario_llm == "sonnet"


def test_m153_auto_uses_the_scenarist_with_its_named_model(tmp_path, monkeypatch, capsys):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    calls = _stub(monkeypatch, tmp_path)
    assert cli.cmd_auto([str(mpath)], root=tmp_path) == 0
    kw = _autocut_kw(calls)
    assert len(kw) == 1 and kw[0]["scenario"] is True and kw[0]["llm"] == "sonnet"
    assert next(c for c in calls if c[0] == "map")[2]["llm"] == "auto"     # the map stays on the free models
    assert "сценарист (sonnet)" in capsys.readouterr().out


def test_m153_mode_autocut_is_the_m63_sequence(tmp_path, monkeypatch):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    _set_mode(tmp_path, "autocut")
    calls = _stub(monkeypatch, tmp_path)
    assert cli.cmd_auto([str(mpath)], root=tmp_path) == 0
    kw = _autocut_kw(calls)
    assert len(kw) == 1 and not kw[0].get("scenario") and kw[0]["llm"] == "auto"


def test_m153_cli_mode_overrides_the_config(tmp_path, monkeypatch):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    calls = _stub(monkeypatch, tmp_path)
    assert cli.cmd_auto([str(mpath)], root=tmp_path, mode="autocut") == 0
    assert not _autocut_kw(calls)[0].get("scenario")
    calls.clear()
    _set_mode(tmp_path, "autocut")
    assert cli.cmd_auto([str(mpath)], root=tmp_path, mode="scenario", scenario_llm="haiku") == 0
    kw = _autocut_kw(calls)[0]
    assert kw["scenario"] is True and kw["llm"] == "haiku"


def test_m153_scenarist_failure_falls_back_to_the_free_autocut(tmp_path, monkeypatch, capsys):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    calls = _stub(monkeypatch, tmp_path)
    inner = cli.cmd_autocut

    def autocut(m, **k):
        if k.get("scenario"):
            calls.append(("autocut", (m,), k))
            return 1
        return inner(m, **k)
    monkeypatch.setattr(cli, "cmd_autocut", autocut)
    assert cli.cmd_auto([str(mpath)], root=tmp_path) == 0
    kw = _autocut_kw(calls)
    assert [bool(k.get("scenario")) for k in kw] == [True, False] and kw[1]["llm"] == "auto"
    out = capsys.readouterr().out
    assert "сценарист не ответил" in out and "автомонтаж" in out


def test_m153_cli_parser_has_mode_and_scenario_llm():
    from autoreels.__main__ import _build_parser as build_parser
    a = build_parser().parse_args(["auto", "x.mp4", "--mode", "autocut", "--scenario-llm", "haiku"])
    assert a.mode == "autocut" and a.scenario_llm == "haiku"
    a = build_parser().parse_args(["auto", "x.mp4"])
    assert a.mode is None and a.scenario_llm is None
