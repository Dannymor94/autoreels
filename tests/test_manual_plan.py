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
