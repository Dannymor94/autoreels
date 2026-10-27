"""M170: arl auto builds the speaker map itself (once, non-fatal)."""
from __future__ import annotations

from tests.test_auto import _stub


def test_m170_auto_runs_the_speaker_stage_after_the_map(tmp_path, monkeypatch):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    calls = _stub(monkeypatch, tmp_path, speakers=True)
    monkeypatch.setattr(cli, "cmd_speakers", lambda m, **k: calls.append(("speakers", (m,), k)) or 0)
    assert cli.cmd_auto([str(mpath)], root=tmp_path) == 0
    names = [c[0] for c in calls]
    assert names.index("map") < names.index("speakers") < names.index("autocut")
    assert next(c for c in calls if c[0] == "speakers")[2]["python"] == "~/.venvs/m141/bin/python"


def test_m170_a_failed_speaker_map_does_not_stop_the_source(tmp_path, monkeypatch, capsys):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    calls = _stub(monkeypatch, tmp_path, speakers=True)
    monkeypatch.setattr(cli, "cmd_speakers", lambda m, **k: 2)
    assert cli.cmd_auto([str(mpath)], root=tmp_path) == 0
    assert "autocut" in [c[0] for c in calls]
    assert "карта говорящих не построена" in capsys.readouterr().out


def test_m170_off_by_default_in_code():
    from autoreels.core.config import AutocutConfig
    assert AutocutConfig().speakers_auto is False and AutocutConfig().speakers_python == ""
