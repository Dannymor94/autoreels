"""M173 (owner on 09h33 m163 r01: hook, 0.7 s of one sentence, then a cut — «нужно отталкиваться от алгоритма, чтобы
таких скачков кадра не возникало»; on m172: one frame «стреляет» by scale): a shot between two picture changes
shorter than short_shot_sec is reported; inside one piece no wide/close span is shorter (the switch moves); an
automatic montage clip with a short shot is refused at --apply and its line check drops that shot's sentences.
short_shot_sec 0 = the previous plan."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from autoreels.cloud.plan import (ManualPlanParams, PlannedWindow, _tidy_spans, build_manual_plan,
                                  picture_shots)
from tests.test_montage import P, _spec_sents

ON = replace(P, short_shot_sec=2.0)


def test_off_by_default_and_no_warning_without_it():
    assert ManualPlanParams().short_shot_sec == 0.0
    sents, words, smap = _spec_sents()
    plan = build_manual_plan(sents, [3, 4, 5], words=words, smap=smap, params=P, breaks=[4])
    assert not [w for w in plan.warnings if w.startswith("short shot")]
    assert all(w.min_span_sec == 0.0 for w in plan.windows)


def test_short_first_piece_is_reported_with_its_sentence():
    sents, words, smap = _spec_sents()
    plan = build_manual_plan(sents, [3, 4, 5], words=words, smap=smap, params=ON, breaks=[4])
    ss = [w for w in plan.warnings if w.startswith("short shot")]
    assert len(ss) == 1 and "whole sentences s3@4.000" in ss[0], plan.warnings
    # the same clip from s2: the first piece is 3.6 s — no short shot
    plan = build_manual_plan(sents, [2, 3, 4, 5], words=words, smap=smap, params=ON, breaks=[4])
    assert not [w for w in plan.warnings if w.startswith("short shot")]


def test_last_shot_is_not_counted():
    sents, words, smap = _spec_sents()
    plan = build_manual_plan(sents, [2, 3, 4], words=words, smap=smap, params=ON, breaks=[4])
    assert not [w for w in plan.warnings if w.startswith("short shot")]       # s4 alone is the last shot


def test_picture_shots_split_at_seams_cuts_and_switches():
    w1 = PlannedWindow(sentences=[1], start=0.0, end=4.0, shot="wide", close_intervals=[[1.0, 2.0]])
    w2 = PlannedWindow(sentences=[2], start=10.0, end=13.0, shot="wide", cuts=[[11.0, 12.0]])
    shots = picture_shots([w1, w2])
    assert [(round(a, 3), round(b, 3)) for a, b, _ in shots] == [(0, 1), (1, 2), (2, 4), (4, 5), (5, 6)]
    assert shots[3][2] == [(4.0, 5.0, 10.0)] and shots[4][2] == [(5.0, 6.0, 12.0)]


def test_tidy_spans_leaves_no_sliver():
    assert _tidy_spans([[0.03, 1.0]], 3.0, 0.5) == [[0.0, 1.0]]            # 1 frame of wide before the close
    assert _tidy_spans([[0.5, 2.97]], 3.0, 0.5) == [[0.5, 3.0]]             # … and after it
    assert _tidy_spans([[0.5, 1.0], [1.1, 2.0]], 3.0, 0.5) == [[0.5, 2.0]]  # a flash of wide between two closes
    assert _tidy_spans([[1.0, 1.2]], 3.0, 0.5) == []                        # a flash of close
    assert _tidy_spans([[0.6, 1.8]], 3.0, 0.5) == [[0.6, 1.8]]              # nothing short: unchanged


def test_window_segments_carry_the_tidy_spans_only_when_on():
    w = PlannedWindow(sentences=[1], start=0.0, end=4.0, shot="wide", close_intervals=[[0.02, 2.0]])
    assert w.segments()[0].close_intervals == [[0.02, 2.0]]
    w.min_span_sec = 2.0
    seg = w.segments()[0]
    assert seg.shot == "wide" and seg.close_intervals == [[0.0, 2.0]]
    w2 = PlannedWindow(sentences=[1], start=0.0, end=4.0, shot="wide", close_intervals=[[0.0, 1.0], [1.04, 4.0]],
                       min_span_sec=0.5)
    assert w2.segments()[0].shot == "close"


def test_drop_sentences_takes_out_the_named_ones():
    from autoreels import __main__ as cli
    from autoreels.core.models import Word
    sbr = {"17.7": [Word(word="Короче.", t0=780.29, t1=781.04)],
           "18.1": [Word(word="Если", t0=783.34, t1=783.6), Word(word="так.", t0=783.7, t1=790.0)],
           "18.2": [Word(word="Дальше.", t0=790.3, t1=809.0)]}
    pr = SimpleNamespace(pieces="17.7 18.1-2", hook="17.7", hooks=["17.7", "18.2"], keys=[("17.7", ("к",))],
                         close=[], notes=[], seconds=30.0)
    import dataclasses
    PR = dataclasses.make_dataclass("PR", ["pieces", "hook", "hooks", "keys", "close", "notes", "seconds"])
    pr = PR(**vars(pr))
    out = cli._drop_sentences(pr, sbr, ["780.290"], 5.0)
    assert out.pieces == "18.1-2" and out.hook is None and out.hooks == ["18.2"] and out.keys == []
    assert cli._drop_sentences(pr, sbr, ["999.0"], 5.0) is None                 # not in the line
    assert cli._drop_sentences(pr, sbr, ["780.290"], 60.0) is None              # the rest too short


def test_short_shot_errors_only_for_montage_reels():
    from autoreels import __main__ as cli
    r = lambda flags: SimpleNamespace(id="r01", planned=True, flags=flags,          # noqa: E731
                                      warnings=["short shot 0.95s between two picture changes …"])
    assert cli._short_shot_errors([r(["montage"])]) and not cli._short_shot_errors([r([])])


def test_params_and_repo_config():
    from autoreels import __main__ as cli
    from autoreels.core.config import R0Config, load_r0_config
    assert R0Config.model_fields["short_shot_sec"].default == 0.0
    r0 = load_r0_config(Path(__file__).resolve().parents[1] / "config" / "r0.yaml")
    assert r0.short_shot_sec > 0
    assert cli._manual_plan_params(r0, None).short_shot_sec == r0.short_shot_sec
