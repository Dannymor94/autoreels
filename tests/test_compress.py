"""Сжатие транскрипта (cloud/compress.py).

Word-level → sentence-level ПРОЕКЦИЯ для LLM (шаг 5): сжатие ВХОДА под 6K TPM Groq,
НЕ потеря данных. word-level обязан дожить до R1 (snap) и R3 (субтитры) — compress
не мутирует Transcript. Формат строки — контракт с prompts/r0_system.md §1.
"""
from autoreels.core.models import Transcript, Word
from autoreels.cloud.compress import compress_transcript


def _w(word, t0, t1):
    return Word(word=word, t0=t0, t1=t1)


def test_splits_on_punctuation():
    # Пунктуация рвёт предложение даже когда паузы малы (< порога).
    tr = Transcript(language="ru", words=[
        _w("Самый", 0.1, 0.5), _w("важный", 0.5, 0.9), _w("момент.", 0.9, 1.3),
        _w("Это", 1.5, 1.8), _w("тест.", 1.8, 2.1),
    ])
    lines = compress_transcript(tr, pause_sec=0.6).splitlines()
    assert lines == [
        "[0000.1-0001.3] Самый важный момент.",
        "[0001.5-0002.1] Это тест.",
    ]


def test_splits_on_pause_when_punctuation_missing():
    # Whisper на русском часто роняет пунктуацию → граница по паузе > порога.
    tr = Transcript(language="ru", words=[
        _w("одно", 0.0, 0.4), _w("предложение", 0.4, 1.0),
        _w("другое", 1.8, 2.2), _w("мысль", 2.2, 2.7),   # пауза 0.8с > 0.6
    ])
    lines = compress_transcript(tr, pause_sec=0.6).splitlines()
    assert lines == [
        "[0000.0-0001.0] одно предложение",
        "[0001.8-0002.7] другое мысль",
    ]


def test_line_format_absolute_seconds():
    tr = Transcript(language="ru", words=[
        _w("Самый", 124.3, 127.0), _w("важный", 127.0, 131.0),
    ])
    line = compress_transcript(tr, pause_sec=0.6)
    assert line == "[0124.3-0131.0] Самый важный"


def test_word_level_preserved_not_mutated():
    words = [_w("а", 0.0, 0.5), _w("б", 0.5, 1.0)]
    tr = Transcript(language="ru", words=words)
    before = len(tr.words)
    compress_transcript(tr, pause_sec=0.6)
    # Оригинальные words нетронуты — доживут до R1/R3.
    assert len(tr.words) == before
    assert tr.words[0] == Word(word="а", t0=0.0, t1=0.5)


def test_compression_reduces_volume():
    # Направление, не «ровно 2×». Коэффициент печатаем (pytest -s), не ассертим.
    words = []
    t = 0.0
    for i in range(30):
        words.append(_w(f"слово{i}", t, t + 0.3))
        t += 0.3
    tr = Transcript(language="ru", words=words)
    compressed = compress_transcript(tr, pause_sec=0.6)
    word_level = tr.model_dump_json()
    ratio = len(word_level) / max(len(compressed), 1)
    print(f"compress ratio (word_level/compressed) = {ratio:.2f}x")
    assert len(compressed) < len(word_level)


def test_empty_transcript_gives_empty_output():
    tr = Transcript(language="ru", words=[])
    assert compress_transcript(tr, pause_sec=0.6) == ""
