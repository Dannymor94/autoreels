"""M172 (owner on 09h33 m163 r01: cold open, 0.7 s of sentence 17.7, a jump to 18.1 — «такие скачки — плохо»):
a montage piece that speaks less than join_short_sec joins its straight-on neighbour across a pause up to
join_short_gap_sec (over the M58 join_gap_sec). Off (0) = the M58 rule unchanged."""
from __future__ import annotations

from types import SimpleNamespace

from autoreels.cloud.montage import build_montage, parse_montage
from autoreels.core.config import MontageConfig, load_r0_config
from autoreels.core.models import Word


def _w(text, t0, t1):
    return Word(word=text, t0=t0, t1=t1)


def _bl():
    # like r01: a 0.75 s sentence, a 2.3 s pause, then the long piece; then a sentence far away
    s1 = [_w("Короче.", 780.29, 781.04)]
    s2 = [_w("Если", 783.34, 783.6), _w("так.", 783.7, 790.0)]
    s3 = [_w("Дальше.", 790.3, 795.0)]
    s4 = [_w("Далеко.", 900.0, 902.0)]
    return {1: SimpleNamespace(start=780.29, end=902.0, sents=[s1, s2, s3, s4])}


def test_off_by_default_and_the_m58_rule_unchanged():
    assert MontageConfig().join_short_sec == 0.0 and MontageConfig().join_short_gap_sec == 0.0
    (e,), _ = parse_montage("M 95 | 1.1 1.2-3\n")
    mb = build_montage(e, _bl(), lambda b: b.sents, pause=lambda a, b: 2.3)
    assert mb.breaks == [2] and mb.joined == []                        # 2.3 s > join_gap 2.0: a seam (before)


def test_short_piece_joins_across_a_longer_pause():
    (e,), _ = parse_montage("M 95 | 1.1 1.2-3\n")
    mb = build_montage(e, _bl(), lambda b: b.sents, pause=lambda a, b: 2.3,
                       join_short_sec=2.0, join_short_gap_sec=4.0)
    assert mb.breaks == [] and mb.pieces == [(1, 3)] and mb.joined == ["1-1 + 1.2-3"]


def test_short_piece_after_the_long_one_joins_too():
    (e,), _ = parse_montage("M 95 | 1.2 1.3\n")
    bl = _bl()
    bl[1].sents[2] = [_w("Дальше.", 792.3, 793.0)]                       # 0.7 s piece after a 2.3 s pause
    mb = build_montage(e, bl, lambda b: b.sents, pause=lambda a, b: 2.3,
                       join_short_sec=2.0, join_short_gap_sec=4.0)
    assert mb.breaks == []


def test_long_pieces_keep_the_m58_gap():
    (e,), _ = parse_montage("M 95 | 1.2 1.3\n")
    mb = build_montage(e, _bl(), lambda b: b.sents, pause=lambda a, b: 2.3,
                       join_short_sec=2.0, join_short_gap_sec=4.0)
    assert mb.breaks == [3]                                            # both pieces ≥ 2 s: a seam as before


def test_pause_over_the_cap_or_a_word_between_stays_a_seam():
    (e,), _ = parse_montage("M 95 | 1.1 1.2-3\n")
    kw = dict(join_short_sec=2.0, join_short_gap_sec=4.0)
    assert build_montage(e, _bl(), lambda b: b.sents, pause=lambda a, b: 4.5, **kw).breaks == [2]
    assert build_montage(e, _bl(), lambda b: b.sents, pause=lambda a, b: None, **kw).breaks == [2]
    (e,), _ = parse_montage("M 95 | 1.1 1.4\n")                        # not the next sentence: never joined
    assert build_montage(e, _bl(), lambda b: b.sents, pause=lambda a, b: 0.1, **kw).breaks == [4]


def test_heard_span_decides_the_length():
    (e,), _ = parse_montage("M 95 | 1.1 1.2-3\n")
    kw = dict(join_short_sec=2.0, join_short_gap_sec=4.0, pause=lambda a, b: 2.3)
    # Whisper says 0.75 s, but heard it is 2.5 s (and the long piece too): a seam
    assert build_montage(e, _bl(), lambda b: b.sents, span=lambda f, l: 2.5, **kw).breaks == [2]


def test_repo_config_turns_it_on():
    from pathlib import Path
    mc = load_r0_config(Path(__file__).resolve().parents[1] / "config" / "r0.yaml").montage
    assert mc.join_short_sec > 0 and mc.join_short_gap_sec > mc.join_gap_sec
