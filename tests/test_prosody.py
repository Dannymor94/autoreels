"""M2.2 sentence-end intonation (local/prosody.py): the clip should end where the VOICE ends.

Calibration (diagnostic M26, IMG_6848, all 332 sentence ends): every ending the owner accepted
ended low (pitch ≤ 26th percentile of the speaker) or faded out without pitch; the two he rejected
ended at the 50th («реализовался.») and 82nd («психолог.» — «он не закончил говорить»).
"""
import json

import numpy as np
import pytest

from autoreels.cloud.blocks import CandidateBlock, _numbered_sentences
from autoreels.cloud.plan import ManualPlanParams, build_manual_plan
from autoreels.core.models import Word
from autoreels.local.prosody import (ToneParams, classify, compute_prosody, load_prosody,
                                     tone_lookup, word_tones, write_prosody)


def _track(segments):
    """Pitch track every 10 ms from [(t0, t1, f_start, f_end)] (Hz, linear); 0 elsewhere."""
    t = np.arange(0.0, 10.0, 0.01)
    f = np.zeros_like(t)
    for a, b, fs, fe in segments:
        m = (t >= a) & (t < b)
        f[m] = np.linspace(fs, fe, m.sum())
    return t, f


def test_word_tones_end_percentile_and_voicing():
    # speaker mostly around 100 Hz; word A falls to 80 Hz (bottom), word B rises to 140 Hz (top),
    # word C has no pitch at all (creak / voice falling off)
    t, f = _track([(0.0, 3.0, 95, 110), (3.0, 3.5, 100, 80), (4.0, 4.5, 100, 140)])
    (a, b, c), ref = word_tones(t, f, [(3.0, 3.5), (4.0, 4.5), (5.0, 5.4)])
    assert 95 < ref < 110
    assert a["end_pct"] < 10 and b["end_pct"] > 90
    assert c == {"v": 0, "end_pct": None, "dur": 0.4}


@pytest.mark.parametrize("entry,expected", [
    ({"v": 27, "end_pct": 3.9, "dur": 0.4}, "final"),     # «йоге.» accepted
    ({"v": 36, "end_pct": 26.1, "dur": 0.4}, "final"),    # «другим.» accepted
    ({"v": 0, "end_pct": None, "dur": 0.26}, "final"),    # «нужно.» accepted: fades out, no pitch
    ({"v": 59, "end_pct": 50.1, "dur": 0.7}, "unsure"),   # «реализовался.» «можно улучшить»
    ({"v": 16, "end_pct": 81.9, "dur": 0.46}, "open"),    # «психолог.» «не закончил говорить»
    ({"v": 0, "end_pct": None, "dur": 0.08}, None),       # too short to judge by missing pitch
    ({"v": 2, "end_pct": None, "dur": 0.3}, "final"),
    (None, None),
])
def test_classify_matches_owner_verdicts(entry, expected):
    assert classify(entry) == expected


def test_classify_thresholds_are_params():
    assert classify({"v": 9, "end_pct": 40.0, "dur": 0.3}, ToneParams(final_pct_max=45)) == "final"


def _align():
    return {"version": 1, "transcript": {"n_words": 3, "t0_hash": "abc"},
            "words": [{"t0": 3.0, "start": 3.0, "end": 3.5, "score": 0.9},
                      {"t0": 4.0, "start": 4.0, "end": 4.5, "score": 0.9},
                      {"t0": 6.0, "start": None, "end": None, "score": 0.1, "far": True}],
            "untranscribed": []}


def test_payload_load_and_staleness(tmp_path):
    t, f = _track([(0.0, 3.0, 95, 110), (3.0, 3.5, 100, 80), (4.0, 4.5, 100, 140)])
    al = _align()
    payload = compute_prosody(al, t, f)
    assert [w["t0"] for w in payload["words"]] == [3.0, 4.0]          # unaligned word skipped
    p = tmp_path / "x.prosody.json"
    write_prosody(p, payload, "sha1")
    assert load_prosody(p, "sha1", al) is not None
    assert load_prosody(p, "other", al) is None                          # another source
    al2 = dict(al, transcript={"n_words": 3, "t0_hash": "zzz"})
    assert load_prosody(p, "sha1", al2) is None                          # another alignment
    data = json.loads(p.read_text())
    data["version"] = 99
    p.write_text(json.dumps(data))
    assert load_prosody(p, "sha1", al) is None
    assert load_prosody(tmp_path / "missing.json") is None


def test_tone_lookup_by_whisper_t0():
    tone = tone_lookup({"words": [{"t0": 3.0, "v": 20, "end_pct": 5.0, "dur": 0.5},
                                  {"t0": 4.0, "v": 20, "end_pct": 85.0, "dur": 0.5}]})
    assert tone(Word(word="а.", t0=3.0, t1=3.6))[0] == "final"
    kind, desc = tone(Word(word="б.", t0=4.0, t1=4.6))
    assert kind == "open" and "85/100" in desc
    assert tone(Word(word="в.", t0=9.0, t1=9.5)) is None
    assert tone_lookup(None) is None


# ── plan: ending report ─────────────────────────────────────────────────────────────────────

def _five():
    sents, words, smap_words = [], [], []
    for i in range(5):
        w = Word(word=f"с{i}.", t0=float(i), t1=i + 1.0)
        sents.append([w])
        words.append(w)
        smap_words.append({"idx": i, "t0": w.t0, "t1": w.t1, "audible_start": i + 0.2, "audible_end": i + 0.8})
    return sents, words, {"words": smap_words, "boundaries": []}


def _stub(tones):
    def tone(w):
        k = tones.get(w.word)
        return None if k is None else (k, f"{k}, test")
    return tone


def test_plan_reports_open_ending_with_finished_neighbours():
    sents, words, smap = _five()
    tone = _stub({"с0.": "final", "с1.": "open", "с2.": "open", "с3.": "final", "с4.": "final"})
    plan = build_manual_plan(sents, [1, 2, 3], words=words, smap=smap, params=ManualPlanParams(), tone=tone)
    msg = [w for w in plan.warnings if w.startswith("ending intonation")]
    assert len(msg) == 1
    assert "«с2.» sounds unfinished" in msg[0]
    assert "s1 «с0.», s4 «с3.», s5 «с4.»" in msg[0]
    # the reviewer's e: is never moved
    assert plan.body[-1].sentences[-1] == 3


def test_plan_silent_on_finished_or_unknown_ending():
    sents, words, smap = _five()
    for tones in ({"с2.": "final"}, {}):
        plan = build_manual_plan(sents, [1, 2, 3], words=words, smap=smap, tone=_stub(tones))
        assert not any(w.startswith("ending intonation") for w in plan.warnings)
    plan = build_manual_plan(sents, [1, 2, 3], words=words, smap=smap)
    assert not any(w.startswith("ending intonation") for w in plan.warnings)


def test_plan_reports_unclear_ending():
    sents, words, smap = _five()
    plan = build_manual_plan(sents, [1, 2, 3], words=words, smap=smap, tone=_stub({"с2.": "unsure"}))
    assert any("intonation unclear" in w and "none in this block" in w for w in plan.warnings)


# ── review export: ↗ marks a sentence whose voice stays up ─────────────────────────────────

def test_export_marks_open_sentence_end():
    ws = [Word(word="Я", t0=0.0, t1=0.2), Word(word="жил.", t0=0.3, t1=0.6),
          Word(word="Вот", t0=1.5, t1=1.7), Word(word="так.", t0=1.8, t1=2.1)]
    block = CandidateBlock(id="b", start=0.0, end=2.2, duration=2.2, text="Я жил. Вот так.",
                           boundary_reason="pause")
    plain = _numbered_sentences(block, ws)
    marked = _numbered_sentences(block, ws, tone=_stub({"жил.": "open", "так.": "final"}))
    assert plain == "[1] Я жил. [2] Вот так."
    assert marked == "[1] Я жил. ↗ [2] Вот так."


def test_pitch_track_on_synthetic_voice_sees_fall_and_rise():
    pytest.importorskip("parselmouth")
    from autoreels.local.prosody import SR, pitch_track

    def voice(f_start, f_end, dur):
        n = int(dur * SR)
        ph = 2 * np.pi * np.cumsum(np.linspace(f_start, f_end, n)) / SR
        return 0.2 * sum(np.sin(k * ph) / k for k in range(1, 8))

    sil = np.zeros(SR // 4)
    x = np.concatenate([voice(100, 110, 2.0), sil, voice(110, 80, 0.6), sil, voice(100, 150, 0.6), sil])

    def read(start, dur):
        a, b = int(start * SR), int((start + dur) * SR)
        return x[a:b]

    t, f0 = pitch_track(read, len(x) / SR, chunk=1.5)
    assert len(t) == len(f0) and np.all(np.diff(t) > 0)                 # chunks stitched in order
    fall_a, rise_a = 2.25, 2.25 + 0.6 + 0.25
    (fall, rise), _ = word_tones(t, f0, [(fall_a, fall_a + 0.6), (rise_a, rise_a + 0.6)])
    assert classify(fall) == "final" and classify(rise) == "open"


# ── REEL_SPEC §1.7: a start right after a sentence whose voice stays up joins mid-thought ─────

def test_plan_reports_start_after_open_sentence_with_strong_starts():
    sents, words, smap = [], [], {"words": [], "boundaries": []}
    texts = [["Раз", "два", "три", "четыре."], ["Пять", "шесть", "семь", "восемь."], ["Девять", "десять."],
             ["Одиннадцать", "двенадцать", "тринадцать", "четырнадцать."]]
    t = 0.0
    for s in texts:
        cur = []
        for x in s:
            w = Word(word=x, t0=t, t1=t + 0.4)
            cur.append(w)
            words.append(w)
            smap["words"].append({"t0": w.t0, "t1": w.t1, "audible_start": w.t0, "audible_end": w.t1})
            t += 0.5
        sents.append(cur)
        t += 0.5
    tone = _stub({"четыре.": "final", "восемь.": "open", "десять.": "final", "четырнадцать.": "final"})
    plan = build_manual_plan(sents, [3, 4], words=words, smap=smap, tone=tone)
    msg = [w for w in plan.warnings if w.startswith("weak start")]
    assert len(msg) == 1 and "s3" in msg[0]
    assert "s2 «Пять шесть семь восемь.…»" in msg[0] and "s4 «Одиннадцать" in msg[0]   # s3 is too short
    ok = build_manual_plan(sents, [2, 3], words=words, smap=smap, tone=tone)      # after «четыре.» (final)
    assert not any(w.startswith("weak start") for w in ok.warnings)
