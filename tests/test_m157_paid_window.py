"""M157: arl auto on the paid model while the promo credit lasts (autocut.paid_llm / paid_until); --tag keeps an
earlier sheet's drafts."""
from __future__ import annotations

import datetime as dt

from tests.test_auto import _stub


def _kw(calls, name):
    return [c[2] for c in calls if c[0] == name]


def test_m157_repo_config_has_the_window():
    from autoreels.__main__ import load_r0_config
    from autoreels.core.config import AutocutConfig
    from tests.test_montage import REPO_ROOT
    assert AutocutConfig().paid_llm == "" and AutocutConfig().paid_until == ""     # off in code
    ac = load_r0_config(REPO_ROOT / "config" / "r0.yaml").autocut
    assert ac.paid_llm == "sonnet" and dt.date.fromisoformat(ac.paid_until) == dt.date(2026, 11, 2)


def test_m157_inside_the_window_map_judges_posts_run_on_the_paid_model(tmp_path, monkeypatch, capsys):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    calls = _stub(monkeypatch, tmp_path, paid=True)
    assert cli.cmd_auto([str(mpath)], root=tmp_path, today=dt.date(2026, 11, 2)) == 0
    assert _kw(calls, "map")[0]["llm"] == "sonnet" and _kw(calls, "describe")[0]["llm"] == "sonnet"
    ac = _kw(calls, "autocut")[0]
    assert ac["scenario"] is True and ac["llm"] == "sonnet"
    assert "до 2026-11-02 включительно" in capsys.readouterr().out


def test_m157_an_explicit_llm_wins(tmp_path, monkeypatch):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    calls = _stub(monkeypatch, tmp_path, paid=True)
    assert cli.cmd_auto([str(mpath)], root=tmp_path, llm="cloud", today=dt.date(2026, 10, 30)) == 0
    assert _kw(calls, "map")[0]["llm"] == "cloud"


def test_m157_after_the_window_arl_auto_is_free(tmp_path, monkeypatch, capsys):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    calls = _stub(monkeypatch, tmp_path, paid=True)
    assert cli.cmd_auto([str(mpath)], root=tmp_path, today=dt.date(2026, 11, 3)) == 0
    assert _kw(calls, "map")[0]["llm"] == "auto"
    ac = _kw(calls, "autocut")[0]
    assert not ac.get("scenario") and ac["llm"] == "auto"
    assert "срок платных моделей прошёл" in capsys.readouterr().out
    calls.clear()                                      # the scenarist still on request
    assert cli.cmd_auto([str(mpath)], root=tmp_path, mode="scenario", today=dt.date(2026, 11, 3)) == 0
    assert _kw(calls, "autocut")[0]["scenario"] is True


def test_m157_tag_writes_its_own_drafts_and_review_json(tmp_path, monkeypatch):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    old = tmp_path / "reviews" / "v_auto_all.txt"
    old.write_text("# the m154 sheet's draft\n", encoding="utf-8")
    calls = _stub(monkeypatch, tmp_path)
    assert cli.cmd_auto([str(mpath)], root=tmp_path, tag="m157", gate="m157") == 0
    assert _kw(calls, "autocut")[0]["out"].endswith("v_auto_m157.txt")
    applies = [c[1][0] for c in calls if c[0] == "apply"]
    assert applies[0].endswith("v_auto_all_m157.txt")
    assert old.read_text(encoding="utf-8") == "# the m154 sheet's draft\n"
    assert (tmp_path / "reviews" / "v_m157.review.json").is_file()
    render = _kw(calls, "render")[0]
    assert render["manifest_name"].endswith("v_m157.review.json")
    sheet = _kw(calls, "sheet")[0]
    assert sheet["review"].endswith("v_auto_all_m157.txt") and sheet["manifest_file"].endswith("v_m157.review.json")


def test_m157_without_tag_names_are_as_before(tmp_path, monkeypatch):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    calls = _stub(monkeypatch, tmp_path)
    assert cli.cmd_auto([str(mpath)], root=tmp_path) == 0
    assert "out" not in _kw(calls, "autocut")[0]
    assert [c[1][0] for c in calls if c[0] == "apply"][0].endswith("v_auto_all.txt")
    assert _kw(calls, "render")[0]["manifest_name"].endswith("v.review.json")


def test_m157_cli_tag():
    from autoreels.__main__ import _build_parser
    assert _build_parser().parse_args(["auto", "x", "--tag", "m157"]).tag == "m157"
