"""M165: the speaker map (who speaks when) and the interviewer switch of the automatic path."""
from __future__ import annotations

import json

from autoreels.cloud import speakers as SP

TURNS = [[0.0, 10.0, "SPEAKER_01"], [10.0, 12.0, "SPEAKER_00"], [12.0, 30.0, "SPEAKER_01"], [30.0, 31.5, "SPEAKER_02"]]


def test_m165_main_speaker_and_span_speaker():
    sp = SP.build(TURNS, "s" * 64, "test")
    assert sp["main"] == "SPEAKER_01" and sp["version"] == SP.SPEAKERS_VERSION
    assert SP.span_speaker(10.2, 11.8, sp) == "other"          # the host's question
    assert SP.span_speaker(9.0, 13.0, sp) == "main"            # mostly the speaker
    assert SP.span_speaker(30.1, 31.4, sp) == "other"          # audience
    assert SP.span_speaker(40.0, 41.0, sp) is None             # silence in the map
    assert SP.other_refs({"1.1": (0.5, 9.5), "1.2": (10.1, 11.9), "1.3": (12.5, 20)}, sp) == {"1.2"}


def test_m165_load_checks_source_and_version(tmp_path):
    p = tmp_path / "x.speakers.json"
    SP.write(p, SP.build(TURNS, "a" * 64))
    assert SP.load(p, "a" * 64) is not None and SP.load(p, "b" * 64) is None
    d = json.loads(p.read_text())
    d["version"] = 0
    p.write_text(json.dumps(d))
    assert SP.load(p, "a" * 64) is None


def test_m165_rules_for_the_scenarist():
    assert SP.interviewer_rule("") == ""
    assert "never use them" in SP.interviewer_rule("off")
    assert "context" in SP.interviewer_rule("on") and "joke" in SP.interviewer_rule("on")


def _sent():
    # B.k → (t0, t1, text, finished, words)
    s = {}
    t = 100.0
    for k in range(1, 9):
        s[f"5.{k}"] = (t, t + 6.0, f"Фраза номер {k} про практику.", True, 5)
        t += 6.2
    return s


def test_m165_scenario_off_drops_reels_with_the_host_on_keeps_context():
    from autoreels.cloud.autocut import AutoParams
    from autoreels.cloud.scenario import scenario_proposals
    p = AutoParams(min_sec=20, max_sec=90, rhythm=False, end_tone=False, start_pause_min=0)
    sent = _sent()
    scen = [{"refs": [f"5.{k}" for k in range(1, 7)], "hook": None, "title": "Тест", "why": "вопрос → ответ"}]
    other = {"5.1"}
    pool, gone = scenario_proposals(scen, sent, [], p, other=other, interviewer="off")
    assert not pool and "interviewer: off" in gone[0][1]
    pool, gone = scenario_proposals(scen, sent, [], p, other=other, interviewer="on")
    assert len(pool) == 1 and any("ведущий: 5.1" in n for n in pool[0].notes)
    pool, gone = scenario_proposals(scen, sent, [], p, other={"5.1", "5.2", "5.3"}, interviewer="on")
    assert not pool and "половину" in gone[0][1]
    pool, gone = scenario_proposals(scen, sent, [], p, other=other, interviewer="")
    assert len(pool) == 1 and not any("ведущий" in n for n in pool[0].notes)


def test_m165_cmd_speakers_imports_a_diarization(tmp_path, capsys):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    d = tmp_path / "d.json"
    d.write_text(json.dumps({"turns": TURNS}))
    assert cli.cmd_speakers(str(mpath), root=tmp_path, from_json=str(d)) == 0
    out = tmp_path / "transcripts" / f"{mpath.stem}.speakers.json"
    sha = json.loads(mpath.read_text())["source_sha256"]
    assert SP.load(out, sha)["main"] == "SPEAKER_01"
    assert cli.cmd_speakers(str(mpath), root=tmp_path, from_json=str(d)) == 0
    assert "уже есть" in capsys.readouterr().out


def test_m165_config_default_off_in_code_on_in_repo():
    from autoreels.__main__ import load_r0_config
    from autoreels.core.config import AutocutConfig
    from tests.test_montage import REPO_ROOT
    assert AutocutConfig().interviewer == ""
    assert load_r0_config(REPO_ROOT / "config" / "r0.yaml").autocut.interviewer == "off"


def test_m165_override_parses():
    from autoreels.__main__ import _autocut_overrides
    from autoreels.core.config import AutocutConfig
    assert _autocut_overrides(AutocutConfig(), ["interviewer=off"]).interviewer == "off"


def test_m165_auto_switch_goes_to_autocut(tmp_path, monkeypatch):
    from autoreels import __main__ as cli
    from tests.test_auto import _stub
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    calls = _stub(monkeypatch, tmp_path)
    assert cli.cmd_auto([str(mpath)], root=tmp_path, interviewer="off") == 0
    assert [c[2] for c in calls if c[0] == "autocut"][0]["ac_over"] == ["interviewer=off"]
    calls.clear()
    assert cli.cmd_auto([str(mpath)], root=tmp_path) == 0
    assert "ac_over" not in [c[2] for c in calls if c[0] == "autocut"][0]


def test_m165_cli():
    from autoreels.__main__ import _build_parser
    p = _build_parser()
    a = p.parse_args(["speakers", "x", "--from", "d.json"])
    assert a.from_json == "d.json"
    assert p.parse_args(["auto", "x", "--interviewer", "off"]).interviewer == "off"
