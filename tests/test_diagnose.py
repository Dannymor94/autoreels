"""Классификация концов клипов для diagnose-cuts (ядро — чистые функции)."""
from autoreels.cloud.diagnose import classify_end, summarize
from autoreels.core.models import Word

HANG = ["и", "а", "но", "что", "это", "как", "то", "есть", "вот"]
CFG = dict(min_pause=1.5, max_micro_pause=0.4, tail_pad_sec=0.7, hanging_words=HANG)


def _w(t0, t1, word):
    return Word(word=word, t0=t0, t1=t1)


def test_clean_on_sentence_punct():
    words = [_w(0, 0.5, "всё"), _w(0.5, 1.0, "понятно."), _w(2.0, 2.5, "Дальше")]
    d = classify_end("r01", 0.0, 1.0, words, **CFG)
    assert d.verdict == "CLEAN" and d.end_type == "фраза(.!?)"


def test_clean_on_long_pause():
    words = [_w(0, 0.5, "слово"), _w(0.5, 1.0, "конец"), _w(3.0, 3.5, "потом")]  # пауза 2.0 ≥ 1.5
    d = classify_end("r01", 0.0, 1.0, words, **CFG)
    assert d.verdict == "CLEAN" and "пауза" in d.end_type


def test_clean_on_end_of_speech():
    words = [_w(0, 0.5, "слово"), _w(0.5, 1.0, "последнее")]                    # нет next
    d = classify_end("r01", 0.0, 1.0, words, **CFG)
    assert d.verdict == "CLEAN" and d.end_type == "конец речи"


def test_hard_on_hanging_word():
    words = [_w(0, 0.5, "нереализованный"), _w(0.5, 1.0, "это"), _w(1.4, 1.9, "всего")]
    d = classify_end("r01", 0.0, 1.0, words, **CFG)
    assert d.verdict == "HARD" and d.end_type == "висячее"


def test_hard_on_comma_word():
    words = [_w(0, 0.5, "смотри"), _w(0.5, 1.0, "внимательно,"), _w(1.6, 2.0, "дальше")]
    d = classify_end("r01", 0.0, 1.0, words, **CFG)
    assert d.verdict == "HARD" and d.end_type == "запятая"


def test_hard_on_mid_word():
    words = [_w(0, 0.5, "мы"), _w(0.5, 1.0, "делаем"), _w(1.1, 1.6, "дальше")]   # gap 0.1 < 0.4
    d = classify_end("r01", 0.0, 1.0, words, **CFG)
    assert d.verdict == "HARD" and d.end_type == "мид-слово"


def test_soft_on_medium_pause():
    words = [_w(0, 0.5, "слово"), _w(0.5, 1.0, "думал"), _w(1.7, 2.2, "потом")]  # gap 0.7 ∈ [0.4,1.5)
    d = classify_end("r01", 0.0, 1.0, words, **CFG)
    assert d.verdict == "SOFT" and abs(d.pause_after - 0.7) < 1e-6


def test_cause_pad_tail_overshoot():
    """Конец на слове после чистой фразы, перелёт ≈ tail_pad → причина PAD-хвост."""
    words = [_w(0, 0.5, "фраза."), _w(0.6, 0.7, "И"), _w(0.7, 1.0, "вот")]      # «фраза.» конец в 0.5
    # клип кончается в 1.05 (перелёт +0.55 за «фраза.» 0.5), последнее слово «вот» gap None→конец речи
    words.append(_w(1.2, 1.3, "ещё"))
    d = classify_end("r01", 0.0, 1.05, words, **CFG)
    assert d.verdict == "HARD"
    assert "PAD-хвост" in d.cause


def test_cause_snap_fallback_no_clean_boundary():
    """Сплошная речь без пунктуации/паузы ≥1.5 → причина snap-fallback."""
    words = [_w(0, 0.5, "мы"), _w(0.5, 1.0, "делаем"), _w(1.1, 1.6, "это"), _w(1.7, 2.2, "дальше")]
    d = classify_end("r01", 0.0, 1.0, words, **CFG)
    assert d.verdict == "HARD"
    assert "snap-fallback" in d.cause


def test_summarize_counts_and_causes():
    diags = [
        classify_end("r1", 0, 1.0, [_w(0, 1.0, "понятно.")], **CFG),                      # CLEAN
        classify_end("r2", 0, 1.0, [_w(0, 1.0, "это"), _w(1.4, 1.9, "всего")], **CFG),    # HARD висячее
        classify_end("r3", 0, 1.0, [_w(0, 1.0, "думал"), _w(1.7, 2.2, "п")], **CFG),      # SOFT
    ]
    s = summarize(diags)
    assert s["clean"] == 1 and s["soft"] == 1 and s["hard"] == 1
    assert sum(s["causes"].values()) == 1                # одна HARD-причина
