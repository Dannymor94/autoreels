"""Форматирование транскрипта под разные выходы (отдельная transcribe-команда).

Инварианты:
- text — связный читаемый текст для переработки в контент: слова склеены, абзацы по
  длинным паузам, БЕЗ таймкодов;
- srt/vtt — субтитры с таймкодами (плееры/YouTube);
- json — сырой word-level {word,t0,t1}.
"""
import json

from autoreels.core.models import Transcript, Word
from autoreels.cloud.transcribe_formats import to_text, to_srt, to_vtt, to_json


def W(word, t0, t1):
    return Word(word=word, t0=t0, t1=t1)


# ------------------------------------------------------------------ text (для контента)

def test_to_text_joins_words_into_readable_line():
    t = Transcript(language="ru", words=[W("Привет", 0.0, 0.5), W("мир", 0.6, 1.0)])
    assert to_text(t, sentence_pause_sec=0.35, paragraph_pause_sec=2.0) == "Привет мир"


def test_to_text_splits_paragraphs_on_long_pause():
    t = Transcript(language="ru", words=[
        W("Первая", 0.0, 0.4), W("мысль.", 0.5, 0.9),
        W("Вторая", 4.0, 4.4), W("мысль.", 4.5, 4.9),
    ])
    out = to_text(t, sentence_pause_sec=0.35, paragraph_pause_sec=2.0)
    assert out == "Первая мысль.\n\nВторая мысль."


def test_to_text_same_paragraph_on_short_pause():
    t = Transcript(language="ru", words=[W("Раз.", 0.0, 0.4), W("Два.", 0.9, 1.3)])
    out = to_text(t, sentence_pause_sec=0.35, paragraph_pause_sec=2.0)
    assert out == "Раз. Два."
    assert "\n\n" not in out


def test_to_text_has_no_timecodes():
    t = Transcript(language="ru", words=[W("Текст", 0.0, 1.0), W("тут", 1.1, 2.0)])
    out = to_text(t, sentence_pause_sec=0.35, paragraph_pause_sec=2.0)
    assert "[" not in out and "-->" not in out and ":" not in out


def test_to_text_empty_is_empty_string():
    t = Transcript(language="ru", words=[])
    assert to_text(t, sentence_pause_sec=0.35, paragraph_pause_sec=2.0) == ""


# ------------------------------------------------------------------ srt

def test_to_srt_has_index_timecodes_and_text():
    t = Transcript(language="ru", words=[W("Привет", 0.0, 0.5), W("мир.", 0.6, 1.2)])
    out = to_srt(t, sentence_pause_sec=0.35)
    assert out.startswith("1\n")
    assert "00:00:00,000 --> 00:00:01,200" in out
    assert "Привет мир." in out


def test_to_srt_numbers_cues_sequentially():
    t = Transcript(language="ru", words=[
        W("Раз.", 0.0, 0.4), W("Два.", 5.0, 5.4),
    ])
    out = to_srt(t, sentence_pause_sec=0.35)
    assert "1\n" in out and "2\n" in out


# ------------------------------------------------------------------ vtt

def test_to_vtt_header_and_dot_millis():
    t = Transcript(language="ru", words=[W("Привет", 0.0, 0.5), W("мир.", 0.6, 1.2)])
    out = to_vtt(t, sentence_pause_sec=0.35)
    assert out.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:01.200" in out


# ------------------------------------------------------------------ json (word-level)

def test_to_json_is_word_level_records():
    t = Transcript(language="ru", words=[W("Привет", 0.0, 0.5), W("мир", 0.6, 1.0)])
    data = json.loads(to_json(t))
    assert data == [
        {"word": "Привет", "t0": 0.0, "t1": 0.5},
        {"word": "мир", "t0": 0.6, "t1": 1.0},
    ]


def test_to_json_empty_is_empty_list():
    assert json.loads(to_json(Transcript(language="ru", words=[]))) == []
