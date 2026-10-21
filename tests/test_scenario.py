"""M123: the scenarist (cloud/scenario.py, arl autocut --scenario) — the model writes the reels from the whole text,
the code checks every line with the automatic path's rules."""
from __future__ import annotations

import json

from autoreels.cloud.autocut import AutoParams
from autoreels.cloud.scenario import compress_refs, expand_refs, parse_scenarios, scenario_proposals


def test_refs_expand_and_compress():
    assert expand_refs("14.2-4 15.1") == ["14.2", "14.3", "14.4", "15.1"]
    assert expand_refs("14.4-2") is None and expand_refs("x") is None
    assert compress_refs(["14.2", "14.3", "14.4", "15.1", "15.3"]) == "14.2-4 15.1 15.3"


def test_parse_keeps_only_lines_of_the_talks_sentences():
    known = {f"1.{k}" for k in range(1, 9)} | {"2.1", "2.2"}
    raw = ("Вот ролики:\nM | 1.1-3 2.1 | h:2.1! | t: Маска и правда | why: вопрос → пример → вывод\n"
           "M | 1.4-9 | h:1.5 | t: лишнее\nM | 1.2 2.2 | t: повтор\nM | 2.2 | h:9.9 | t: Конец\nтекст без строки")
    scens, bad = parse_scenarios(raw, known)
    assert [s["refs"] for s in scens] == [["1.1", "1.2", "1.3", "2.1"], ["2.2"]]
    assert scens[0]["hook"] == "2.1" and scens[0]["title"] == "Маска и правда" and scens[0]["why"].startswith("вопрос")
    assert scens[1]["hook"] is None                                    # a teaser outside the reel is dropped
    assert any("нет таких фраз 1.9" in b for b in bad) and any("уже в другом ролике" in b for b in bad)


def _sent(spec):
    """{ref: (t0, dur, finished)} → the sent index scenario_proposals takes."""
    return {r: (t0, t0 + d, f"Законченная фраза {r} про жизнь.", fin, 5) for r, (t0, d, fin) in spec.items()}


def test_proposals_keep_the_rules_and_map_the_thoughts():
    sent = _sent({"1.1": (0, 10, True), "1.2": (10, 10, True), "1.3": (20, 10, True), "1.4": (30, 4, True),
                  "5.1": (300, 14, True), "9.1": (600, 6, True), "9.2": (606, 6, False)})
    units = [{"id": 1, "refs": "1.1-2", "summary": "мысль 1"}, {"id": 2, "refs": "1.3-4", "summary": "мысль 2"},
             {"id": 3, "refs": "5.1", "summary": "вывод"}, {"id": 4, "refs": "9.1-2", "summary": "хвост"}]
    p = AutoParams(min_sec=20, target_sec=55, max_sec=90, rhythm=True, hook_teaser=True, close_last=True, end_tone=True)
    tone = lambda r: "open" if r == "1.4" else "final"  # noqa: E731
    scens = [{"refs": ["1.1", "1.2", "1.3", "1.4", "5.1"], "hook": "1.4", "title": "Тема", "why": "a → b → c"},
             {"refs": ["1.1", "9.1"], "hook": None, "title": "", "why": ""},           # too short
             {"refs": ["9.1", "9.2"], "hook": None, "title": "", "why": ""},             # 9.2 unfinished, cannot trim
             {"refs": ["1.1", "1.2", "9.1", "5.1"], "hook": None, "title": "", "why": ""}]  # 6 s after a far jump
    props, gone = scenario_proposals(scens, sent, units, p, tone)
    (pr,) = props
    assert pr.pieces == "1.1-4 5.1" and pr.units == [1, 2, 3] and pr.unit_refs == {} and pr.title == "Тема"
    assert pr.hook == "1.4" and any("крючок сценариста: h:1.4" in n for n in pr.notes) and pr.close == ["5.1"] and pr.caption == "вывод"
    assert any(n.startswith("сценарий: a → b → c") for n in pr.notes)
    assert pr.notes[0].startswith("#1 None★None 1.1-2 — мысль 1") and pr.notes[2].startswith("#3 ")   # M124
    whys = [w for _, w in gone]
    assert len(gone) == 3 and any("длина" in w for w in whys) and any("скачки" in w for w in whys)
    assert any("конец не законченный" in w for w in whys)


def test_cmd_autocut_scenario_takes_the_models_lines_and_lists_the_rest(tmp_path, capsys):
    from autoreels import __main__ as cli
    from autoreels.cloud.edit import merge_group_sentences
    from autoreels.core.models import Manifest
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    cfg = tmp_path / "config" / "r0.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("  min_sec: 25 ", "  min_sec: 5 ")
                   .replace("  hook_llm: auto ", "  hook_llm: none "), encoding="utf-8")
    r0 = cli.load_r0_config(cfg)
    tx = cli._resolve_cached_transcript(Manifest.model_validate_json(mpath.read_text()), tmp_path / "cache")
    _, kept, _ = cli._review_block_set(tx, r0, "lecture")
    ss = merge_group_sentences([kept[1]], tx.words)
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    (tmp_path / "transcripts" / "v.map.json").write_text(json.dumps({"version": 1, "stem": "v", "source_sha256": "f" * 64,
        "units": [{"id": 1, "t0": ss[0][0].t0, "t1": ss[-1][-1].t1, "role": "thesis", "punch": 4,
                   "refs": f"2.1-{len(ss)}", "topic": 1, "standalone": True, "summary": "тезис"}]}), encoding="utf-8")
    asked = []

    class Fake:
        model_id = "fake:scenarist"

        def complete(self, messages, temperature=0.0):
            asked.append(messages)
            return f"M | 2.1-{len(ss)} | t: Тезис ролика | why: вопрос → ответ\nM | 99.1 | t: нет такой"
    rc = cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=False, scenario=True,
                         scenario_provider=Fake(), out=str(tmp_path / "reviews" / "v_scen.txt"))
    assert rc == 0
    text = (tmp_path / "reviews" / "v_scen.txt").read_text(encoding="utf-8")
    assert f"| 2.1-{len(ss)} |" in text and "сценарий: вопрос → ответ" in text
    assert "# --- сценарист:" in text and "нет таких фраз 99.1" in text
    sys_text, user_text = asked[0][0]["content"], asked[0][1]["content"]
    assert "You are the editor" in sys_text and "2.1 [" in user_text
    rc = cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=False, scenario=True,
                         scenario_provider=Fake(), out=str(tmp_path / "reviews" / "v_scen2.txt"))
    assert rc == 0 and len(asked) == 1 and "ответ из кэша" in capsys.readouterr().out   # not asked twice
    assert cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=False, scenario=True,
                           llm="cloud") == 1                                       # the model must be named


def test_m123b_reel_lines_in_the_forms_the_model_writes():
    """m123: Sonnet wrote «1 | 30.4-30.7 | …» — a number for «M» and the block repeated in a range; the answer was cut
    at max_tokens, its last line half written."""
    from autoreels.cloud.scenario import REEL_LINE
    assert all(REEL_LINE.match(s) for s in ("M | 1.1", "M3 | 1.1", "1 | 1.1", "3. | 1.1", "12) | 1.1", "**M2** | 1.1"))
    assert not REEL_LINE.match("Вот | 1.1") and not REEL_LINE.match("Ролики:")
    assert expand_refs("30.4-30.7") == ["30.4", "30.5", "30.6", "30.7"] and expand_refs("30.4–5") == ["30.4", "30.5"]
    assert expand_refs("14.5-15.2") is None
    known = {"30.4", "30.5", "30.6", "30.7", "31.1", "31.2"}
    scens, bad = parse_scenarios("1 | 30.4-30.7 | h:30.6 | t: Тема | why: a → b\n**2** | 31.1 | t: Б | why: c\n3 | 31.2-31",
                                 known)
    assert [s["refs"] for s in scens] == [["30.4", "30.5", "30.6", "30.7"], ["31.1"]] and scens[0]["hook"] == "30.6"
    assert len(bad) == 1                                              # the cut last line goes, with its reason
