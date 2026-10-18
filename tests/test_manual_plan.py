"""REEL_SPEC (docs/REEL_SPEC.md): the manual-path plan — windows, shots, ending, subtitles.

Two layers:
1. Synthetic unit tests of cloud/plan.py — every rule of §1–§4 on a tiny word list.
2. A golden test on real committed data (IMG_6848): words = transcripts/IMG_6848.txt tokens with
   the speech-map times, blocks rebuilt with the production functions (fingerprint must equal the
   review's), and every reel of benchmarks/golden/img6848_plan.yaml — computed independently of
   this code — must come out the same: windows, shot order, hook replay, first/last sentence.
"""
import json
import re
from pathlib import Path

import pytest
import yaml

from autoreels.cloud.plan import ManualPlanParams, build_manual_plan
from autoreels.core.models import Word

ROOT = Path(__file__).resolve().parents[1]


def _w(text, t0, t1):
    return Word(word=text, t0=t0, t1=t1)


def _sentences_and_map(spec):
    """spec: list of sentences, each a list of (word, t0, t1, audible_start, audible_end)."""
    sents, words, smap_words = [], [], []
    for sent in spec:
        cur = []
        for text, t0, t1, a, b in sent:
            w = _w(text, t0, t1)
            cur.append(w)
            words.append(w)
            smap_words.append({"idx": len(smap_words), "t0": t0, "t1": t1,
                               "audible_start": a, "audible_end": b})
        sents.append(cur)
    return sents, words, {"words": smap_words, "boundaries": []}


# Five one-word sentences, 1 s apart; audible span = middle 0.6 s of each slot.
_FIVE = [[(f"с{i}.", float(i), i + 1.0, i + 0.2, i + 0.8)] for i in range(5)]
P = ManualPlanParams(seam_pad_sec=0.04, end_air_sec=0.30, onset_margin_sec=0.06, hook_replay_min_pos=0.5)


def test_windows_cut_in_silence_by_audible_times():
    sents, words, smap = _sentences_and_map(_FIVE)
    plan = build_manual_plan(sents, [1, 2, 4], words=words, smap=smap, params=P)
    w1, w2 = plan.body
    assert w1.sentences == [1, 2] and w2.sentences == [4]
    assert w1.start == pytest.approx(0.16)          # audible start 0.2 − pad
    assert w1.end == pytest.approx(1.84)            # audible end 1.8 + pad (silence to 2.2)
    assert w2.start == pytest.approx(3.16)
    assert [w.word for w in plan.subtitles] == ["с0.", "с1.", "с3."]


def test_seam_in_continuous_speech_never_inside_a_word():
    # word B starts audibly 0.02 s after A ends: pad would cross into B → cut at the middle.
    spec = [[("а.", 0.0, 1.0, 0.1, 0.90)], [("б.", 0.9, 2.0, 0.92, 1.8)], [("в.", 2.0, 3.0, 2.1, 2.8)]]
    sents, words, smap = _sentences_and_map(spec)
    plan = build_manual_plan(sents, [1, 3], words=words, smap=smap, params=P)
    assert plan.body[0].end == pytest.approx(0.91)   # (0.90 + 0.92) / 2, not 0.94
    assert plan.body[0].end < 0.92


def test_shots_hook_close_body_wide_seams_flip_c_close():
    sents, words, smap = _sentences_and_map(_FIVE)
    plan = build_manual_plan(sents, [1, 2, 4, 5], words=words, smap=smap, params=P, hook=5, close=[2])
    assert plan.shot_sequence() == [("close", [5]), ("wide", [1]), ("close", [2]),
                                    ("wide", [4, 5])]
    # the c: span inside the wide window: from the 1|2 boundary to the window end
    w1 = plan.body[0]
    assert w1.shot == "wide"
    assert w1.close_intervals == [[pytest.approx(1.0 - w1.start), pytest.approx(w1.end - w1.start)]]


def test_c_on_whole_window_makes_it_close_and_next_seam_flips_back():
    sents, words, smap = _sentences_and_map(_FIVE)
    plan = build_manual_plan(sents, [1, 3, 4], words=words, smap=smap, params=P, close=[1])
    assert [w.shot for w in plan.body] == ["close", "wide"]
    assert plan.body[0].close_intervals == []


def test_ending_is_last_word_plus_air_capped_by_next_speech():
    sents, words, smap = _sentences_and_map(_FIVE)
    plan = build_manual_plan(sents, [1, 2], words=words, smap=smap, params=P)
    assert plan.end == pytest.approx(1.8 + 0.30)
    near = build_manual_plan(sents, [1, 2], words=words, smap=smap, params=P,
                             next_onset=lambda w: 1.9)
    assert near.end == pytest.approx(1.9 - 0.06)


def test_ending_never_cuts_the_last_word():
    sents, words, smap = _sentences_and_map(_FIVE)
    plan = build_manual_plan(sents, [1, 2], words=words, smap=smap, params=P,
                             next_onset=lambda w: 1.82)
    assert plan.end == pytest.approx(1.8)          # audible end, not 1.76
    assert plan.warnings and "no room" in plan.warnings[0]


def test_hook_replay_by_position():
    sents, words, smap = _sentences_and_map(_FIVE)
    late = build_manual_plan(sents, [1, 2, 3, 4, 5], words=words, smap=smap, params=P, hook=5)
    assert late.hook_replayed is True and 5 in late.body[-1].sentences
    early = build_manual_plan(sents, [1, 2, 3, 4, 5], words=words, smap=smap, params=P, hook=2)
    assert early.hook_replayed is False
    assert [w.sentences for w in early.body] == [[1], [3, 4, 5]]
    forced = build_manual_plan(sents, [1, 2, 3, 4, 5], words=words, smap=smap, params=P, hook=2,
                               hook_mode="!")
    assert forced.hook_replayed is True
    removed = build_manual_plan(sents, [1, 2, 3, 4, 5], words=words, smap=smap, params=P, hook=5,
                                hook_mode="-")
    assert removed.hook_replayed is False and removed.body[-1].sentences == [1, 2, 3, 4]


def test_forward_seam_without_silence_is_played_through():
    # sentence 2 is a Whisper duplicate: 3 starts audibly before 1 ends → no silence to cut.
    spec = [[("а.", 0.0, 1.0, 0.1, 0.95)], [("дубль.", 0.5, 1.0, 0.5, 0.9)],
            [("б.", 0.8, 2.0, 0.85, 1.8)], [("в.", 2.0, 3.0, 2.1, 2.8)]]
    sents, words, smap = _sentences_and_map(spec)
    plan = build_manual_plan(sents, [1, 3, 4], words=words, smap=smap, params=P)
    assert [w.sentences for w in plan.body] == [[1, 3, 4]]
    assert any("played through" in m for m in plan.warnings)


def test_subtitle_times_stay_inside_their_window():
    # Whisper t0 of the first kept word is earlier than its audible start − pad.
    spec = [[("а.", 0.0, 1.0, 0.1, 0.9)], [("б.", 1.0, 2.0, 1.5, 1.9)]]
    sents, words, smap = _sentences_and_map(spec)
    plan = build_manual_plan(sents, [2], words=words, smap=smap, params=P)
    (only,) = plan.subtitles
    # at least 50 ms inside: render rounds window edges to frames and drops words outside
    assert plan.body[0].start + 0.05 - 1e-9 <= only.t0 < plan.body[0].end - 0.05


# Map spans that overlap (Whisper stretched a word over its neighbour) are resolved by the energy
# track: the silence that touches the snapped edge is the real gap (IMG_6848 r05 «главное. | Ну»).

def test_ending_overlap_resolved_by_energy_gap_never_plays_next_word():
    spec = [[("самое", 0.0, 0.3, 0.0, 0.35), ("главное.", 0.3, 1.1, 0.4, 1.05)],
            [("Ну", 1.0, 1.08, 0.98, 1.13), ("и", 1.08, 1.2, 1.18, 1.25)]]
    sents, words, smap = _sentences_and_map(spec)
    smap["intervals"] = [[0.0, 0.92], [0.98, 2.0]]          # silence 0.92–0.98 before «Ну»
    plan = build_manual_plan(sents, [1], words=words, smap=smap, params=P)
    assert plan.last_audible_end == pytest.approx(0.92)
    assert plan.next_onset == pytest.approx(0.98)
    assert plan.end == pytest.approx(0.92)                  # not 1.05 (map end, inside «Ну»)
    assert plan.end < plan.next_onset


def test_seam_overlap_resolved_by_energy_gap_after_left_word():
    spec = [[("вещи.", 0.0, 1.0, 0.1, 1.0)], [("То", 0.93, 1.3, 0.93, 1.3), ("есть.", 1.3, 1.6, 1.35, 1.6)]]
    sents, words, smap = _sentences_and_map(spec)
    smap["intervals"] = [[0.1, 1.0], [1.14, 1.6]]           # silence 1.00–1.14 after «вещи.»
    plan = build_manual_plan(sents, [2], words=words, smap=smap, params=P)
    assert plan.body[0].start == pytest.approx(1.10)        # 1.14 − pad, not 0.93 (inside «вещи.»)


def test_word_cut_by_flags_only_cuts_inside_a_word():
    from autoreels.cloud.plan import SpeechTimes
    spec = [[("вещи.", 0.0, 1.0, 0.1, 1.0)], [("То", 0.93, 1.3, 0.93, 1.3), ("есть.", 1.3, 1.6, 1.35, 1.6)]]
    sents, words, smap = _sentences_and_map(spec)
    smap["intervals"] = [[0.1, 1.0], [1.14, 1.6]]
    t = SpeechTimes(words, smap)
    assert t.word_cut_by(0.5).word == "вещи."
    assert t.word_cut_by(1.07) is None                      # in the silence between the words
    assert t.word_cut_by(1.45).word == "есть."
    # continuous speech, no energy gap: the cut at the right word's onset is the only place → OK
    smap["intervals"] = [[0.1, 1.6]]
    t2 = SpeechTimes(words, smap)
    assert t2.word_cut_by(0.93) is None
    assert t2.word_cut_by(0.6).word == "вещи."


# ---------------------------------------------------------------- golden: real committed data

_GOLD = ROOT / "benchmarks" / "golden" / "img6848_plan.yaml"
_TXT = ROOT / "transcripts" / "IMG_6848.txt"
_SMAP = ROOT / "transcripts" / "IMG_6848.speechmap.json"


def _norm(text):
    return re.sub(r"[^\wё-]+", " ", text.lower().replace("ё", "е")).split()


@pytest.fixture(scope="module")
def img():
    if not (_GOLD.is_file() and _TXT.is_file() and _SMAP.is_file()):
        pytest.skip("IMG_6848 committed data not present")
    from autoreels.cloud.blocks import (_block_fingerprint, candidate_blocks, filter_blocks,
                                        parse_compact_answer, resolve_merge_groups)
    from autoreels.cloud.compress import compress_transcript
    from autoreels.cloud.edit import merge_group_sentences, strip_credit_words
    from autoreels.core.config import load_r0_config
    from autoreels.core.models import Transcript
    from autoreels.local.render import _next_speech_onset_after, _smap_word_lookup

    toks = _TXT.read_text(encoding="utf-8").split()
    smap = json.loads(_SMAP.read_text(encoding="utf-8"))
    assert len(toks) == len(smap["words"])
    raw = [Word(word=t, t0=e["t0"], t1=e["t1"]) for t, e in zip(toks, smap["words"])]
    r0 = load_r0_config(ROOT / "config" / "r0.yaml")
    comp = compress_transcript(Transcript(language="ru", words=raw),
                               pause_sec=r0.sentence_pause_sec, max_sentence_sec=r0.max_sentence_sec)
    allb = candidate_blocks(comp, min_sec=r0.min_meaningful_sec, max_sec=r0.max_duration,
                            min_pause_for_phrase_end=r0.min_pause_for_phrase_end,
                            block_target_sec=r0.block_target_sec)
    bf = r0.blocks_filter
    kept, _ = filter_blocks(allb, total_duration=allb[-1].end, head_skip_sec=bf.head_skip_sec,
                            tail_skip_sec=bf.tail_skip_sec, speech_density_min=bf.speech_density_min,
                            repetition_unique_ratio_min=bf.repetition_unique_ratio_min,
                            artefact_markers=bf.artefact_markers, promo_keywords=bf.promo_keywords,
                            signoff_phrases=bf.signoff_phrases, host_affirmations=[],
                            min_sec=r0.min_meaningful_sec, max_sec=r0.max_duration)
    gold = yaml.safe_load(_GOLD.read_text(encoding="utf-8"))
    assert _block_fingerprint(kept) == gold["review_fingerprint"], "blocks drifted from the review"
    words = strip_credit_words(raw, r0.credit_word_patterns)
    lookup = _smap_word_lookup(smap)

    def onset(w):
        r = _next_speech_onset_after(w.t0, smap, lookup, last_t1=w.t1)
        return None if r is None else r.onset

    seq_block = {i: b for i, b in enumerate(kept, 1)}
    plans = {}
    for reel in gold["reels"]:
        _, entries, errs, _ = parse_compact_answer(reel["review_line"])
        assert not errs
        (entry,) = entries
        groups, _ = resolve_merge_groups(entries, {s: seq_block[s] for s in seq_block}, 180.0)
        g = next(g for g in groups if g[0] == entry.seq)
        sents = merge_group_sentences([seq_block[s] for s in g], words)
        from autoreels.__main__ import _manual_play_order
        play = _manual_play_order(entry, sents, r0)
        mode = "!" if entry.hook_keep else ("-" if entry.hook_remove else None)
        plans[reel["id"]] = (reel, sents, build_manual_plan(
            sents, play, words=words, smap=smap, params=P, hook=entry.hook, hook_mode=mode,
            close=entry.c, next_onset=onset))
    return plans


_IDS = [f"r{i:02d}" for i in range(1, 9)]


@pytest.mark.parametrize("rid", _IDS)
def test_golden_windows_and_shots(img, rid):
    gold, sents, plan = img[rid]
    assert [w.sentences for w in plan.body] == gold["body_windows"]
    assert [[s, n] for s, n in plan.shot_sequence()] == gold["shots"]
    co = gold["cold_open"]
    if co is None:
        assert plan.cold_open is None
    else:
        assert plan.cold_open.sentences == [co["sentence"]]
        assert plan.hook_replayed is co["replayed_in_body"]
        assert _norm(" ".join(w.word for w in sents[co["sentence"] - 1])) == _norm(co["text"])


@pytest.mark.parametrize("rid", _IDS)
def test_golden_first_last_sentence_and_ending(img, rid):
    gold, sents, plan = img[rid]
    first = sents[plan.body[0].sentences[0] - 1]
    last = sents[plan.body[-1].sentences[-1] - 1]
    assert _norm(" ".join(w.word for w in first)) == _norm(gold["first_body_sentence"])
    assert _norm(" ".join(w.word for w in last)) == _norm(gold["last_sentence"])
    air = plan.end - plan.last_audible_end
    assert -1e-6 <= air <= P.end_air_sec + 1e-6
    # screen = sound: subtitles are exactly the played sentences' words, each inside a window
    played = [n for w in plan.windows for n in w.sentences]
    expect = {round(w.t0 * 1000) for n in played for w in sents[n - 1]}
    assert len(plan.subtitles) == len(expect)
    for w in plan.subtitles:
        assert any(win.start <= w.t0 < win.end for win in plan.windows)


def test_overlap_resolved_by_silence_near_the_overlap_zone():
    # IMG_6848 «дальше. | У»: map spans overlap (У 164.299 < дальше. 164.399), the energy silence
    # 164.44–164.56 starts 41 ms after the left word — that silence is the real gap.
    spec = [[("дальше.", 163.949, 164.829, 164.049, 164.399)],
            [("У", 164.349, 164.729, 164.299, 164.779), ("меня.", 164.729, 164.869, 164.829, 164.919)]]
    sents, words, smap = _sentences_and_map(spec)
    smap["intervals"] = [[162.34, 164.44], [164.56, 166.02]]
    plan = build_manual_plan(sents, [2], words=words, smap=smap, params=P)
    assert plan.body[0].start == pytest.approx(164.52)      # 164.56 − pad, not 164.299
    # a silence far from the overlap zone (> 0.10 s) is not used
    smap["intervals"] = [[162.34, 164.70], [164.80, 166.02]]
    far = build_manual_plan(sents, [2], words=words, smap=smap, params=P)
    assert far.body[0].start == pytest.approx(164.299)


# ---------------------------------------------------------------- M2.1: alignment-driven cuts

def _align(words_times, untr=()):
    return {"version": 1, "words": [{"t0": t0, "start": a, "end": b, "score": 0.9} for t0, a, b in words_times],
            "untranscribed": [list(u) for u in untr]}


def test_aligned_times_override_whisper_and_map():
    # Whisper stretches «жизнь.» over the hesitation after it (IMG_6848 r01).
    spec = [[("свою", 1.0, 1.3, 1.1, 1.35), ("жизнь.", 1.3, 3.6, 1.4, 3.65)],
            [("Для", 3.6, 3.7, 3.7, 3.73), ("этого.", 3.7, 4.0, 3.78, 4.0)]]
    sents, words, smap = _sentences_and_map(spec)
    smap["intervals"] = [[1.0, 1.62], [1.8, 3.6], [3.62, 4.1]]          # 1.8–3.6 = «а… ммм»
    al = _align([(1.0, 1.05, 1.3), (1.3, 1.35, 1.6), (3.6, 3.62, 3.72), (3.7, 3.78, 4.0)],
                untr=[(1.8, 3.6)])
    plan = build_manual_plan(sents, [1], words=words, smap=smap, params=P, align=al)
    assert plan.last_audible_end == pytest.approx(1.62)    # aligned 1.60 + its sound to 1.62
    assert plan.next_onset == pytest.approx(1.8)            # the hesitation is speech
    assert plan.end == pytest.approx(1.74)                  # 1.8 − onset margin, never into «ммм»
    old = build_manual_plan(sents, [1], words=words, smap=smap, params=P)
    assert old.end > 3.6                                    # without alignment: the whole «ммм»


def test_window_start_skips_untranscribed_filler_before_first_word():
    # IMG_6848 r06: «людям.» … «э» … «Чтобы» — the clip must not open on the filler.
    spec = [[("людям.", 0.0, 1.0, 0.1, 1.0)], [("Чтобы", 1.0, 1.6, 1.0, 1.6), ("выжить.", 1.6, 2.2, 1.6, 2.2)]]
    sents, words, smap = _sentences_and_map(spec)
    smap["intervals"] = [[0.1, 0.57], [0.65, 0.76], [0.81, 2.2]]
    al = _align([(0.0, 0.29, 0.57), (1.0, 0.94, 1.18), (1.6, 1.26, 1.6)], untr=[(0.65, 0.76), (0.81, 0.94)])
    plan = build_manual_plan(sents, [2], words=words, smap=smap, params=P, align=al)
    # the filler 0.81–0.94 ends exactly at the CTC onset: 40 ms go back to the word (CTC onsets are
    # a frame or two late), the cut lies midway → 20 ms before the onset, not at 0.79 (before the filler)
    assert plan.body[0].start == pytest.approx(0.92)


def test_final_stop_release_burst_belongs_to_the_word():
    # «есть.»: aligned end in the т-closure; the release burst follows after a short silence.
    spec = [[("я", 0.0, 0.2, 0.0, 0.2), ("есть.", 0.2, 0.9, 0.2, 0.9)], [("А", 1.5, 1.6, 1.5, 1.6)]]
    sents, words, smap = _sentences_and_map(spec)
    smap["intervals"] = [[0.0, 0.44], [0.54, 0.64], [1.5, 1.7]]
    al = _align([(0.0, 0.0, 0.2), (0.2, 0.24, 0.50), (1.5, 1.5, 1.6)])
    plan = build_manual_plan(sents, [1], words=words, smap=smap, params=P, align=al)
    assert plan.last_audible_end == pytest.approx(0.64)     # burst 0.54–0.64 kept
    assert plan.end == pytest.approx(0.94)                  # + 0.30 air


def test_seam_accent_close_lasts_first_sentences_then_wide():
    # 12 one-second sentences; play 1, 3-12: seam before 3 → close accent until ≥ 3 s played (3-6), then wide.
    spec = [[(f"с{i}.", float(i), i + 1.0, i + 0.05, i + 0.95)] for i in range(12)]
    sents, words, smap = _sentences_and_map(spec)
    play = [1] + list(range(3, 13))
    plan = build_manual_plan(sents, play, words=words, smap=smap, params=P)
    assert plan.shot_sequence() == [("wide", [1]), ("close", [3, 4, 5, 6]), ("wide", list(range(7, 13)))]
    w2 = plan.body[1]
    assert w2.shot == "wide" and len(w2.close_intervals) == 1
    assert 3.0 <= w2.close_intervals[0][1] <= 8.0


def test_short_sound_after_dip_is_the_word_end_not_new_speech():
    # IMG_6848 r05 «главное.»: aligned end 1.877, dip 1.83–1.91, sound 1.91–2.04, silence, then «Ну».
    spec = [[("самое", 1.0, 1.3, 1.0, 1.3), ("главное.", 1.3, 2.2, 1.5, 2.17)],
            [("Ну", 2.1, 2.2, 2.11, 2.19), ("и.", 2.2, 2.3, 2.25, 2.27)]]
    sents, words, smap = _sentences_and_map(spec)
    smap["intervals"] = [[1.0, 1.83], [1.91, 2.04], [2.10, 3.0]]
    al = _align([(1.0, 1.0, 1.3), (1.3, 1.5, 1.877), (2.1, 2.11, 2.19), (2.2, 2.25, 2.27)], untr=[(1.91, 2.04)])
    plan = build_manual_plan(sents, [1], words=words, smap=smap, params=P, align=al)
    assert plan.last_audible_end == pytest.approx(2.04)
    # but a second blob after a long tail is not absorbed (total tail ≤ 0.30 s)
    smap["intervals"] = [[1.0, 2.0], [2.07, 2.2], [2.3, 3.0]]
    al2 = _align([(1.0, 1.0, 1.3), (1.3, 1.5, 1.8), (2.1, 2.31, 2.4)], untr=[(2.07, 2.2)])
    plan2 = build_manual_plan(sents, [1], words=words, smap=smap, params=P, align=al2)
    assert plan2.last_audible_end == pytest.approx(2.0)


def test_subtitles_keep_text_order_when_whisper_times_go_back():
    """10h59 r03 / IMG_6848 r04 (M35): Whisper stitched «лучше всего работает. То есть» with «То»
    starting before «работает.»; sorting by time showed «лучше всего То работает. есть»."""
    spec = [[("лучше", 0.0, 0.4, 0.05, 0.4), ("всего", 0.5, 0.9, 0.55, 0.9), ("работает.", 1.2, 1.8, 1.25, 1.8)],
            [("То", 1.0, 1.1, 1.9, 2.0), ("есть", 2.1, 2.4, 2.15, 2.4), ("алгоритм.", 2.5, 3.2, 2.55, 3.2)]]
    sents, words, smap = _sentences_and_map(spec)
    plan = build_manual_plan(sents, [1, 2], words=words, smap=smap)
    assert [w.word for w in plan.subtitles] == ["лучше", "всего", "работает.", "То", "есть", "алгоритм."]
    ts = [w.t0 for w in plan.subtitles]
    assert ts == sorted(ts)


def test_near_zero_score_word_aligned_out_of_order_is_not_used():
    """09h33 533.8 s (M38): the aligner put «Первый» (Whisper 535.23 s, score 0.004) 1.5 s early,
    inside «Понятно,». The plan started the clip there and the seam check refused it (a cut inside
    «Понятно,»). Such a word is dropped and its time comes from the speech map; confident words
    out of order are kept as before. Values are the real align.json entries."""
    from autoreels.cloud.plan import SpeechTimes, clean_alignment
    al = {"words": [
        {"t0": 533.0504, "start": 533.629, "end": 533.949, "score": 0.921},   # «Понятно,»
        {"t0": 533.9704, "start": 533.989, "end": 534.069, "score": 0.963},
        {"t0": 535.2304, "start": 533.77, "end": 533.951, "score": 0.004},    # «Первый»
        {"t0": 535.9304, "start": 535.772, "end": 535.912, "score": 0.984},
    ], "untranscribed": []}
    kept, rejected = clean_alignment(al["words"])
    assert rejected == [535.2304] and len(kept) == 3
    words = [_w("Понятно,", 533.0504, 533.9704), _w("и", 533.9704, 534.0904),
             _w("Первый", 535.2304, 535.9104), _w("—", 535.9304, 535.9504)]
    smap = {"words": [{"t0": 535.2304, "t1": 535.9104, "audible_start": 535.28, "audible_end": 535.96}],
            "intervals": []}
    t = SpeechTimes(words, smap, al)
    assert t.audible(words[2]) == (535.28, 535.96) and t.rejected_alignment == [535.2304]
    assert t.audible(words[0]) == (533.629, 533.949)
    # both confident, out of order: kept (Whisper's text order may disagree with time)
    k2, r2 = clean_alignment([{"t0": 1.0, "start": 2.0, "end": 2.5, "score": 0.9},
                              {"t0": 1.5, "start": 1.0, "end": 1.4, "score": 0.8}])
    assert r2 == [] and len(k2) == 2
    # the earlier word is the guess: it goes, the confident later one stays
    k3, r3 = clean_alignment([{"t0": 1.0, "start": 2.0, "end": 2.5, "score": 0.01},
                              {"t0": 1.5, "start": 1.0, "end": 1.4, "score": 0.8}])
    assert r3 == [1.0] and [e["t0"] for e in k3] == [1.5]


def test_speech_in_no_sentence_between_two_played_ones_is_cut_at_a_seam():
    """M42: speech that is in no sentence of the clip (10h59 blocks 45+46: «Мышцы губ, подбородок…»,
    a short block the block builder dropped; IMG_6848 2+3: «Сначала я был инженером-строителем…»,
    which Whisper wrote after «Вопрос в том…» in the text) was never shown to the reviewer, yet the
    merged window played it without subtitles. Now the window splits there and the plan says why.
    Without such speech the window stays whole."""
    spec = [[("а.", 0.0, 1.0, 0.1, 0.9)], [("б.", 3.0, 4.0, 3.1, 3.9)], [("в.", 4.0, 5.0, 4.1, 4.9)]]
    sents, words, smap = _sentences_and_map(spec)
    lost = _w("инженером-строителем,", 1.2, 2.6)
    smap["words"].append({"idx": 3, "t0": 1.2, "t1": 2.6, "audible_start": 1.2, "audible_end": 2.6})
    all_words = sorted(words + [lost], key=lambda w: w.t0)
    plan = build_manual_plan(sents, [1, 2, 3], words=all_words, smap=smap, params=P)
    assert [w.sentences for w in plan.body] == [[1], [2, 3]]
    assert plan.body[0].end <= 1.2 and plan.body[1].start >= 2.6       # the lost speech is not played
    assert any("not in the review text" in x and "инженером-строителем" in x for x in plan.warnings)
    assert [w.word for w in plan.subtitles] == ["а.", "б.", "в."]
    whole = build_manual_plan(sents, [1, 2, 3], words=words, smap=smap, params=P)
    assert [w.sentences for w in whole.body] == [[1, 2, 3]]
    tiny = ManualPlanParams(seam_pad_sec=0.04, unseen_split_sec=5.0)       # below the threshold: kept
    assert [w.sentences for w in build_manual_plan(sents, [1, 2, 3], words=all_words, smap=smap,
                                                   params=tiny).body] == [[1, 2, 3]]


def test_sentence_sharing_its_sound_with_speech_of_no_sentence_is_an_error():
    """M42: IMG_6848 «Возможно, вы не понимаете, что такое психология принятия решений.» has 20 ms
    Whisper word times; the aligner put it at 1652.1–1653.9 s, over «…который любит себя» — speech
    in no sentence of the clip. Played, its subtitles would run over another text's sound
    (invariant 10). The plan reports an error naming both texts; the manual choice is not revised.
    Speech of no sentence that only sits NEXT to a played sentence is not an error."""
    spec = [[("а.", 0.0, 1.0, 0.1, 0.9)], [("б", 3.0, 3.02, 3.0, 3.5), ("в.", 3.02, 3.04, 3.5, 3.9)]]
    sents, words, smap = _sentences_and_map(spec)
    other = [_w("который", 2.9, 3.6), _w("любит", 3.6, 4.2)]
    smap["words"] += [{"idx": 9, "t0": 2.9, "t1": 3.6, "audible_start": 2.9, "audible_end": 3.6},
                      {"idx": 10, "t0": 3.6, "t1": 4.2, "audible_start": 3.6, "audible_end": 4.2}]
    all_words = sorted(words + other, key=lambda w: w.t0)
    plan = build_manual_plan(sents, [1, 2], words=all_words, smap=smap, params=P)
    assert len(plan.errors) == 1
    assert plan.errors[0].startswith("s2 «б в.» shares 0.9s of its sound") and "«который любит»" in plan.errors[0]
    # only sentence 1 played: its sound is its own
    assert build_manual_plan(sents, [1], words=all_words, smap=smap, params=P).errors == []
    # neighbours, no overlap: no error
    apart = [_w("который", 1.2, 2.0)]
    smap2 = dict(smap, words=[e for e in smap["words"] if e.get("idx") not in (9, 10)]
                 + [{"idx": 9, "t0": 1.2, "t1": 2.0, "audible_start": 1.2, "audible_end": 2.0}])
    ok = build_manual_plan(sents, [1, 2], words=sorted(words + apart, key=lambda w: w.t0), smap=smap2, params=P)
    assert ok.errors == []


def test_next_word_at_its_aligned_place_not_at_its_whisper_place():
    """M49, 10h59 r03: Whisper stretched «И» over the pause (591.205–591.985); the speech map gave it
    the first sound after that — the tail of «пробуйте.» (591.305). Forced alignment puts «И» at
    591.91, right before «главная». The plan used the map's onset: the next speech «began» inside
    the last word, the clip ended on the word with no air, and render flagged speech after the last
    subtitle. An aligned next word counts where alignment puts it; the map's untranscribed speech
    still counts."""
    ws = [_w("Вы", 590.2, 590.6), _w("пробуйте.", 590.905, 591.425), _w("И", 591.205, 591.985),
          _w("главная", 591.985, 592.325), _w("причина.", 592.325, 592.845)]
    smap = {"words": [
        {"t0": 590.2, "t1": 590.6, "audible_start": 590.25, "audible_end": 590.6},
        {"t0": 590.905, "t1": 591.425, "audible_start": 591.005, "audible_end": 591.255},
        {"t0": 591.205, "t1": 591.985, "audible_start": 591.305, "audible_end": 591.620},
        {"t0": 591.985, "t1": 592.325, "audible_start": 591.890, "audible_end": 592.375},
        {"t0": 592.325, "t1": 592.845, "audible_start": 592.425, "audible_end": 592.895}],
        "boundaries": [], "intervals": [[590.25, 590.6], [590.95, 591.62], [591.89, 592.9]]}
    align = {"words": [
        {"t0": 590.2, "start": 590.25, "end": 590.6, "score": 0.98},
        {"t0": 590.905, "start": 590.949, "end": 591.35, "score": 0.979},
        {"t0": 591.205, "start": 591.91, "end": 591.93, "score": 0.995},
        {"t0": 591.985, "start": 591.97, "end": 592.35, "score": 0.972},
        {"t0": 592.325, "start": 592.39, "end": 592.81, "score": 0.967}], "untranscribed": []}
    sents = [ws[:2], ws[2:]]
    prm = ManualPlanParams(seam_pad_sec=0.04, end_air_sec=0.30, onset_margin_sec=0.06)
    map_onset = lambda w: 591.305                                  # noqa: E731 — what render's smap lookup gives
    plan = build_manual_plan(sents, [1], words=ws, smap=smap, align=align, params=prm, next_onset=map_onset)
    assert plan.last_audible_end == pytest.approx(591.62)          # the word's tail, absorbed from the energy
    assert plan.next_onset == pytest.approx(591.91)                # «И» where alignment puts it
    assert plan.end == pytest.approx(591.85) and not any("no room" in w for w in plan.warnings)
    # untranscribed speech the map reports (not the next word's map onset) still cuts the clip
    untr = build_manual_plan(sents, [1], words=ws, smap=smap, align=align, params=prm,
                             next_onset=lambda w: 591.70)
    assert untr.next_onset == pytest.approx(591.70) and untr.end == pytest.approx(591.64)


def test_hook_air_keeps_real_silence_between_the_hook_and_the_body():
    """M74 (owner: «после крючка сильно резко идёт тело»): silence after the cold open and before the body,
    never into speech; 0 = the previous windows."""
    from dataclasses import replace
    sents, words, smap = _sentences_and_map(_FIVE)
    base = build_manual_plan(sents, [2, 4, 5], words=words, smap=smap, params=P, hook=3)
    air = build_manual_plan(sents, [2, 4, 5], words=words, smap=smap, params=replace(P, hook_air_sec=0.5), hook=3)
    assert base.hook_air is None and base.cold_open.end == pytest.approx(2.84) and base.body[0].start == pytest.approx(1.16)
    assert air.cold_open.end == pytest.approx(3.14)          # next speech 3.2 − margin 0.06, not 2.8 + 0.5
    assert air.body[0].start == pytest.approx(0.86)          # previous speech 0.8 + margin, not 1.2 − 0.5
    assert air.hook_air == (0.3, 0.3)
    assert [w.word for w in air.subtitles] == [w.word for w in base.subtitles]
    assert any(ln.startswith("hook air  +0.30s") for ln in air.describe(sents))
    no_hook = build_manual_plan(sents, [2, 4, 5], words=words, smap=smap, params=replace(P, hook_air_sec=0.5))
    assert no_hook.hook_air is None and no_hook.body[0].start == pytest.approx(1.16)


def test_hook_air_never_plays_the_same_silence_twice():
    """M77 (owner: «где-то повторение — кадр двоится»): the body starts right after the hook in the source — the hook's
    air and the body's air were the same silence, played twice. It is shared once, cut in its middle."""
    from dataclasses import replace
    sents, words, smap = _sentences_and_map(_FIVE)
    plan = build_manual_plan(sents, [2, 4, 5], words=words, smap=smap, params=replace(P, hook_air_sec=0.5), hook=1)
    co, b0 = plan.cold_open, plan.body[0]
    assert co.end == pytest.approx(1.0) and b0.start == pytest.approx(1.0)       # no overlap: 0.84 → 1.0 ← 1.16
    assert co.end <= b0.start + 1e-9


def test_a_last_word_fading_into_the_next_speech_ends_before_it():
    """M80 (PXL_20260729_copy r02, local transcript: «регулярно.» audible to 220.487, next word at 220.471 → render
    [ERROR] «next speech before clip end»): a small tail overlap is cut, a big one keeps the old ending."""
    from dataclasses import replace
    spec = [[("Раз", 0.0, 0.5, 0.1, 0.5), ("регулярно.", 0.6, 1.5, 0.6, 1.50)],
            [("Дальше", 1.48, 2.0, 1.484, 2.0)]]
    sents, words, smap = _sentences_and_map(spec)
    old = build_manual_plan(sents, [1], words=words, smap=smap, params=P)
    assert old.end == pytest.approx(1.50) and any("no room after last word" in w for w in old.warnings)
    new = build_manual_plan(sents, [1], words=words, smap=smap, params=replace(P, tail_overlap_sec=0.1))
    assert new.end == pytest.approx(1.484 - 0.06) and any("fades into the next speech" in w for w in new.warnings)
    far = [[("Раз", 0.0, 0.5, 0.1, 0.5), ("регулярно.", 0.6, 1.5, 0.6, 1.50)], [("Дальше", 1.3, 2.0, 1.30, 2.0)]]
    sents2, words2, smap2 = _sentences_and_map(far)
    big = build_manual_plan(sents2, [1], words=words2, smap=smap2, params=replace(P, tail_overlap_sec=0.1))
    assert big.end == pytest.approx(1.50) and any("no room after last word" in w for w in big.warnings)
