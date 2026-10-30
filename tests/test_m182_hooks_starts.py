"""M182 (owner on prew_isaev_anna m176: «r03, r14 — начало пустое»; «раньше хуки были лучше, сейчас пустые» — 1 cold
open in 12 clips): (a) a cold open may be a clause of a long sentence, h:B.N@i-j, cut in the pauses around it, the
whole sentence replayed in the body; (b) a reel of the automatic path never opens on a line pointing back or at the
interviewer — an earlier start, else none. Both off by default (the previous proposals and plans)."""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from autoreels.cloud.autocut import AutoParams, _hook_cands, clause_spans, strict_start_reason
from autoreels.cloud.montage import parse_montage
from autoreels.cloud.plan import ManualPlanParams, build_manual_plan
from autoreels.core.models import Word
from tests.test_filler_cut import _setup


def test_off_by_default():
    p = AutoParams()
    assert not p.hook_clauses and not p.start_strict
    from autoreels.core.config import AutocutConfig
    assert not AutocutConfig().hook_clauses and not AutocutConfig().start_strict


def test_repo_config_on():
    from autoreels.core.config import load_r0_config
    ac = load_r0_config(Path(__file__).resolve().parents[1] / "config" / "r0.yaml").autocut
    assert ac.hook_clauses and ac.start_strict


def test_strict_start_reason():
    assert "о ком" in strict_start_reason("Каждый из них влияет на результат по-своему.")
    assert "собеседнику" in strict_start_reason("Ты чувствуешь это в стрессовых ситуациях, Ласанна.")
    assert "по имени" in strict_start_reason("Я думаю, это важно, Ласанна.")
    assert strict_start_reason("Это и есть главное.")                      # back_reference as before
    assert strict_start_reason("У меня был такой интересный момент.") is None
    assert strict_start_reason("Как вы отдыхаете?") is None


def test_montage_parses_a_clause_hook():
    (e,), errs = parse_montage("M1 90 | 3.1-4 | h:3.3@4-9!\n")
    assert errs == [] and e.hook == (3, 3) and e.hook_words == (4, 9) and e.hook_keep
    (e,), errs = parse_montage("M1 90 | 3.1-4 | h:3.3!\n")
    assert e.hook_words is None
    _, errs = parse_montage("M1 90 | 3.1-4 | h:3.3@x\n")
    assert errs and "h:B.N@i-j" in errs[0][1]


W = [("Когда", 0.0, 0.3), ("я", 0.35, 0.45), ("ехал", 0.5, 0.8), ("домой,", 0.85, 1.3),
     ("я", 1.8, 1.9), ("понял", 1.95, 2.3), ("главную", 2.35, 2.8), ("вещь", 2.85, 3.2), ("о", 3.25, 3.3),
     ("себе,", 3.35, 3.9), ("и", 4.6, 4.7), ("это", 4.75, 5.0), ("было", 5.05, 5.3), ("больно", 5.35, 5.9),
     ("и", 5.95, 6.0), ("долго.", 6.05, 7.4)]


def _words():
    return [Word(word=t, t0=a, t1=b) for t, a, b in W]


def test_clause_spans_cut_only_in_pauses():
    ws = _words()
    pause = lambda k: ws[k].t0 - ws[k - 1].t1 if k < len(ws) else None       # noqa: E731
    dur = lambda a, z: ws[z - 1].t1 - ws[a - 1].t0                          # noqa: E731
    spans = clause_spans(ws, pause, min_words=4, min_sec=1.5, max_sec=6.0, min_pause=0.12, dur=dur)
    assert (5, 10) in spans                    # «я понял главную вещь о себе,» — 0.5 s pause before, 0.7 s after
    assert (1, 16) not in spans                # the whole sentence is the ordinary hook
    assert all(dur(a, z) <= 6.0 for a, z in spans)
    assert not any(a == 2 for a, _ in spans)   # never from a word without a pause before it


def test_hook_cands_offer_a_clause_of_a_long_sentence():
    p = dataclasses.replace(AutoParams(), hook_teaser=True, hook_teaser_pos=0.0, hook_clauses=True, min_punch=0)
    long_text = " ".join(t for t, _, _ in W)

    def rows(refs):
        return [("1.1", 7.4, 16, True, long_text)]
    clip = [{"id": 1, "refs": "1.1", "punch": 4, "role": "thesis"}]
    assert _hook_cands(clip, rows, dataclasses.replace(p, hook_clauses=False)) == []      # 7.4 s > hook_max_sec
    cands = _hook_cands(clip, rows, p, clauses=lambda ref: [(5, 10, 2.1, "я понял главную вещь о себе,")])
    assert [c[0] for c in cands] == ["1.1@5-10"] and cands[0][2].startswith("я понял")


def test_plan_plays_the_clause_as_cold_open_and_the_sentence_in_the_body():
    tail = [("Потом", 8.0, 8.4), ("я", 8.45, 8.55), ("это", 8.6, 8.8), ("понял.", 8.85, 9.6)]
    sents, words, smap, align = _setup([W, tail], [])
    plan = build_manual_plan(sents, [1, 2], words=words, smap=smap, params=ManualPlanParams(), hook=1,
                             hook_mode=None, hook_words=(5, 10), align=align)
    co = plan.cold_open
    assert co is not None and 1.3 < co.start < 1.8 and 3.9 < co.end < 4.6       # inside the pauses around the clause
    assert plan.hook_replayed and plan.body[0].start < 0.1                       # the sentence plays whole in the body
    shown = [w.word for w in plan.subtitles if co.start <= w.t0 < co.end]
    assert shown == ["я", "понял", "главную", "вещь", "о", "себе,"]
    assert [w.word for w in plan.subtitles][:4] == ["Когда", "я", "ехал", "домой,"]   # body words keep their times


def test_scenario_extends_a_pointing_start_or_drops_it():
    from autoreels.cloud.scenario import scenario_proposals
    sent = {"1.1": (0.0, 5.0, "Мы говорили про разные методы работы с психикой.", True, 8),
            "1.2": (5.3, 20.0, "Каждый из них влияет на результат по-своему.", True, 7),
            "1.3": (20.3, 50.0, "Настоящие друзья поддерживают и рассказывают свой случай.", True, 7)}
    p = dataclasses.replace(AutoParams(), min_sec=10.0, max_sec=90.0, rhythm=False, start_strict=True)
    pool, gone = scenario_proposals([{"refs": ["1.2", "1.3"], "title": "Друзья"}], sent, [], p)
    assert pool and pool[0].pieces.startswith("1.1") and any("добавлена фраза перед" in n for n in pool[0].notes)
    sent["1.1"] = (0.0, 5.0, "Это тоже важно.", True, 3)                      # the sentence before points back too
    pool, gone = scenario_proposals([{"refs": ["1.2", "1.3"]}], sent, [], dataclasses.replace(p, start_extend_max=1))
    assert not pool and "раньше начать нельзя" in gone[0][1]
    pool, gone = scenario_proposals([{"refs": ["1.2", "1.3"]}], sent, [], dataclasses.replace(p, start_strict=False))
    assert pool and pool[0].pieces.startswith("1.2")                           # off: the start as the model wrote it


def test_drop_sentences_knows_a_clause_hook():
    from autoreels import __main__ as cli
    PR = dataclasses.make_dataclass("PR", ["pieces", "hook", "hooks", "keys", "close", "notes", "seconds"])
    sbr = {"1.1": [Word(word="Коротко.", t0=0.0, t1=0.7)], "1.2": [Word(word="Длинно.", t0=1.0, t1=40.0)]}
    pr = PR(pieces="1.1-2", hook="1.1@2-5", hooks=["1.1@2-5", "1.2"], keys=[], close=[], notes=[], seconds=40.0)
    out = cli._drop_sentences(pr, sbr, ["0.000"], 5.0)
    assert out.hook is None and out.hooks == ["1.2"]


def test_apply_builds_a_clause_cold_open(tmp_path, capsys):
    from autoreels.cloud.edit import merge_group_sentences
    from tests.test_montage import _apply
    rc, man, kept, tx = _apply(tmp_path, "2 80\nM 85 | 2.2-4 5.1-3 | h:5.2@1-2!\n")
    out = capsys.readouterr()
    assert rc == 0, out.err[-1500:]
    mont = man.reels[-1]
    s52 = merge_group_sentences([kept[4]], tx.words)[1]
    co = mont.cold_open
    assert co is not None and co.start <= s52[0].t0 and co.end < s52[-1].t1      # the clause only, not the sentence


def test_label_hook_picks_a_teaser_from_the_second_half():
    from types import SimpleNamespace
    from autoreels import __main__ as cli
    tail = [("Потом", 8.0, 8.4), ("я", 8.45, 8.55), ("это", 8.6, 8.8), ("понял.", 8.85, 9.6)]
    first = [("Начало", 0.0, 0.4), ("истории", 0.45, 0.9), ("было", 0.95, 1.2), ("простым", 1.25, 1.7),
             ("и", 1.75, 1.8), ("понятным.", 1.85, 2.6)]
    shifted = [(t, a + 3.0, b + 3.0) for t, a, b in W]           # the long sentence after the first one
    sents, words, smap, align = _setup([first, shifted, [(t, a + 3.0, b + 3.0) for t, a, b in tail]], [])
    entry = SimpleNamespace(beats=(), s=None, e=3, x=(), hook=None)
    ac = SimpleNamespace(hook_min_sec=1.5, hook_min_words=4, hook_teaser_pos=0.2, hook_clauses=True,
                         hook_clause_pause=0.12)
    r0 = SimpleNamespace(autocut=ac, hook_max_sec=6.0, filler_removal=None, wind_down_phrases=[])
    got = cli._label_hook(entry, sents, words, smap, align, r0)
    assert got is not None and got[0] == 2 and got[1] is not None and got[1][0] >= 1
    ac.hook_clauses = False
    assert cli._label_hook(entry, sents, words, smap, align, r0) is None or cli._label_hook(
        entry, sents, words, smap, align, r0)[1] is None


def test_m183_a_pointing_sentence_still_gives_its_clauses():
    """M183 (m182: prew_isaev_anna 0 clause hooks): «А…» / «То есть…» opens most interview sentences; the sentence is
    no cold open itself, but a later clause of it is."""
    p = dataclasses.replace(AutoParams(), hook_teaser=True, hook_teaser_pos=0.0, hook_no_pointer=True, min_punch=0,
                            hook_clauses=True)
    text = "А когда я ехал домой, я понял главную вещь о себе, и это было больно."

    def rows(refs):
        return [("1.1", 8.0, 15, True, text)]
    clip = [{"id": 1, "refs": "1.1", "punch": 4, "role": "thesis"}]
    cl = lambda ref: [(1, 5, 1.6, "А когда я ехал домой,"), (6, 11, 2.1, "я понял главную вещь о себе,")]  # noqa: E731
    cands = _hook_cands(clip, rows, p, clauses=cl)
    assert [c[0] for c in cands] == ["1.1@6-11"]                       # the «А…» clause is still no teaser
    assert _hook_cands(clip, rows, dataclasses.replace(p, hook_clauses=False), clauses=cl) == []   # off: as before
