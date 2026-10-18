"""M100: longreads from the map's topics — a plan, then each section from its thoughts' words, checked to stay in
the talk — and a crosspost plan of «статья» rows for Telegraph."""
from __future__ import annotations

import csv
import io
import json

from autoreels import __main__ as cli
from autoreels.cloud.article import pick_topics, write_article
from tests.test_montage import _source

T1 = "Маска защищает ребёнка от боли. В детстве маска помогает выжить в семье и в обществе."
T2 = "Взрослому маска мешает. Взрослый человек может снять маску, когда появляется доверие к себе."
T3 = "Доверие к себе растёт, когда вы честны с собой. Честность с собой — основа взросления."
S1 = "Маска защищает ребёнка от боли и помогает выжить в семье. В детстве маска нужна, чтобы выжить в обществе."
S2 = "Взрослому человеку маска мешает. Снять маску можно, когда появляется доверие к себе."


class Answers:
    name = "scripted"

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def complete(self, messages, temperature=0.0):
        self.calls.append(messages)
        a = self.answers.pop(0)
        return a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)


def _map():
    U = lambda i, t0, topic, text, role="thesis", punch=4: {   # noqa: E731
        "id": i, "t0": t0, "t1": t0 + 10, "topic": topic, "text": text, "summary": text.split(".")[0],
        "role": role, "punch": punch}
    return {"topics": [{"id": 1, "name": "Маски и взросление", "units": [1, 2, 3, 4]},
                       {"id": 2, "name": "Служебное", "units": [5, 6, 7]},
                       {"id": 0, "name": "прочее", "units": [8]}],
            "units": [U(1, 0, 1, T1), U(2, 10, 1, T2), U(3, 20, 1, T3), U(4, 30, 1, "Ну да.", punch=1),
                      U(5, 40, 2, "Перерыв.", "aside"), U(6, 50, 2, "Слышно меня?", "aside"),
                      U(7, 60, 2, "Начнём.", "aside"), U(8, 70, 0, T1)]}


def test_topics_for_articles_are_the_real_ones():
    picks = pick_topics(_map(), 3)
    assert [(t["id"], [u["id"] for u in us]) for t, us in picks] == [(1, [1, 2, 3])]   # weak, asides, «прочее» out


def test_article_plan_then_sections_each_checked():
    (t, us), = pick_topics(_map(), 1)
    prov = Answers({"title": "Маска защищает ребёнка, но мешает взрослому",
                    "sections": [{"heading": "Зачем ребёнку маска", "units": [1, 99]},
                                 {"heading": "Квантовая эзотерика", "units": [2]},
                                 {"heading": "Снова маска", "units": [1]}]},
                   {"text": S1},
                   {"text": "Коротко."}, {"text": S2})
    art = write_article(prov, t["name"], us, log=lambda m: None)
    assert art.title == "Маска защищает ребёнка, но мешает взрослому"
    assert [h for h, _ in art.sections] == ["Зачем ребёнку маска", "Взрослому маска мешает"]   # off-talk heading → summary
    assert art.body().splitlines() == ["Зачем ребёнку маска", S1, "Взрослому маска мешает", S2]
    assert "rejected: предложений 1" in prov.calls[3][-1]["content"]                   # one retry with the reason
    assert len(prov.calls) == 4                                                          # unit 1 reused: section 3 skipped
    assert write_article(Answers("нет"), t["name"], us, log=lambda m: None) is None
    one = Answers({"title": "Маски", "sections": [{"heading": "Маска", "units": [1]}]}, {"text": S1})
    assert write_article(one, t["name"], us, log=lambda m: None) is None               # fewer than two sections


def test_cmd_article_writes_markdown_and_a_crosspost_plan(tmp_path, capsys):
    _source(tmp_path)
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    (tmp_path / "transcripts" / "v.map.json").write_text(json.dumps(_map(), ensure_ascii=False), encoding="utf-8")
    prov = Answers({"title": "Маска защищает ребёнка", "sections": [{"heading": "Зачем ребёнку маска", "units": [1]},
                                                                  {"heading": "Взрослому маска мешает", "units": [2]}]},
                   {"text": S1}, {"text": S2})
    assert cli.cmd_article("v", root=tmp_path, provider=prov) == 0
    md = (tmp_path / "export" / "articles" / "v" / "01.md").read_text(encoding="utf-8")
    assert md.startswith("# Маска защищает ребёнка\n\n## Зачем ребёнку маска\n\n" + S1)
    rows = list(csv.reader(io.StringIO((tmp_path / "export" / "crosspost" / "v_articles.csv").read_text(
        encoding="utf-8-sig")), delimiter=";"))
    assert rows[0] == ["файл", "текст", "тип", "заголовок"]
    assert rows[1] == ["", "\n".join(["Зачем ребёнку маска", S1, "Взрослому маска мешает", S2]), "статья",
                       "Маска защищает ребёнка"]
    assert "статей 1 из 1 тем" in capsys.readouterr().out


def test_m101_a_section_over_the_size_is_cut_in_code_not_retried():
    (t, us), = pick_topics(_map(), 1)
    long1 = S1 + " Маска защищает ребёнка. Маска помогает выжить."
    prov = Answers({"title": "Маски", "sections": [{"heading": "Зачем ребёнку маска", "units": [1]},
                                                   {"heading": "Взрослому маска мешает", "units": [2]}]},
                   {"text": long1}, {"text": S2})
    art = write_article(prov, t["name"], us, pmax=3, log=lambda m: None)
    assert art.sections[0][1] == S1 + " Маска защищает ребёнка." and len(prov.calls) == 3
