"""M54: arl map — the map of a whole source (cloud/thoughtmap.py, local/map_page.py).

1. Thoughts: finished sentences, split at pauses, 8–30 s, never past the maximum; review numbering
   B.k per sentence, a unit written as montage pieces.
2. Voice: energy is the percentile of level + pitch range + rate within the source.
3. Passports (LLM): every unit described or retried once, then marked missing; invalid answers
   (unknown role, punch out of range, refers forward) are not taken.
4. Topics (LLM): each unit in one topic; the rest go to «прочее».
5. Similar: the same thought said far apart is found; near units are not listed.
6. The page and the CLI end to end (scripted model).
"""
import json
from types import SimpleNamespace

import pytest

from autoreels import __main__ as cli
from autoreels.cloud.thoughtmap import (
    MapParams, Sentence, Unit, build_map, describe_units, similar_units, split_units, topic_units,
    unit_refs, voice_scores,
)
from autoreels.core.models import Word
from autoreels.local.map_page import build_map_page

from tests.test_label import Scripted


def _s(text, a, b, ref=None, complete=True):
    ws = [Word(word=x, t0=a, t1=b) for x in text.split()]
    return Sentence(words=ws, a=a, b=b, ref=ref, complete=complete)


def test_units_close_after_a_finished_sentence_at_a_pause():
    p = MapParams(unit_min_sec=8, unit_max_sec=30, unit_max_sents=4, pause_split_sec=1.0)
    ss = [_s("Раз.", 0, 5, "1.1"), _s("Два.", 5.2, 9, "1.2"),          # 9 s, then a 2 s pause → close
          _s("Три", 11, 15, "1.3", complete=False), _s("четыре.", 15.1, 20, "2.1"),   # not before the finished one
          _s("Пять.", 20.2, 25, "2.2"), _s("Шесть.", 25.1, 30, "2.3"), _s("Семь.", 30.1, 33, "2.4"),
          _s("Восемь.", 34, 70, "2.5")]                                 # a long sentence alone
    units = split_units(ss, p)
    assert [[x.text for x in u.sents] for u in units] == [
        ["Раз.", "Два."], ["Три", "четыре.", "Пять.", "Шесть."], ["Семь."], ["Восемь."]]
    assert unit_refs(units[1]) == "1.3 2.1-3"
    assert [u.id for u in units] == [1, 2, 3, 4]


def test_unit_never_grows_past_the_maximum():
    p = MapParams(unit_min_sec=8, unit_max_sec=20, unit_max_sents=9, pause_split_sec=5)
    ss = [_s(f"Фраза{i}.", 6 * i, 6 * i + 5.5, f"1.{i + 1}") for i in range(7)]
    units = split_units(ss, p)
    assert all(u.t1 - u.t0 <= 20 for u in units) and sum(len(u.sents) for u in units) == 7


def test_refs_skip_filtered_blocks():
    u = Unit(1, [_s("А.", 0, 1, None), _s("Б.", 1, 2, "4.1"), _s("В.", 2, 3, "4.2"), _s("Г.", 3, 4, "5.1")])
    assert unit_refs(u) == "4.1-2 5.1"


def test_energy_is_a_percentile_within_the_source():
    units = [Unit(i + 1, [_s("слово " * 10, 10 * i, 10 * i + 8)]) for i in range(5)]
    vals = {1: (-30, 2, 0), 2: (-25, 4, 0), 3: (-20, 6, 0), 4: (-28, 3, 0), 5: (-18, 9, 0)}
    voice_scores(units, lambda a, b: {"level_db": vals[int(a // 10) + 1][0], "pitch_st": 0.0,
                                      "range_st": vals[int(a // 10) + 1][1]})
    en = [u.info["voice"]["energy"] for u in units]
    assert en[4] == 100 and en[0] == 0 and en[2] > en[1] > en[3]
    assert units[0].info["voice"]["rate"] == pytest.approx(10 / 8, abs=0.01)
    none = [Unit(1, [_s("а б", 0, 5)])]
    voice_scores(none, None)
    assert none[0].info["voice"]["energy"] is None and none[0].info["voice"]["level_db"] is None


def _units(n):
    return [Unit(i + 1, [_s(f"Мысль номер {i + 1}.", 20 * i, 20 * i + 15, f"{i + 1}.1")]) for i in range(n)]


def _pp(uid, **kw):
    e = {"id": uid, "role": "thesis", "punch": 3, "standalone": True, "refers": None, "summary": f"итог {uid}"}
    e.update(kw)
    return e


def test_passports_validated_retried_then_missing():
    units = _units(5)
    first = {"units": [_pp(1), _pp(2, role="joke"), _pp(3, punch=9), _pp(4, refers=5, standalone=False),
                       _pp(9)]}                                   # 2, 3 invalid; 5 unanswered; 9 not asked
    retry = {"units": [_pp(2, role="example"), _pp(3, punch=5, refers="#1", standalone=False)]}
    prov = Scripted([first, retry])
    done, missing = describe_units(units, prov, system="S", p=MapParams(window_units=20), log=lambda m: None)
    assert (done, missing) == (4, 1)
    i = {u.id: u.info for u in units}
    assert i[1]["role"] == "thesis" and i[2]["role"] == "example" and i[3]["punch"] == 5 and i[3]["refers"] == 1
    assert i[4]["refers"] is None                                  # forward reference dropped
    assert i[5].get("missing") and i[5]["role"] is None
    asked = prov.calls[1][-1]["content"]
    assert "#2 " in asked and "#5 " in asked and "#1 " not in asked.split("Describe")[1]


def test_windows_carry_context_and_a_provider_failure_is_not_fatal():
    units = _units(5)
    prov = Scripted([{"units": [_pp(1), _pp(2)]}, RuntimeError("429"), {"units": [_pp(5)]},
                     {"units": [_pp(3), _pp(4)]}])               # the retry round asks for 3 and 4
    done, missing = describe_units(units, prov, system="S", p=MapParams(window_units=2), log=lambda m: None)
    assert (done, missing) == (5, 0)
    second = prov.calls[1][-1]["content"]
    assert second.startswith("Context") and "#1 " in second and "#3 " in second


def test_topics_cover_every_unit():
    units = _units(6)
    for u in units:
        u.info["summary"] = f"кратко {u.id}"
    ans = {"topics": [{"name": "Маски", "units": [1, 2, "#3"]}, {"name": "Дыхание", "units": [3, 4, 99]}, {"name": "", "units": [5]}]}
    topics = topic_units(units, Scripted([ans]), system="S", log=lambda m: None)
    assert [(t["id"], t["name"], t["units"]) for t in topics] == [(1, "Маски", [1, 2, 3]), (2, "Дыхание", [4]),
                                                                 (0, "прочее", [5, 6])]
    assert [u.info["topic"] for u in units] == [1, 1, 1, 2, 0, 0]


def test_topics_of_a_long_source_by_parts_then_merged():
    """M84 (G7: one TOPICS request over a whole long source timed out): parts of consecutive units, each
    retried once; the same theme found in several parts is merged; the request of a short source is one."""
    units = _units(7)
    for u in units:
        u.info["summary"] = f"кратко {u.id}"
    prov = Scripted([{"topics": [{"name": "Маски", "units": [1, 2]}, {"name": "Дыхание", "units": [3]}]},
                     TimeoutError("read timed out"),                                   # part 2: retried
                     {"topics": [{"name": "Маски снова", "units": [4, 5, 6, 1]}]},     # 1 is not in this part
                     {"topics": [{"name": "Тело", "units": [7]}]},
                     {"topics": [{"name": "Маски", "parts": ["T1", "T3"]}, {"name": "Дыхание и тело", "parts": [2, 4]}]}])
    logs = []
    topics = topic_units(units, prov, system="S", log=logs.append, chunk=3)
    assert [c[-1]["content"].split(" (")[0].split(".")[0] for c in prov.calls] == [
        "TOPICS of part 1 of 3 of the source", "TOPICS of part 2 of 3 of the source",
        "TOPICS of part 2 of 3 of the source", "TOPICS of part 3 of 3 of the source", "MERGE TOPICS"]
    assert "T3 [part 2] Маски снова: кратко 4; кратко 5; кратко 6" in prov.calls[-1][-1]["content"]
    assert [(t["id"], t["name"], t["units"]) for t in topics] == [(1, "Маски", [1, 2, 4, 5, 6]),
                                                                 (2, "Дыхание и тело", [3, 7])]
    assert [u.info["topic"] for u in units] == [1, 1, 2, 1, 1, 1, 2]
    assert any("слияние — 2 тем из 4" in m for m in logs)
    one = Scripted([{"topics": [{"name": "Маски", "units": [1, 2, 3, 4, 5, 6, 7]}]}])
    topic_units(units, one, system="S", log=lambda m: None, chunk=10)
    assert len(one.calls) == 1 and one.calls[0][-1]["content"].startswith("TOPICS of the whole source")


def test_topics_part_without_answer_is_marked_and_a_failed_merge_keeps_the_parts():
    """M84: a part with no answer after the retry → topic −1 «без ответа» and the map is incomplete (arl map
    asks again); no merge answer → the parts' topics stay apart; nothing at all → «темы не получены»."""
    units = _units(4)
    for u in units:
        u.info.update(summary=f"кратко {u.id}", role="thesis")
    topics = topic_units(units, Scripted([{"topics": [{"name": "Маски", "units": [1, 2]}]},
                                          TimeoutError("t"), "не JSON"]), system="S", log=lambda m: None, chunk=2)
    assert [(t["id"], t["name"], t["units"]) for t in topics] == [(1, "Маски", [1, 2]), (-1, "без ответа", [3, 4])]
    m = build_map(units, stem="v", source_sha256="f" * 64, topics=topics)
    assert cli._map_gaps(m) == ["темы: без ответа для 2 мыслей"]
    assert cli._map_gaps(m, topics=False) == []                       # autocut does not wait for topics
    assert "без ответа" in build_map_page(m)
    topics = topic_units(units, Scripted([{"topics": [{"name": "А", "units": [1, 2]}]},
                                          {"topics": [{"name": "Б", "units": [3, 4]}]}, "нет", TimeoutError("t")]),
                         system="S", log=lambda m: None, chunk=2)
    assert [(t["id"], t["name"], t["units"]) for t in topics] == [(1, "А", [1, 2]), (2, "Б", [3, 4])]
    topics = topic_units(units, Scripted(["нет"] * 4), system="S", log=lambda m: None, chunk=2)
    assert [(t["id"], t["units"]) for t in topics] == [(0, [1, 2, 3, 4])]
    assert cli._map_gaps(build_map(units, stem="v", source_sha256="f" * 64, topics=topics)) == ["темы не получены"]


def test_similar_finds_the_same_thought_far_away_only():
    texts = ["Ваша нервная система сжимается под давлением родителей и школы.",
             "Сегодня мы дышим глубоко и быстро, это холотропное дыхание.",
             "Нервная система сжимается, когда давят родители, школа, институт.",
             "Нервную систему сжимают родители — это давление."]
    t0 = [0, 300, 900, 930]
    units = [Unit(i + 1, [_s(t, t0[i], t0[i] + 10)]) for i, t in enumerate(texts)]
    similar_units(units, MapParams(similar_min=0.2, similar_far_sec=60))
    sim1 = [i for i, _ in units[0].info["similar"]]
    assert sim1[:1] == [3] and 2 not in sim1
    assert 4 not in [i for i, _ in units[2].info["similar"]]      # 30 s apart — not listed


def test_map_and_page():
    units = _units(3)
    for u in units:
        u.info.update(role="conclusion", punch=5, standalone=u.id != 3, refers=1 if u.id == 3 else None,
                      summary=f"итог <{u.id}>", topic=1, voice={"energy": 70}, similar=[[1, 0.41]] if u.id == 3 else [])
    m = build_map(units, stem="v", source_sha256="x", topics=[{"id": 1, "name": "Маски", "units": [1, 2, 3]}], model="m")
    assert m["units"][2]["refs"] == "3.1" and m["units"][2]["refers"] == 1
    page = build_map_page(m)
    assert page.count('class="u') == 3 and "Маски · 3" in page and "★★★★★" in page and "вывод" in page
    assert "итог &lt;3&gt;" in page and 'опирается на <a href="#u1">#1</a>' in page and "похоже:" in page


def test_cmd_map_end_to_end(tmp_path, capsys):
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "map_system.md").write_text("S", encoding="utf-8")

    class Model:
        name = "scripted"

        def __init__(self):
            self.calls = 0

        def complete(self, messages, temperature=0.0):
            self.calls += 1
            q = messages[-1]["content"]
            if q.startswith("TOPICS"):
                ids = [int(x[1:]) for x in q.split() if x.startswith("#") and x[1:].isdigit()]
                return json.dumps({"topics": [{"name": "Всё", "units": ids}]})
            part = q.split("Describe EVERY one of these units:")[1]
            ids = [int(x[1:]) for x in part.split() if x.startswith("#") and x[1:].isdigit()]
            return json.dumps({"units": [_pp(i) for i in ids]})

    model = Model()
    rc = cli.cmd_map(str(mpath), root=tmp_path, cache_dir=str(tmp_path / "cache"), provider=model,
                     out_dir=str(tmp_path / "out"))
    assert rc == 0
    m = json.loads((tmp_path / "transcripts" / "v.map.json").read_text(encoding="utf-8"))
    assert m["version"] == 1 and m["topics"][0]["name"] == "Всё" and len(m["units"]) >= 10
    assert all(u["role"] == "thesis" for u in m["units"]) and not any(u.get("missing") for u in m["units"])
    assert any(u["refs"] for u in m["units"]) and any(u["filtered"] for u in m["units"])   # head/tail blocks too
    assert (tmp_path / "out" / "v" / "_map.html").is_file()
    out = capsys.readouterr().out
    assert "мыслей" in out and "голос: не измерен" in out
    # an existing map is kept: only the page is rebuilt, no model call
    calls = model.calls
    assert cli.cmd_map(str(mpath), root=tmp_path, cache_dir=str(tmp_path / "cache"), provider=model,
                       out_dir=str(tmp_path / "out")) == 0
    assert model.calls == calls and "карта уже есть" in capsys.readouterr().out
    assert cli._build_parser().parse_args(["map", "v", "--llm", "local", "--force"]).llm == "local"


def test_voice_profile_measures_level_pitch_and_range():
    import numpy as np
    from autoreels.local.voice import SR, profile
    t = np.arange(int(SR * 3.0)) / SR
    f = 150 * 2 ** (np.linspace(0, 6, t.size) / 12)                 # a glide over 6 semitones
    x = 0.3 * np.sin(2 * np.pi * np.cumsum(f) / SR)
    prof = profile(lambda a, d: x[int(a * SR):int((a + d) * SR)], ref_f0=150.0, threshold_db=-50.0)
    v = prof(0.0, 3.0)
    assert v["level_db"] == pytest.approx(-13.5, abs=1.0)
    assert v["pitch_st"] == pytest.approx(3.0, abs=0.6) and v["range_st"] == pytest.approx(4.8, abs=0.8)
    assert prof(0.0, 0.2) == {"level_db": None, "pitch_st": None, "range_st": None}


def test_describe_units_asks_only_the_units_without_a_known_passport():
    """M66: a resumed map — passports from the previous map are kept, only the rest is asked."""
    units = _units(5)
    prov = Scripted([{"units": [_pp(2), _pp(4)]}, {"units": [_pp(5)]}])
    known = {1: _pp(1) | {"summary": "старое"}, 3: _pp(3)}
    known = {k: {x: v[x] for x in ("role", "punch", "standalone", "refers", "summary")} for k, v in known.items()}
    done, missing = describe_units(units, prov, system="S", p=MapParams(window_units=2), log=lambda m: None,
                                   known=known)
    assert (done, missing) == (5, 0) and len(prov.calls) == 2
    asked = prov.calls[0][-1]["content"].split("Describe EVERY one of these units:")[1]
    assert "#2 " in asked and "#4 " in asked and "#1 " not in asked and "#3 " not in asked
    assert units[0].info["summary"] == "старое"


def test_cmd_map_incomplete_returns_3_and_the_next_run_asks_only_what_is_missing(tmp_path, capsys):
    """M66: 10h59 local-gp — Groq out of tokens after 8 of 152 thoughts, the map was written as if done and
    autocut proposed 0 clips. Now: rc 3 + «карта неполна», autocut refuses, a rerun fills the gaps only."""
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "map_system.md").write_text("S", encoding="utf-8")

    class Model:
        name = "scripted"

        def __init__(self, budget):
            self.budget, self.asked = budget, []

        def complete(self, messages, temperature=0.0):
            if self.budget <= 0:
                raise RuntimeError("rate limit")
            self.budget -= 1
            q = messages[-1]["content"]
            if q.startswith("TOPICS"):
                ids = [int(x[1:]) for x in q.split() if x.startswith("#") and x[1:].isdigit()]
                return json.dumps({"topics": [{"name": "Всё", "units": ids}]})
            part = q.split("Describe EVERY one of these units:")[1]
            ids = [int(x[1:]) for x in part.split() if x.startswith("#") and x[1:].isdigit()]
            self.asked += ids
            return json.dumps({"units": [_pp(i) for i in ids]})

    import re
    cfg = tmp_path / "config" / "r0.yaml"
    cfg.write_text(re.sub(r"(?m)^  window_units: \d+", "  window_units: 4", cfg.read_text(encoding="utf-8")),
                   encoding="utf-8")
    kw = dict(root=tmp_path, cache_dir=str(tmp_path / "cache"), out_dir=str(tmp_path / "out"))
    first = Model(budget=1)                                     # one window answered, then the limit
    assert cli.cmd_map(str(mpath), provider=first, **kw) == 3
    out = capsys.readouterr().out
    assert "✗ карта неполна" in out and "без паспорта" in out and "темы не получены" in out
    m = json.loads((tmp_path / "transcripts" / "v.map.json").read_text(encoding="utf-8"))
    n, had = len(m["units"]), set(first.asked)
    assert 0 < len(had) < n and sum(1 for u in m["units"] if u.get("missing")) == n - len(had)
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache")) == 1
    assert "карта неполна" in capsys.readouterr().err
    second = Model(budget=99)
    assert cli.cmd_map(str(mpath), provider=second, **kw) == 0
    out = capsys.readouterr().out
    assert "неполна" in out and f"паспортов {len(had)} из {n}" in out
    assert set(second.asked) == {u["id"] for u in m["units"]} - had          # nothing asked twice
    m2 = json.loads((tmp_path / "transcripts" / "v.map.json").read_text(encoding="utf-8"))
    assert not any(u.get("missing") for u in m2["units"]) and m2["topics"][0]["name"] == "Всё"
    third = Model(budget=99)                                    # complete now: kept, no call
    assert cli.cmd_map(str(mpath), provider=third, **kw) == 0 and third.asked == []
    assert "карта уже есть" in capsys.readouterr().out


class _MapModel:
    """Scripted model for cmd_map: answers windows and topics; `die_after` windows → KeyboardInterrupt
    (a kill / timeout, not an exception the map can catch)."""
    name = "scripted"

    def __init__(self, die_after=None):
        self.die_after, self.windows, self.asked = die_after, 0, []

    def complete(self, messages, temperature=0.0):
        q = messages[-1]["content"]
        if q.startswith("TOPICS"):
            ids = [int(x[1:]) for x in q.split() if x.startswith("#") and x[1:].isdigit()]
            return json.dumps({"topics": [{"name": "Всё", "units": ids}]})
        if self.die_after is not None and self.windows >= self.die_after:
            raise KeyboardInterrupt
        self.windows += 1
        part = q.split("Describe EVERY one of these units:")[1]
        ids = [int(x[1:]) for x in part.split() if x.startswith("#") and x[1:].isdigit()]
        self.asked += ids
        return json.dumps({"units": [_pp(i) for i in ids]})


def _map_source(tmp_path, key="k-groq"):
    import re
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    (tmp_path / "prompts").mkdir(exist_ok=True)
    (tmp_path / "prompts" / "map_system.md").write_text("S", encoding="utf-8")
    cfg = tmp_path / "config" / "r0.yaml"
    cfg.write_text(re.sub(r"(?m)^  window_units: \d+", "  window_units: 4", cfg.read_text(encoding="utf-8")),
                   encoding="utf-8")
    m = json.loads(mpath.read_text(encoding="utf-8"))
    m["transcript_params_key"] = key
    mpath.write_text(json.dumps(m), encoding="utf-8")
    return mpath


def test_cmd_map_keeps_every_window_when_killed_midway(tmp_path):
    """M67: Pxl 112938952 — two 90-min timeouts and nothing kept. Now each window is written as it comes."""
    mpath = _map_source(tmp_path)
    kw = dict(root=tmp_path, cache_dir=str(tmp_path / "cache"), out_dir=str(tmp_path / "out"))
    with pytest.raises(KeyboardInterrupt):
        cli.cmd_map(str(mpath), provider=_MapModel(die_after=2), **kw)
    m = json.loads((tmp_path / "transcripts" / "v.map.json").read_text(encoding="utf-8"))
    done = [u for u in m["units"] if not u.get("missing")]
    assert len(done) == 8 and len(m["units"]) > 8 and m["transcript_key"] == "k-groq"
    second = _MapModel()
    assert cli.cmd_map(str(mpath), provider=second, **kw) == 0
    assert set(second.asked) == {u["id"] for u in m["units"]} - {u["id"] for u in done}
    assert not (tmp_path / "transcripts" / "v.map.json.tmp").exists()


def test_map_of_another_transcript_is_refused_by_map_autocut_and_tx_use(tmp_path, capsys):
    """M67: 10h59 — after two sessions switched the source at once, a local-gp map sat under a Groq manifest;
    autocut ran on it and the rejected pieces read «block 28 has sentences 1-8»."""
    mpath = _map_source(tmp_path, key="k-local-gp")
    kw = dict(root=tmp_path, cache_dir=str(tmp_path / "cache"), out_dir=str(tmp_path / "out"))
    assert cli.cmd_map(str(mpath), provider=_MapModel(), **kw) == 0
    m = json.loads(mpath.read_text(encoding="utf-8"))
    m["transcript_params_key"] = "k-groq"                      # the manifest moved on, the files did not
    mpath.write_text(json.dumps(m), encoding="utf-8")
    capsys.readouterr()
    assert cli.cmd_map(str(mpath), provider=_MapModel(), **kw) == 1
    assert "построена по расшифровке k-local-gp, а манифест указывает на k-groq" in capsys.readouterr().err
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache")) == 1
    assert "k-local-gp" in capsys.readouterr().err
    second = _MapModel()
    assert cli.cmd_map(str(mpath), provider=second, force=True, **kw) == 0 and second.asked
    assert json.loads((tmp_path / "transcripts" / "v.map.json").read_text())["transcript_key"] == "k-groq"


def test_pool_names_who_answers_and_the_reserve(capsys):
    from autoreels.cloud.providers import LocalLLM, ProviderPool
    from tests.test_providers import _ScriptedProvider
    loc = LocalLLM(url="http://192.168.3.17:8081/v1")
    pool = ProviderPool([_ScriptedProvider("Groq", []), _ScriptedProvider("OpenRouter", [])], reserve=[loc])
    assert pool.describe() == "модели: Groq → OpenRouter · запас: Local http://192.168.3.17:8081/v1"
    assert ProviderPool([_ScriptedProvider("Groq", [])]).describe().endswith("запас: нет (LOCAL_LLM_URL не задан или не отвечает)")
    assert ProviderPool([loc]).describe() == "модели: Local http://192.168.3.17:8081/v1"
    cli._pool_banner(pool)
    assert "запас: Local" in capsys.readouterr().out


def test_map_of_another_video_is_refused(tmp_path, capsys):
    """M68: PXL_0729 re-analysed from a re-saved copy — the old map (another sha, no transcript key) must not
    pass as «карта уже есть»."""
    mpath = _map_source(tmp_path)
    kw = dict(root=tmp_path, cache_dir=str(tmp_path / "cache"), out_dir=str(tmp_path / "out"))
    assert cli.cmd_map(str(mpath), provider=_MapModel(), **kw) == 0
    mp = tmp_path / "transcripts" / "v.map.json"
    m = json.loads(mp.read_text())
    m["source_sha256"], m["transcript_key"] = "e" * 64, ""
    mp.write_text(json.dumps(m))
    capsys.readouterr()
    assert cli.cmd_map(str(mpath), provider=_MapModel(), **kw) == 1
    assert "для другого исходника" in capsys.readouterr().err
