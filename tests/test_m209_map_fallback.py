"""M209: the map's passport — the model's; the rules (cloud/textmap.py) only for the thoughts the model gave nothing.
m208: all by rules 33 of 56 owner clips, the model 36 — the rules stand in, they do not replace."""
from __future__ import annotations

import json
import re

from autoreels.cloud import textmap as T
from tests.test_m208_textmap import _map


def test_a_complete_map_comes_back_as_it_is():
    m = _map()
    out, nfill, ntop = T.apply_fallback(m)
    assert out is m and (nfill, ntop) == (0, 0)


def test_only_the_thoughts_without_a_passport_take_the_rules():
    m = _map()
    for u in m["units"][2:]:
        u.update(role=None, punch=None, standalone=None, refers=None, summary="", missing=True)
    out, nfill, ntop = T.apply_fallback(m)
    assert (nfill, ntop) == (2, 0)
    assert out["units"][:2] == m["units"][:2]                                     # the model's passport kept
    assert [u["role"] for u in out["units"][2:]] == ["example", "conclusion"]     # the rules where it was missing
    assert all(u["passport"] == "rules" and "missing" not in u for u in out["units"][2:])
    assert m["units"][2]["missing"] is True                                       # the input map is not changed


def test_thoughts_without_a_topic_take_the_rules_topic_without_a_clash():
    m = _map()
    m["topics"] = [{"id": 1, "name": "страх", "units": [1, 2]}, {"id": -1, "name": "без ответа", "units": [3, 4],
                                                                 "missing": True}]
    for u in m["units"][2:]:
        u["topic"] = -1
    out, nfill, ntop = T.apply_fallback(m)
    assert (nfill, ntop) == (0, 2)
    assert [u["topic"] for u in out["units"][:2]] == [1, 1]
    assert all(u["topic"] > T.FALLBACK_TOPIC_BASE for u in out["units"][2:])
    ids = {tp["id"] for tp in out["topics"]}
    assert -1 not in ids and 1 in ids and all(u["topic"] in ids for u in out["units"])
    m2 = _map()
    m2["topics"] = []                                       # no topics at all: «every thought its own topic», as before
    for u in m2["units"]:
        u.pop("topic")
    out2, nfill2, ntop2 = T.apply_fallback(m2)
    assert out2 is m2 and (nfill2, ntop2) == (0, 0)


def test_arl_map_goes_on_and_autocut_fills_what_the_model_did_not_give(tmp_path, capsys):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    from tests.test_map import _pp
    mpath = _source(tmp_path)
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "map_system.md").write_text("S", encoding="utf-8")

    class Model:
        name = "scripted"

        def __init__(self):
            self.budget = 1

        def complete(self, messages, temperature=0.0):
            if self.budget <= 0:
                raise RuntimeError("rate limit")
            self.budget -= 1
            part = messages[-1]["content"].split("Describe EVERY one of these units:")[1]
            ids = [int(x[1:]) for x in part.split() if x.startswith("#") and x[1:].isdigit()]
            return json.dumps({"units": [_pp(i) for i in ids]})

    cfg = tmp_path / "config" / "r0.yaml"
    text = cfg.read_text(encoding="utf-8")
    assert re.search(r"(?m)^  map_passport: fallback", text)                       # the repo config
    cfg.write_text(re.sub(r"(?m)^  window_units: \d+", "  window_units: 4", text), encoding="utf-8")
    kw = dict(root=tmp_path, cache_dir=str(tmp_path / "cache"), out_dir=str(tmp_path / "out"))
    assert cli.cmd_map(str(mpath), provider=Model(), **kw) == 0                     # incomplete, the run goes on
    out = capsys.readouterr().out
    assert "⚠ карта неполна" in out and "по правилам" in out and "✗ карта неполна" not in out
    m = json.loads((tmp_path / "transcripts" / "v.map.json").read_text(encoding="utf-8"))
    assert any(u.get("missing") for u in m["units"])                               # the file keeps what is missing
    rc = cli.cmd_autocut("v", root=tmp_path, cache_dir=str(tmp_path / "cache"), check=False, llm="none")
    assert rc == 0 and "по правилам паспорт" in capsys.readouterr().out
