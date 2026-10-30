"""M200 (blind judges on ab192 + clip checks M199): a reel never opens on a sentence with nothing to stand on — a verb
without a subject («Как было, так и было.», «Всем говорит, и он стоит на этом…», start 1 of 5 from both judges) or
«он/их» before any noun (`autocut.start_morph`, with start_strict; off by default — the previous proposals). And the
answer word is found behind a filler («Ну да, вот я как-то говорил…», «Вот, да, у меня…» — m196 kept both)."""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from autoreels.cloud import clipcheck as C
from autoreels.cloud.autocut import AutoParams, answer_start_reason


def test_off_by_default_and_in_repo_config():
    assert not AutoParams().start_morph
    from autoreels.core.config import AutocutConfig, load_r0_config
    assert not AutocutConfig().start_morph
    ac = load_r0_config(Path(__file__).resolve().parents[1] / "config" / "r0.yaml").autocut
    assert ac.start_morph is False


def test_answer_word_behind_a_filler():
    assert "ответ" in answer_start_reason("Ну да, вот я как-то говорил, что впервые с йогой я познакомился.")
    assert "ответ" in answer_start_reason("Вот, да, у меня даже как получается.")
    assert "ответ" in answer_start_reason("Ну, конечно, перенос — вещь неблагодарная.")
    assert "ответ" in answer_start_reason("Ну наверное.")
    for ok in ("Ну вот.", "Вот так мы и живём.", "Нужно сказать, да, это сложно.", "Ну, здесь какие-то свои правила.",
               "Вот это да.", "Ну, наверное, такая ценность, что ты себя по-настоящему уважаешь."):
        assert answer_start_reason(ok) is None, ok


def test_start_morph_a_subject_in_any_reading():
    pytest.importorskip("pymorphy3")
    assert C.start_morph("У папы был рак, да, царство ему небесное.".split()) is None       # «рак» may be nominative
    assert C.start_morph("Вдохновляет меня то, что ты растёшь как профессионал.".split()) is None   # «то, что…»
    assert "без подлежащего" in C.start_morph("Как было, так и было.".split())
    assert "без подлежащего" in C.start_morph("Всем говорит, и он стоит на этом, ну я же зато не вру.".split())


def test_rule_without_morphology_is_an_error(monkeypatch):
    monkeypatch.setattr(C, "_morph", lambda: None)
    with pytest.raises(RuntimeError, match="pymorphy3"):
        C.require_morph()
    from autoreels.cloud.scenario import scenario_proposals
    p = dataclasses.replace(AutoParams(), min_sec=10.0, max_sec=90.0, rhythm=False, start_strict=True, start_morph=True)
    with pytest.raises(RuntimeError, match="pymorphy3"):
        scenario_proposals([{"refs": ["1.1"]}], {"1.1": (0.0, 30.0, "Каждая система уникальна.", True, 3)}, [], p)


def _sent():
    return {"1.1": (0.0, 9.0, "Человек врёт всем вокруг, даже самым близким.", True, 7),
            "1.2": (9.3, 14.0, "Всем говорит, и он стоит на этом, ну я же зато не вру.", True, 12),
            "1.3": (14.3, 40.0, "А взрослый понимает, что среда не даёт ему говорить правду.", True, 10)}


def test_scenario_start_morph_starts_earlier_off_keeps_it():
    pytest.importorskip("pymorphy3")
    from autoreels.cloud.scenario import scenario_proposals
    p = dataclasses.replace(AutoParams(), min_sec=10.0, max_sec=90.0, rhythm=False, start_strict=True)
    scen = [{"refs": ["1.2", "1.3"]}]
    pool, gone = scenario_proposals(scen, _sent(), [], p)
    assert pool and pool[0].pieces.startswith("1.2")                        # start_morph off: as before
    pm = dataclasses.replace(p, start_morph=True)
    pool, gone = scenario_proposals(scen, _sent(), [], pm)
    assert pool and pool[0].pieces.startswith("1.1") and any("без подлежащего" in n for n in pool[0].notes)
    sent = dict(_sent())
    sent["1.1"] = (0.0, 5.0, "Было и прошло.", True, 3)                     # nothing before stands either
    pool, gone = scenario_proposals(scen, sent, [], pm)
    assert not pool and "раньше начать нельзя" in gone[0][1]
