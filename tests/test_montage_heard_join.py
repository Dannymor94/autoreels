"""M134 (invariant 9): «a piece goes straight on from the previous one» by the pause HEARD between the two
sentences (speech map / alignment), not by the Whisper gap — Whisper times overlap at sentence ends (IMG_6848:
65 of 345 sentence ends have a negative gap), and such a straight-on piece got a seam."""
from __future__ import annotations

from types import SimpleNamespace

from autoreels.cloud.montage import build_montage, parse_montage
from autoreels.cloud.plan import SpeechTimes, heard_pause
from autoreels.core.config import MontageConfig
from autoreels.core.models import Word


def _w(text, t0, t1):
    return Word(word=text, t0=t0, t1=t1)


def _one_block(s1, s2, s3):
    bl = SimpleNamespace(start=s1[0].t0, end=s3[-1].t1, sents=[s1, s2, s3])
    return {1: bl}


def test_flag_is_off_by_default():
    assert MontageConfig().join_heard is False


def test_whisper_overlap_is_a_seam_without_heard_pause_and_joined_with_it():
    s1 = [_w("раз", 0.0, 0.4), _w("два.", 0.5, 1.02)]
    s2 = [_w("три", 1.0, 1.4), _w("четыре.", 1.5, 1.9)]            # Whisper gap −0.02 s
    s3 = [_w("пять.", 2.5, 2.9)]
    bl = _one_block(s1, s2, s3)
    (e,), _ = parse_montage("M 80 | 1.1 1.2\n")
    assert build_montage(e, bl, lambda b: b.sents).breaks == [2]        # before: a seam
    mb = build_montage(e, bl, lambda b: b.sents, pause=lambda a, b: 0.1)
    assert mb.breaks == [] and mb.pieces == [(1, 2)] and mb.joined == ["1-1 + 1.2"]


def test_long_heard_pause_is_a_seam_even_when_whisper_shows_none():
    s1 = [_w("Хорошо.", 0.0, 3.3)]                                   # Whisper stretched the word over the silence
    s2 = [_w("Второй.", 3.3, 3.8)]
    s3 = [_w("Третий.", 4.0, 4.5)]
    bl = _one_block(s1, s2, s3)
    (e,), _ = parse_montage("M 80 | 1.1 1.2\n")
    assert build_montage(e, bl, lambda b: b.sents).breaks == []          # Whisper gap 0.0: joined
    assert build_montage(e, bl, lambda b: b.sents, pause=lambda a, b: 2.76).breaks == [2]


def test_a_word_between_the_sentences_is_never_straight_on():
    s1 = [_w("раз.", 0.0, 0.4)]
    s2 = [_w("два.", 0.6, 1.0)]
    s3 = [_w("три.", 1.2, 1.6)]
    bl = _one_block(s1, s2, s3)
    (e,), _ = parse_montage("M 80 | 1.1 1.2\n")
    assert build_montage(e, bl, lambda b: b.sents, pause=lambda a, b: None).breaks == [2]


def test_heard_pause_from_the_speech_map():
    a, b, c = _w("два.", 0.5, 1.02), _w("три", 1.0, 1.4), _w("четыре.", 1.5, 1.9)
    smap = {"words": [{"t0": 0.5, "audible_start": 0.5, "audible_end": 0.9},
                      {"t0": 1.0, "audible_start": 1.05, "audible_end": 1.4},
                      {"t0": 1.5, "audible_start": 1.5, "audible_end": 1.9}]}
    times = SpeechTimes([a, b, c], smap)
    assert abs(heard_pause(times, a, b) - 0.15) < 1e-6                 # heard 0.9 → 1.05, Whisper −0.02
    assert heard_pause(times, a, c) is None                            # «три» stands between them
