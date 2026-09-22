"""Parts 2-3: sentence bounds, trailing wind-down, deterministic filler removal, review grammar.

3. s:/e: bound the clip at sentence edges (numbering continuous across a merge); defaults drop
   trailing pure wind-down.
4. Filler removal cuts a standalone "ну" and keeps "ну" inside a phrase; immediate repetitions
   collapse; a long pause shortens to the residual; the removed-share cap holds.
7. An answer line with every field applies; a malformed field is reported and the rest applies.
8. The automatic path never runs filler removal (it is manual-only).
"""
import inspect

from autoreels.cloud import edit
from autoreels.cloud.blocks import parse_compact_answer
from autoreels.core.models import Word


def _w(t0, t1, word):
    return Word(word=word, t0=t0, t1=t1)


# --- Test 3: sentence bounds + wind-down default -------------------------------------------
def test_sentence_bounds_explicit_across_merge():
    # 5 sentences over a "merged" span; s:2 e:4 bounds it at sentence edges.
    ws = []
    for i in range(5):
        ws.append(_w(i * 2.0, i * 2.0 + 1.0, f"слово{i}"))
        ws.append(_w(i * 2.0 + 1.0, i * 2.0 + 1.5, "конец."))
    s, e, expl, note = edit.sentence_bounds(ws, 0.0, 10.0, s=2, e=4)
    assert expl is True
    assert s == ws[2].t0                # first word of sentence 2
    assert e == ws[7].t1                # last word (конец.) of sentence 4


def test_default_end_drops_wind_down():
    ws = [_w(0, 1, "Главная"), _w(1, 2, "мысль."), _w(2, 3, "И"), _w(3, 4, "вывод."),
          _w(4, 5, "вот."), _w(5, 6, "да.")]
    s, e, expl, note = edit.sentence_bounds(ws, 0.0, 6.0, wind_down_phrases=["вот", "да"],
                                            filler_words=["ну", "вот"])
    assert expl is False
    assert e == 4.0                     # ends at "вывод." — "вот."/"да." dropped
    assert "wind-down" in note


def test_default_end_keeps_non_terminal_tail():
    # A real clip whose speech ends without a full stop must NOT be collapsed to an earlier period.
    ws = [_w(0, 1, "Первое."), _w(1, 2, "Мысль"), _w(2, 3, "продолжается"), _w(3, 4, "дальше")]
    s, e, expl, note = edit.sentence_bounds(ws, 0.0, 4.0, wind_down_phrases=["да"], filler_words=[])
    assert e == 4.0 and note == ""      # nothing dropped


# --- Test 4: filler removal rules -----------------------------------------------------------
_FR = dict(filler_words=["ну", "вот", "как бы"], pause_shorten_sec=0.8,
           pause_residual_sec=0.25, max_removed_share=0.25)


def test_filler_cuts_standalone_keeps_inside_phrase():
    # "Ну," standalone at a sentence start (trailing comma) → cut. "ну" in "ну и что" (no right
    # boundary) → kept.
    ws = [_w(0.0, 0.4, "Ну,"), _w(0.5, 1.0, "смысл"), _w(1.0, 1.5, "такой."),
          _w(1.6, 2.0, "ну"), _w(2.05, 2.4, "и"), _w(2.45, 3.0, "что")]
    segs, removed, cuts = edit.remove_fillers(ws, 0.0, 3.0, **_FR)
    assert cuts == 1                          # only the standalone "Ну," is cut
    assert removed > 0
    # the cut covers the leading "Ну," and the silence up to "смысл"
    assert segs and abs(segs[0].start - 0.5) < 0.06


def test_filler_collapses_immediate_repetition():
    ws = [_w(0.0, 0.5, "я"), _w(0.55, 1.0, "я"), _w(1.05, 1.6, "думаю"), _w(1.65, 2.2, "так")]
    segs, removed, cuts = edit.remove_fillers(ws, 0.0, 2.2, **_FR)
    assert cuts == 1 and abs(removed - 0.55) < 0.06   # first "я" (0.0→0.55) dropped


def test_filler_shortens_long_pause_to_residual():
    # 3.0s pause inside a 20s span (well under the 25% cap → 5s budget).
    ws = [_w(0.0, 1.0, "речь."), _w(4.0, 5.0, "дальше"), _w(5.2, 20.0, "итог.")]
    segs, removed, cuts = edit.remove_fillers(ws, 0.0, 20.0, **_FR)
    assert cuts == 1
    assert abs(removed - (3.0 - 0.25)) < 0.06             # shortened to 0.25s residual
    assert len(segs) == 2 and abs(segs[0].end - 1.25) < 0.06


def test_filler_respects_removed_share_cap():
    # Three 3s pauses in a 30s span; cap 0.25 → budget 7.5s; each cut removes 2.75s, so only 2 fit.
    ws = [_w(0.0, 1.0, "a."), _w(4.0, 5.0, "b."), _w(8.0, 9.0, "c."), _w(12.0, 30.0, "d.")]
    segs, removed, cuts = edit.remove_fillers(ws, 0.0, 30.0, **_FR)
    assert removed <= 0.25 * 30.0 + 1e-6
    assert cuts == 2                                       # third cut skipped by the cap


# --- Test 7: grammar — every field applies; malformed reported, rest applies ----------------
def test_grammar_all_fields_and_malformed():
    src, entries, errs, ign = parse_compact_answer(
        "3 85+ | s:2 e:9 | h:7 | t: Ты не поломан — ты забыл свою силу\n"
        "4 90 | s:bad e:3\n"
    )
    e3 = next(e for e in entries if e.seq == 3)
    assert (e3.score, e3.merge_fwd, e3.s, e3.e, e3.hook) == (85, 1, 2, 9, 7)
    assert e3.title == "Ты не поломан — ты забыл свою силу"
    e4 = next(e for e in entries if e.seq == 4)
    assert e4.e == 3                     # the valid e:3 still applied
    assert any("s" in msg for _, msg in errs)   # malformed s:bad reported, not fatal


# --- Test 8: automatic path never removes filler --------------------------------------------
def test_automatic_path_has_no_filler_removal():
    from autoreels.cloud import select as _sel
    from autoreels import __main__ as cli
    # remove_fillers must not be wired into the automatic selection pipeline or its command path.
    assert "remove_fillers" not in inspect.getsource(_sel)
    assert "remove_fillers" not in inspect.getsource(cli._cmd_run_impl)
