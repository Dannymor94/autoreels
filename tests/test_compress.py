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


def test_force_split_long_sentence_into_chunks():
    import re
    # 60 непрерывных слов по 1.5с = одно «предложение» 90с (нет пунктуации/пауз).
    words = [_w(f"w{i}", i * 1.5, i * 1.5 + 1.5) for i in range(60)]
    tr = Transcript(language="ru", words=words)
    out = compress_transcript(tr, pause_sec=0.35, max_sentence_sec=30).splitlines()
    assert len(out) >= 3                                  # 90с / 30с → строк-гигантов нет
    for ln in out:
        m = re.match(r"\[(\d+\.\d)-(\d+\.\d)\] .", ln)    # формат строки цел
        assert m
        assert float(m.group(2)) - float(m.group(1)) <= 30.0 + 1e-6   # каждая ≤ max
    # Дробление по границам СЛОВ: конкатенация текстов = исходный порядок, слова целы.
    joined = " ".join(ln.split("] ", 1)[1] for ln in out)
    assert joined == " ".join(w.word for w in words)


def test_lower_pause_threshold_yields_more_boundaries():
    # Пауза 0.5с: при 0.6 не рвёт, при 0.35 рвёт → больше границ.
    words = [_w("а", 0.0, 1.0), _w("б", 1.5, 2.0), _w("в", 2.0, 3.0)]   # gap а→б = 0.5
    tr = Transcript(language="ru", words=words)
    n_06 = len(compress_transcript(tr, pause_sec=0.6).splitlines())
    n_035 = len(compress_transcript(tr, pause_sec=0.35).splitlines())
    assert n_035 > n_06


def test_force_split_preserves_word_level():
    words = [_w(f"w{i}", i * 1.0, i * 1.0 + 1.0) for i in range(50)]
    tr = Transcript(language="ru", words=words)
    compress_transcript(tr, pause_sec=0.35, max_sentence_sec=30)
    assert len(tr.words) == 50                            # word-level не тронут


def test_moment_within_preset_not_split():
    # Регресс: момент 50с при max_sentence_sec=89 (привязка к пресету) — целая строка.
    words = [_w(f"w{i}", i * 1.0, i * 1.0 + 1.0) for i in range(50)]   # 0..50с слитно
    tr = Transcript(language="ru", words=words)
    out = compress_transcript(tr, pause_sec=0.35, max_sentence_sec=89).splitlines()
    assert len(out) == 1


def test_force_split_cuts_at_longest_pause():
    # 5 слитных слов (0–10), пауза 2с, ещё 5 слитных (12–22). max=15 → рез по паузе.
    words = [_w(f"a{i}", i * 2.0, i * 2.0 + 2.0) for i in range(5)]        # 0..10
    words += [_w(f"b{i}", 12.0 + i * 2.0, 14.0 + i * 2.0) for i in range(5)]  # 12..22
    tr = Transcript(language="ru", words=words)
    out = compress_transcript(tr, pause_sec=5.0, max_sentence_sec=15).splitlines()
    assert len(out) == 2
    import re
    end0 = float(re.match(r"\[(\d+\.\d)-(\d+\.\d)\]", out[0]).group(2))
    start1 = float(re.match(r"\[(\d+\.\d)-(\d+\.\d)\]", out[1]).group(1))
    assert end0 == 10.0 and start1 == 12.0               # рез ровно на паузе, не в фразе
