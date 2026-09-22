"""Parts 2-3: sentence bounds, trailing wind-down, deterministic filler removal, review grammar.

3. s:/e: bound the clip at sentence edges (numbering continuous across a merge); defaults drop
   trailing pure wind-down.
4. Filler removal cuts a standalone "ну" and keeps "ну" inside a phrase; immediate repetitions
   collapse; a long pause shortens to the residual; the removed-share cap holds.
7. An answer line with every field applies; a malformed field is reported and the rest applies.
8. The automatic path never runs filler removal (it is manual-only).
"""
import inspect
from pathlib import Path

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
    # A standalone "ну," at a clause edge (after "такой.", trailing comma) → cut. "ну" in "ну и что"
    # (no right boundary) → kept. The filler is NOT the clip's first word (index 0 is never cut).
    ws = [_w(0.0, 0.4, "Смысл"), _w(0.5, 1.0, "такой."), _w(1.2, 1.6, "ну,"),
          _w(2.0, 2.4, "смысл"), _w(2.5, 3.0, "такой."),
          _w(3.1, 3.4, "ну"), _w(3.45, 3.8, "и"), _w(3.85, 4.2, "что")]
    segs, removed, cuts = edit.remove_fillers(ws, 0.0, 4.2, **_FR)
    assert cuts == 1                          # only the standalone "ну," is cut
    assert removed > 0
    # the cut covers "ну," and the silence up to the next word; the clip keeps its opening "Смысл"
    assert segs and segs[0].start == 0.0 and abs(segs[0].end - 1.2) < 0.06


def test_filler_never_cuts_opening_word():
    # The clip opens on a standalone filler at a clause edge; it must NOT be cut (it is the first
    # word of the clip's first sentence — chosen by s:N or the default start).
    ws = [_w(0.0, 0.4, "Ну,"), _w(0.5, 1.0, "смысл"), _w(1.0, 1.5, "такой.")]
    segs, removed, cuts = edit.remove_fillers(ws, 0.0, 1.5, **_FR)
    assert cuts == 0 and removed == 0.0 and segs == []


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


# --- s:N lands exactly: export → parse → the CLI's own formatting stages -------------------
def test_s_marker_first_body_word_matches_export_end_to_end():
    """Applying s:N puts the first body word on sentence N's first word — as the export numbers it.

    Threads the real code the CLI uses: export_compact_review (numbering) → parse_compact_answer →
    sentence_bounds → snap_segments → filter_dangling_start → apply_padding. Sentence 2 opens on a
    hanging word ("Если"), which snap would otherwise skip past — the _explicit_start guard must
    keep the start on it.
    """
    from autoreels.cloud.blocks import CandidateBlock, export_compact_review
    from autoreels.cloud.edit import split_sentences, words_in_span, sentence_bounds
    from autoreels.cloud.snap import snap_segments, apply_padding
    from autoreels.cloud.select import filter_dangling_start
    from autoreels.core.config import load_r0_config
    from autoreels.core.models import Reel
    from autoreels.local.subtitles import words_in_window

    # Two clear sentences; sentence 2 opens on the hanging word "Если".
    ws = [_w(0.0, 0.4, "Раз"), _w(0.5, 1.0, "два."),
          _w(2.0, 2.4, "Если"), _w(2.5, 3.0, "тепло"), _w(3.1, 4.0, "дома."),
          _w(4.2, 4.6, "Семь"), _w(4.7, 20.0, "восемь.")]
    block = CandidateBlock(id="b1", start=0.0, end=20.0, duration=20.0,
                           text=" ".join(w.word for w in ws), boundary_reason="sentence")

    export = export_compact_review([block], source_ref="t.json", filter_removed_count=0, words=ws)
    assert "[2] Если тепло дома." in export                   # numbering the reviewer sees

    _, entries, _, _ = parse_compact_answer("1 90 | s:2\n")
    e = entries[0]
    sent2_first = split_sentences(words_in_span(ws, block.start, block.end))[e.s - 1][0].word
    assert sent2_first == "Если"

    r0 = load_r0_config(Path(__file__).resolve().parents[1] / "config" / "r0.yaml")
    ns, ne, expl, _ = sentence_bounds(ws, block.start, block.end, s=e.s, e=e.e,
                                      wind_down_phrases=r0.wind_down_phrases,
                                      filler_words=r0.filler_removal.filler_words)
    reel = Reel(id="r", start=ns, end=ne, score=90, hook="h", title="", description="", reason="x")
    assert expl
    reel._explicit_start = True
    reel.r0_start, reel.r0_end = reel.start, reel.end

    reels = [reel]
    snap_segments(reels, ws, tail_sec=r0.tail_sec, window_sec=r0.snap_window_sec,
                  max_duration=180.0, min_pause_for_phrase_end=r0.min_pause_for_phrase_end,
                  max_micro_pause=r0.max_micro_pause, hanging_words=r0.hanging_end_words,
                  hanging_start_words=r0.hanging_start_words,
                  max_end_search_sec=r0.max_end_search_sec, min_clip_duration=r0.min_clip_duration)
    filter_dangling_start(reels, ws, dangling_words=getattr(r0, "dangling_words", None),
                          min_duration=r0.min_clip_duration, repair_only=True,
                          max_start_fraction=1.0 / 3.0)
    apply_padding(reels, ws, tail_pad_sec=r0.tail_pad_sec, lead_pad_sec=r0.lead_pad_sec,
                  max_duration=180.0, video_duration=ws[-1].t1, hanging_words=r0.hanging_end_words)

    first_body = words_in_window(ws, reel.start, reel.end)[0].word
    assert first_body == "Если", f"clip opened on {first_body!r}, expected the s:2 word 'Если'"


# --- Test 8: the manual-only features never touch the automatic path ------------------------
def test_automatic_path_untouched_by_edit_features():
    from autoreels.cloud import select as _sel
    from autoreels import __main__ as cli
    src = inspect.getsource(_sel) + inspect.getsource(cli._cmd_run_impl)
    # filler removal, cold open and the title plate are set only on the manual/edit path.
    assert "remove_fillers" not in src
    assert "cold_open" not in src
    assert "title_overlay" not in src
