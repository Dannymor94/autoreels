"""M207: the scenarist through any chat — the task one file (exchange/<src>.scenario.md), the chat's answer back
(exchange/<src>.scenario.answer.txt), the same parse and checks; no paid API."""
from __future__ import annotations

from autoreels.cloud import chatscenario as C


def test_task_carries_the_owner_steps_the_rules_the_text_and_its_fingerprint():
    md = C.render_task("v", "0123456789abcdef", "ПРАВИЛА СЦЕНАРИСТА", "[2.1] Текст.")
    assert C.task_key(md) == ("v", "0123456789abcdef")
    assert md.index("Владельцу") < md.index("ЗАДАНИЕ ДЛЯ ЧАТА") < md.index("ПРАВИЛА СЦЕНАРИСТА") < md.index("[2.1] Текст.")
    assert "exchange/v.scenario.answer.txt" in md and "arl scenario-check v" in md
    assert "--scenario-llm chat" in md and C.task_key("нет ключа") is None
    assert C.text_key("a") == C.text_key("a") != C.text_key("b") and len(C.text_key("a")) == 16


def test_answer_and_fix_message(tmp_path):
    assert C.read_answer(tmp_path / "none.txt") is None
    (tmp_path / "e.txt").write_text("  \n", encoding="utf-8")
    assert C.read_answer(tmp_path / "e.txt") is None
    ok = C.render_fix("v", 3, [])
    assert "все строки приняты (3)" in ok
    fix = C.render_fix("v", 2, [("", "нет таких фраз 99.1: 99.1-3"), ("2.5-8", "короче min_sec")])
    assert "принято 2, не принято 2" in fix and "пришли заново ВСЕ строки" in fix
    assert "- нет таких фраз 99.1: 99.1-3" in fix and "- короче min_sec: `2.5-8`" in fix


def _project(tmp_path):
    from tests.test_m202_replay_accounting import _scenario_project
    cli, _Fake, first, second = _scenario_project(tmp_path)
    kw = dict(root=tmp_path, cache_dir=str(tmp_path / "cache"), check=False, llm="none", scenario=True,
              scenario_llm="chat")
    return cli, kw, first, second


def test_no_answer_writes_the_task_and_stops(tmp_path, capsys):
    cli, kw, first, second = _project(tmp_path)
    out = tmp_path / "reviews" / "v_chat.txt"
    assert cli.cmd_autocut("v", out=str(out), **kw) == 3
    task, answer, _fix = C.paths(tmp_path, "v")
    md = task.read_text(encoding="utf-8")
    stem, key = C.task_key(md)
    assert stem == "v" and len(key) == 16 and "\n2.1 [" in md and not out.exists()
    assert "ответа чата ещё нет" in capsys.readouterr().out


def test_the_answer_goes_through_the_same_checks_and_the_check_writes_a_message(tmp_path, capsys):
    cli, kw, first, second = _project(tmp_path)
    assert cli.cmd_autocut("v", **kw) == 3
    task, answer, fix = C.paths(tmp_path, "v")
    answer.write_text(f"```\nM | {first} | t: Первая | why: a\nM | 99.1-3 | t: Чужая | why: b\n"
                      f"**M | {second} | t: Вторая | why: c**\n```\n", encoding="utf-8")
    assert cli.cmd_autocut("v", chat_check=True, **kw) == 0
    text = fix.read_text(encoding="utf-8")
    assert "принято 2, не принято 1" in text and "нет таких фраз 99.1" in text
    out = tmp_path / "reviews" / "v_chat.txt"
    capsys.readouterr()
    assert cli.cmd_autocut("v", out=str(out), **kw) == 0
    reels = [ln.split(" | ")[1] for ln in out.read_text(encoding="utf-8").splitlines() if ln.startswith("M")]
    assert reels == [first, second] and "ответ из exchange/v.scenario.answer.txt" in capsys.readouterr().out


def test_an_answer_to_another_text_is_not_used(tmp_path, capsys):
    cli, kw, first, second = _project(tmp_path)
    assert cli.cmd_autocut("v", **kw) == 3
    task, answer, _fix = C.paths(tmp_path, "v")
    md = task.read_text(encoding="utf-8")
    stem, key = C.task_key(md)
    task.write_text(md.replace(key, "f" * 16), encoding="utf-8")     # the task of another (older) text
    answer.write_text(f"M | {first} | t: Первая | why: a\n", encoding="utf-8")
    assert cli.cmd_autocut("v", **kw) == 3
    assert C.task_key(task.read_text(encoding="utf-8")) == ("v", key)    # the task is written again for this text
    assert "написан к другому тексту" in capsys.readouterr().out


def test_auto_with_the_chat_waits_and_does_not_fall_back_to_autocut(tmp_path, monkeypatch, capsys):
    import datetime as dt
    from autoreels import __main__ as cli
    from tests.test_auto import _stub
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    calls = _stub(monkeypatch, tmp_path)

    def waiting(m, **k):
        calls.append(("autocut", (m,), k))
        return 3
    monkeypatch.setattr(cli, "cmd_autocut", waiting)
    rc = cli.cmd_auto([str(mpath)], root=tmp_path, scenario_llm="chat", today=dt.date(2027, 1, 1))  # paid window over
    out = capsys.readouterr().out
    kws = [c[2] for c in calls if c[0] == "autocut"]
    assert rc == 1 and len(kws) == 1                                   # the chat only — no autocut in its place
    assert kws[0]["scenario"] is True and kws[0]["scenario_llm"] == "chat" and kws[0]["llm"] != "chat"
    assert "сценарист через чат" in out and "ждёт ответа чата: exchange/" in out and "взят автомонтаж" not in out
    assert not any(c[0] == "apply" for c in calls)


def test_the_chat_never_polishes():
    from autoreels import __main__ as cli
    from autoreels.core.config import AutocutConfig
    assert cli._scenario_autocut_llms(AutocutConfig(), "cloud", "chat") == {"llm": "cloud", "scenario_llm": "chat"}
