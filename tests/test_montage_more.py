"""M58: a montage line may take the filtered blocks (x1…), and a piece that goes straight on from the
previous one in the source is played as one piece (no seam)."""
from __future__ import annotations

from types import SimpleNamespace

from autoreels.cloud.montage import build_montage, montage_blocks, parse_montage
from autoreels.core.models import Word


def _sent(text, t0, step=0.5):
    ws = text.split()
    return [Word(word=w + ("." if i == len(ws) - 1 else ""), t0=round(t0 + i * step, 2),
                 t1=round(t0 + i * step + 0.4, 2)) for i, w in enumerate(ws)]


def _blocks():
    # block 1: three sentences 0–9 s; block 2 starts 0.6 s after block 1 ends; block 3 far away
    b1 = [_sent("раз два три", 0.0), _sent("четыре пять шесть", 3.0), _sent("семь восемь девять", 6.0)]
    b2 = [_sent("десять одиннадцать", 7.0 + 1.5 + 0.6), _sent("двенадцать тринадцать", 11.0)]
    b3 = [_sent("далеко потом", 60.0), _sent("ещё дальше", 63.0)]
    mk = lambda s: SimpleNamespace(start=s[0][0].t0, end=s[-1][-1].t1, sents=s)
    return {1: mk(b1), 2: mk(b2), 3: mk(b3)}


def test_x_blocks_are_numbered_after_the_review_numbering():
    a, b, c, d = (SimpleNamespace(start=float(i)) for i in range(4))
    mb = montage_blocks([a, b, c, d], [b, d])
    assert mb == {1: b, 2: d, "x1": a, "x2": c}
    (e,), errs = parse_montage("M 80 | x1.2-3 2.1 | h:x2.1 | k:x1.2=слово\n")
    assert errs == [] and e.pieces[0].block == "x1" and str(e.pieces[0]) == "x1.2-3" and e.hook == ("x2", 1)
    assert e.keys == ((("x1", 2), ("слово",)),)


def test_pieces_that_go_straight_on_are_joined():
    bl = _blocks()
    (e,), _ = parse_montage("M 80 | 1.2-3 2.1-2 3.1\n")
    mb = build_montage(e, bl, lambda b: b.sents)
    assert mb.errors == []
    assert mb.pieces == [(2, 5), (6, 6)] and mb.breaks == [6]          # 1.3 → 2.1: no seam; 2.2 → 3.1: seam
    assert mb.joined == ["2-3 + 2.1-2"]
    (e,), _ = parse_montage("M 80 | 1.1 1.3 3.1\n")                     # 1.1 → 1.3 skips a sentence: seam
    assert build_montage(e, bl, lambda b: b.sents).breaks == [3, 4]       # block 3 is numbered 4-5 here
    (e,), _ = parse_montage("M 80 | 1.2-3 2.1-2\n")
    assert build_montage(e, bl, lambda b: b.sents, join_gap_sec=0.1).breaks == [4]   # gap 0.7 s > 0.1


def test_missing_block_names_both_numberings():
    bl = _blocks()
    bl["x1"] = SimpleNamespace(start=100.0, sents=[_sent("хвост", 100.0)])
    (e,), _ = parse_montage("M 80 | 9.1\n")
    assert "1-3, filtered x1-x1" in build_montage(e, bl, lambda b: b.sents).errors[0]


def test_apply_takes_a_piece_of_the_filtered_tail(tmp_path, capsys):
    from autoreels import __main__ as cli
    from tests.test_montage import _apply
    rc, man, kept, tx = _apply(tmp_path, "M 85 | 2.1-3 x1.1-2\n")
    out = capsys.readouterr()
    assert rc == 0, out.err[-1500:]
    (mont,) = man.reels
    tail_start = 347.0
    assert mont.effective_segments()[-1].start > tail_start - 1.0      # the last piece plays the tail block
    assert cli.cmd_blocks_text(str(tmp_path / "manifests" / "v.json"), root=tmp_path,
                               cache_dir=str(tmp_path / "cache"), blocks="x1") == 0
    txt = capsys.readouterr().out
    assert "+ отсеянных x1–x1" in txt and "[x1] " in txt and "отсеян: tail" in txt and "x1.1 " in txt


# ------------------------------------------------------------------ M59: free order of pieces

def test_pieces_may_come_in_any_order():
    bl = _blocks()
    (e,), _ = parse_montage("M 80 | 3.1-2 1.1-2\n")
    mb = build_montage(e, bl, lambda b: b.sents)
    assert mb.errors == [] and mb.reordered
    assert mb.play == [4, 5, 1, 2] and mb.breaks == [1] and mb.pieces == [(4, 5), (1, 2)]
    (e,), _ = parse_montage("M 80 | 1.1-2 3.1\n")
    assert not build_montage(e, bl, lambda b: b.sents).reordered


def test_plan_subtitles_in_play_order_when_reordered():
    from autoreels.cloud.plan import build_manual_plan
    from tests.test_montage import P as MP, _spec_sents
    sents, words, smap = _spec_sents()
    fwd = build_manual_plan(sents, [1, 2, 3, 4, 5, 6], words=words, smap=smap, params=MP, breaks=[4])
    assert fwd.subtitles == sorted(fwd.subtitles, key=lambda w: w.t0)          # source order: as before
    rev = build_manual_plan(sents, [4, 5, 6, 1, 2, 3], words=words, smap=smap, params=MP, breaks=[1])
    assert rev.last_word.word == sents[2][-1].word
    assert rev.subtitles[-1].word == sents[2][-1].word and rev.subtitles[0].word == sents[3][0].word
    assert [w.start for w in rev.body][0] > [w.start for w in rev.body][1]


def test_apply_reordered_montage_plays_in_written_order(tmp_path, capsys):
    from tests.test_montage import _apply
    rc, man, kept, tx = _apply(tmp_path, "M1 85 | 5.1-3 2.1-3\n")
    out = capsys.readouterr()
    assert rc == 0, out.err[-1500:]
    (mont,) = man.reels
    segs = mont.effective_segments()
    assert mont.reordered and segs[0].start > segs[-1].start                 # block 5 first, then block 2
    assert mont.start == segs[0].start and mont.end == segs[-1].end
    mont.check_segments()                                                    # play order is valid
    assert mont.subtitles[-1].t0 < segs[-1].end and mont.subtitles[-1].t0 > segs[-1].start
    assert "jumps back" in out.out
    with __import__("pytest").raises(ValueError):                            # a normal clip still must be in order
        mont.model_copy(update={"reordered": False}).check_segments()
