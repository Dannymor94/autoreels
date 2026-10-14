"""M57: Whisper inventions and holes in a transcript (cloud/txcheck.py, arl tx-check, clip warnings).

G5a: on IMG_6848 the Groq transcript had «Субтитры создавал DimaTorzok» and «каждый из них влияет на
результат по-своему» in five places where a local Whisper heard other speech, and ~1000 words fewer."""
from __future__ import annotations

import json
from types import SimpleNamespace

from autoreels.cloud.txcheck import TxCheckParams, check, hit_times, known_phrases, repeats, sparse
from autoreels.core.models import Reel, Word

from tests.test_render import ROOT


def _say(text: str, t0: float, step: float = 0.4) -> list[Word]:
    return [Word(word=w, t0=round(t0 + i * step, 2), t1=round(t0 + i * step + 0.35, 2)) for i, w in enumerate(text.split())]


FILLER = ("мы говорим о том как устроена психика человека и почему он реагирует так а не иначе "
          "когда сталкивается с трудностями в жизни и в отношениях с близкими людьми")


def _lecture():
    w = _say(FILLER, 10.0)
    w += _say("и вот каждый из них влияет на результат по-своему.", 100.0)
    w += _say("потом мы разбираем детство и то что родитель реализуется через ребёнка", 200.0)
    w += _say("Каждый из них влияет на результат по-своему,", 400.0)
    w += _say("Субтитры создавал DimaTorzok", 600.0)
    w += _say("каждый из них влияет на результат", 630.0)          # the same six words a third time, shorter
    return w


def test_known_inventions_are_found():
    hits = known_phrases(_lecture(), TxCheckParams().known)
    assert [h["t"] for h in hits] == [600.0]
    assert "DimaTorzok" in hits[0]["text"]


def test_verbatim_repeats_far_apart_grown_to_full_length():
    (r,) = repeats(_lecture(), n=6, far_sec=60.0)
    assert r["text"] == "каждый из них влияет на результат"      # grown only as far as every place goes
    assert r["times"] == [100.8, 400.0, 630.0]
    (two,) = repeats(_lecture()[:-6], n=6, far_sec=60.0)
    assert two["text"] == "каждый из них влияет на результат посвоему" and two["times"] == [100.8, 400.0]
    assert repeats(_say(FILLER, 0) + _say(FILLER, 30), n=6, far_sec=60.0) == []   # too close
    assert repeats(_say(FILLER, 0), n=6, far_sec=60.0) == []


def test_sound_without_words():
    words = _say(" ".join(["слово"] * 25), 0.0)                 # 25 words in the first 10 s
    intervals = [[0.0, 30.0]]                                  # speech heard for 30 s
    (z,) = sparse(words, intervals, win=10.0, min_speech=6.0, max_rate=0.8)
    assert z["a"] == 10.0 and z["b"] == 30.0 and z["words"] == 0
    assert sparse(words, [[0.0, 10.0]], win=10.0, min_speech=6.0, max_rate=0.8) == []
    assert sparse(words, [], win=10.0) == []


def test_check_report_and_clip_hit_times():
    rep = check(_lecture(), None)
    assert rep["suspicious"] and not rep["speech_map"] and rep["sparse"] == []
    notes = hit_times(rep)
    assert [t for t, _ in notes] == [100.8, 400.0, 600.0, 630.0]
    assert "известная выдумка" in notes[2][1] and "повторяется в 3 местах" in notes[0][1]
    clean = check(_say(FILLER, 0), [[0.0, 12.0]])
    assert not clean["suspicious"] and clean["speech_map"]


def test_apply_warns_on_a_clip_that_plays_a_flagged_place():
    from autoreels import __main__ as cli
    r0 = cli.load_r0_config(ROOT / "config" / "r0.yaml")
    assert r0.tx_check.enabled
    words = _lecture()
    inside = Reel(id="r01", start=595.0, end=605.0, score=80, hook="h", title="", description="")
    outside = Reel(id="r02", start=200.0, end=210.0, score=80, hook="h", title="", description="")
    out = cli.collect_human_warnings([inside, outside], SimpleNamespace(words=words), r0_cfg=r0)
    assert any("DimaTorzok" in m and r.id == "r01" for r, m in out)
    assert not any("расшифровка" in w for w in outside.warnings)
    off = r0.model_copy(update={"tx_check": r0.tx_check.model_copy(update={"enabled": False})})
    again = Reel(id="r01", start=595.0, end=605.0, score=80, hook="h", title="", description="")
    cli.collect_human_warnings([again], SimpleNamespace(words=words), r0_cfg=off)
    assert not any("расшифровка" in w for w in again.warnings)       # flag off → as before


def test_cmd_tx_check_writes_the_report(tmp_path, capsys):
    from autoreels import __main__ as cli
    from tests.test_montage import _source
    mpath = _source(tmp_path)
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    assert cli.cmd_tx_check([str(mpath)], root=tmp_path, cache_dir=str(tmp_path / "cache")) == 0
    out = capsys.readouterr().out
    assert f"== {mpath.stem}: слов " in out and "звук без слов: нет карты речи" in out and "итого: источников 1" in out
    rep = json.loads((tmp_path / "transcripts" / f"{mpath.stem}.txcheck.json").read_text(encoding="utf-8"))
    assert rep["words"] > 400 and rep["stem"] == mpath.stem
    assert cli.cmd_tx_check([], root=tmp_path) == 1
    assert cli._build_parser().parse_args(["tx-check", "--all"]).all_sources
