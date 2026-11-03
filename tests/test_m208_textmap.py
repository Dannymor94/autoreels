"""M208: the map's passport and topics by rules — no model. The cut, times, voice and similar places stay the map's."""
from __future__ import annotations

import json
import re

import pytest

from autoreels.cloud import textmap as T


@pytest.mark.parametrize("text,role", [
    ("Что такое страх? Откуда он берётся?", "question"),
    ("Например, приходит ко мне женщина и говорит о сыне.", "example"),
    ("Это как будто вы идёте по тонкому льду над рекой.", "metaphor"),
    ("Поэтому дышать нужно спокойно и медленно, всегда.", "conclusion"),
    ("Потому что тело помнит всё, что с ним было раньше.", "explanation"),
    ("Ну вот, да.", "aside"),
    ("Страх — это сигнал тела о границе возможностей.", "thesis"),
])
def test_role_by_markers(text, role):
    assert T.rule_role(text) == role


def test_strength_is_ranked_within_the_source():
    raws = [float(x) for x in range(10)]                     # 9 is the strongest
    roles = ["thesis"] * 10
    pn = T.rank_punch(raws, roles)
    assert pn[9] == 5 and sorted(pn, reverse=True)[:3] == [5, 4, 4] and Counter_(pn) == {5: 1, 4: 2, 3: 3, 2: 2, 1: 2}
    roles[9] = "aside"
    assert T.rank_punch(raws, roles)[9] == 1                  # an aside is 1 whatever its rank
    assert T.rank_punch([1.0, 1.0, 1.0], ["thesis"] * 3) == T.rank_punch([1.0, 1.0, 1.0], ["thesis"] * 3)


def Counter_(xs):
    from collections import Counter
    return dict(Counter(xs))


def test_raw_strength_features():
    base = T.punch_raw("Мы долго обсуждали разные варианты этого очень длинного и сложного вопроса сегодня утром.",
                       "explanation", 50)
    assert T.punch_raw("Не страх мешает, а привычка. Всегда так.", "thesis", 50) > base
    assert T.punch_raw("Страх мешает.", "thesis", 90) > T.punch_raw("Страх мешает.", "thesis", 10)


def test_standalone_uses_the_start_rules():
    assert T.rule_standalone("Страх — это сигнал тела. Он помогает.") is True
    assert T.rule_standalone("То есть это так и работает.") is False
    assert T.rule_standalone("Он надевает маски каждый день.") is False


def test_summary_is_the_richest_sentence_without_fillers_but_with_meaning():
    s = T.rule_summary("Ну да. Вот просто тело помнит каждую обиду и каждый страх детства. Так.")
    assert s == "Тело помнит каждую обиду и каждый страх детства."
    assert T.rule_summary("Как бы вы ни старались, привычка сильнее воли.").startswith("Как бы вы ни старались")
    assert len(T.rule_summary("слово " * 80)) <= 160


def test_topics_by_lexical_cohesion():
    a = ["Дыхание успокаивает нервную систему и тело.", "Медленное дыхание снижает пульс и тревогу.",
         "Дыхание животом помогает телу расслабиться.", "Считайте дыхание до четырёх, тело отпустит."] * 2
    b = ["Деньги приходят к тем, кто ценит своё время.", "Заработок растёт, когда время стоит дорого.",
         "Деньги любят счёт и порядок в расходах.", "Время и деньги связаны напрямую у предпринимателя."] * 2
    assert T.rule_topics(a + b, per_topic=8, lo=2) == [1] * 8 + [2] * 8
    tids = T.rule_topics(a + b, per_topic=8)                  # at least 3 topics: the deepest border is still 8|9
    assert len(set(tids)) == 3 and tids[7] != tids[8] and tids == sorted(tids)
    assert T.rule_topics([]) == [] and T.rule_topics(["одна мысль"]) == [1]


def _map():
    texts = ["Страх — это сигнал тела о границе.", "Он помогает выжить в опасности.",
             "Например, приходит ко мне клиент с паникой.", "Поэтому дышать нужно медленно, всегда."]
    return {"version": 1, "stem": "v", "source_sha256": "f" * 64, "model": "groq:x", "transcript_key": "k",
            "topics": [{"id": 1, "name": "страх", "units": [1, 2, 3, 4]}],
            "units": [{"id": i + 1, "t0": float(i * 10), "t1": float(i * 10 + 9), "refs": f"2.{i + 1}", "filtered": "",
                       "text": t, "voice": {"energy": 20 * i}, "similar": [9], "role": "thesis", "punch": 3,
                       "standalone": True, "refers": None, "summary": "модель", "topic": 1} for i, t in enumerate(texts)]}


def test_apply_rules_keeps_the_cut_and_replaces_the_passport():
    m = _map()
    r = T.apply_rules(m)
    assert r["passport"] == "rules" and m["units"][0]["summary"] == "модель"          # the input map is not changed
    for a, b in zip(m["units"], r["units"]):
        assert (a["id"], a["t0"], a["t1"], a["refs"], a["text"], a["voice"], a["similar"]) == \
               (b["id"], b["t0"], b["t1"], b["refs"], b["text"], b["voice"], b["similar"])
    roles = [u["role"] for u in r["units"]]
    assert roles[2] == "example" and roles[3] == "conclusion"
    assert r["units"][1]["standalone"] is False and r["units"][1]["refers"] == 1      # «Он помогает…» leans on #1
    assert {t["id"] for t in r["topics"]} == {u["topic"] for u in r["units"]}
    assert all(1 <= u["punch"] <= 5 for u in r["units"])


def test_autocut_reads_the_map_with_the_rules_passport_only_when_asked(tmp_path, capsys):
    from tests.test_m202_replay_accounting import _scenario_project
    cli, Fake, first, second = _scenario_project(tmp_path)
    mp = tmp_path / "transcripts" / "v.map.json"
    m = json.loads(mp.read_text(encoding="utf-8"))
    for u in m["units"]:                                       # a map whose passport the model never gave
        u.update(role=None, punch=None, standalone=None, refers=None, summary="", missing=True)
    mp.write_text(json.dumps(m), encoding="utf-8")
    kw = dict(root=tmp_path, cache_dir=str(tmp_path / "cache"), check=False, scenario=True, scenario_provider=Fake())
    cfg = tmp_path / "config" / "r0.yaml"
    cfg.write_text(re.sub(r"(?m)^  map_passport: \w+", "  map_passport: model", cfg.read_text(encoding="utf-8")),
                   encoding="utf-8")
    assert cli.cmd_autocut("v", out=str(tmp_path / "reviews" / "a.txt"), **kw) == 1           # model: incomplete
    assert "карта неполна" in capsys.readouterr().err
    cfg.write_text(re.sub(r"(?m)^  map_passport: \w+", "  map_passport: rules", cfg.read_text(encoding="utf-8")),
                   encoding="utf-8")
    assert cli.cmd_autocut("v", out=str(tmp_path / "reviews" / "b.txt"), **kw) == 0
    assert "паспорт и темы по правилам" in capsys.readouterr().out
    assert json.loads(mp.read_text(encoding="utf-8"))["units"][0]["missing"] is True          # the map file stays


def test_code_default_is_the_model_passport_the_repo_config_the_fallback():
    from autoreels import __main__ as cli
    from autoreels.core.config import AutocutConfig
    assert AutocutConfig().map_passport == "model"
    assert cli.load_r0_config("config/r0.yaml").autocut.map_passport == "fallback"      # M209: owner 2026-11-02


def test_the_comparison_tool(tmp_path, monkeypatch, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("map_rules_check", "tools/map_rules_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    (tmp_path / "transcripts").mkdir()
    (tmp_path / "transcripts" / "v.map.json").write_text(json.dumps(_map()), encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    assert mod.main(["v", "нет"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"^v\s+4\s+\d+%", out, re.M) and "нет                нет карты" in out
    assert "роли (модель → правила)" in out and "сила (модель → правила)" in out
