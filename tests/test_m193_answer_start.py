"""M193 (blind judges on ab192: automatic reels open on answers to a question the viewer never heard — «Да, у меня даже
как…»): with start_strict and answer_start, a reel never opens on an answer word or on the reply right after the
interviewer's sentence (unless it is a question or repeats the question). Off by default: the previous proposals."""
from __future__ import annotations

import dataclasses
from pathlib import Path

from autoreels.cloud.autocut import AutoParams, answer_start_reason


def test_off_by_default_on_in_repo_config():   # M196: owner 2026-10-30 «давай» — on in config/r0.yaml
    assert not AutoParams().answer_start
    from autoreels.core.config import AutocutConfig
    assert not AutocutConfig().answer_start
    from autoreels.core.config import load_r0_config
    ac = load_r0_config(Path(__file__).resolve().parents[1] / "config" / "r0.yaml").autocut
    assert ac.answer_start is True and ac.answer_gap_sec == 3.0


def test_answer_words():
    assert "ответ" in answer_start_reason("Да, у меня даже как получается.")
    assert "ответ" in answer_start_reason("Нет. Это совсем другое.")
    assert "ответ" in answer_start_reason("Конечно, перенос — вещь неблагодарная.")
    assert "ответ" in answer_start_reason("Наверное, да.")
    assert answer_start_reason("Наверное, такая ценность, что ты по-настоящему себя ценишь, что ты себя уважаешь.") is None
    assert answer_start_reason("Дайте себе место в этом мире.") is None        # «Да…» inside a word is not «да»
    assert answer_start_reason("Настоящие друзья не говорят, что ты не прав.") is None


def test_reply_to_the_host():
    q = "А какие бы ты мини-практики мог бы посоветовать зрителям?"
    assert "ведущего" in answer_start_reason("Знаете, когда ко мне приходит человек, он возбуждён.", q)
    assert answer_start_reason("Как ты отдыхаешь?", "Как ты восстанавливаешь себя?") is None          # a question
    assert answer_start_reason("Мини-практики, которые я советую зрителям, очень просты.", q) is None   # repeats it
    assert answer_start_reason("Знаете, когда ко мне приходит человек, он возбуждён.", "") is None      # no host


def _sent():
    return {"1.1": (0.0, 6.0, "Мы с вами сегодня говорим о стрессе и о теле.", True, 9),
            "1.2": (6.3, 12.0, "А что ты советуешь зрителям в сложной ситуации?", True, 8),
            "1.3": (12.8, 40.0, "Знаете, когда ко мне приходит человек, он очень возбуждён.", True, 9),
            "1.4": (40.3, 60.0, "Первое, что мы делаем, это уходим в тело и чувствуем сигнал.", True, 11)}


def test_scenario_drops_a_reply_to_the_host_off_keeps_it():
    from autoreels.cloud.scenario import scenario_proposals
    p = dataclasses.replace(AutoParams(), min_sec=10.0, max_sec=90.0, rhythm=False, start_strict=True)
    scen = [{"refs": ["1.3", "1.4"], "title": "Тело"}]
    pool, gone = scenario_proposals(scen, _sent(), [], p, other={"1.2"}, interviewer="off")
    assert pool and pool[0].pieces.startswith("1.3")                       # answer_start off: as before
    pa = dataclasses.replace(p, answer_start=True)
    pool, gone = scenario_proposals(scen, _sent(), [], pa, other={"1.2"}, interviewer="off")
    assert not pool and "ведущего" in gone[0][1]                            # the host's line may not be added (off)
    pool, gone = scenario_proposals(scen, _sent(), [], dataclasses.replace(pa, answer_gap_sec=0.5),
                                    other={"1.2"}, interviewer="off")
    assert pool                                                             # 0.8 s after the host > gap: not a reply


def test_scenario_answer_word_gets_an_earlier_start():
    from autoreels.cloud.scenario import scenario_proposals
    sent = {"1.1": (0.0, 8.0, "Мне вообще хотелось сделать книгу как самодиагностику.", True, 8),
            "1.2": (8.2, 12.0, "Да, у меня даже как получается.", True, 6),
            "1.3": (12.3, 40.0, "Она уже привыкла и отключается сама по себе.", True, 9)}   # M197: leans back — no later start
    p = dataclasses.replace(AutoParams(), min_sec=10.0, max_sec=90.0, rhythm=False, start_strict=True,
                            answer_start=True)
    pool, gone = scenario_proposals([{"refs": ["1.2", "1.3"]}], sent, [], p)
    assert pool and pool[0].pieces.startswith("1.1") and any("ответ" in n for n in pool[0].notes)


def test_m197_an_answer_word_start_moves_one_sentence_later_when_that_one_stands():
    """m196: «Да, если брать восстановление… Как ты отдыхаешь? А я и не работаю…» — the whole reel went (the host's
    question before it may not be added); it starts at «Как ты отдыхаешь?» instead."""
    from autoreels.cloud.scenario import scenario_proposals
    sent = {"1.1": (0.0, 5.0, "Как ты восстанавливаешь себя в жизни?", True, 6),
            "1.2": (5.5, 12.0, "Да, если брать восстановление, то есть такая штука интересная.", True, 9),
            "1.3": (12.3, 14.0, "Как ты отдыхаешь?", True, 3),
            "1.4": (14.3, 40.0, "А я и не работаю, когда работа мне по душе.", True, 9)}
    p = dataclasses.replace(AutoParams(), min_sec=10.0, max_sec=90.0, rhythm=False, start_strict=True,
                            answer_start=True)
    pool, gone = scenario_proposals([{"refs": ["1.2", "1.3", "1.4"]}], sent, [], p, other={"1.1"}, interviewer="off")
    assert pool and pool[0].pieces.startswith("1.3") and any("следующей фразы" in n for n in pool[0].notes)
    pool, gone = scenario_proposals([{"refs": ["1.2", "1.3", "1.4"]}], sent, [],
                                    dataclasses.replace(p, min_sec=30.0), other={"1.1"}, interviewer="off")
    assert not pool                                  # later start too short (27.7 s < 30): the reel goes as before
    pool, gone = scenario_proposals([{"refs": ["1.2", "1.3", "1.4"]}], sent, [],
                                    dataclasses.replace(p, answer_start=False), other={"1.1"}, interviewer="off")
    assert pool and pool[0].pieces.startswith("1.2")  # answer_start off: as before
