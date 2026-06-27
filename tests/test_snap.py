"""R4: детерминированная подтяжка границ сегментов к словам/паузам (cloud/snap.py).

LLM предлагает start/end приблизительно (часто в середине слова → резкий обрыв). КОД
подтягивает границы к word-таймкодам транскрипта: end → к концу слова/паузе + небольшой
хвост (фраза договаривается); start → к началу слова/после паузы. Рубрика/LLM не трогаются.
Нет подходящей границы рядом → сегмент не меняется. Хвост не выводит за max_duration пресета.
"""
from autoreels.cloud.snap import snap_segments
from autoreels.core.models import Reel, Word


def _w(t0: float, t1: float, word: str = "x") -> Word:
    return Word(word=word, t0=t0, t1=t1)


def _reel(start: float, end: float) -> Reel:
    return Reel(id="r01", start=start, end=end, score=80,
                hook="h", title="t", description="d", reason="r", topic="x")


# Транскрипт: две фразы с паузой между ними (паузы — gap между словами > pause_sec).
#  с1: 30.0–31.6 ("слово1 слово2 стоп"), пауза 31.6→33.0 (1.4с),
#  с2: 33.0–34.0 ("далее ещё"), пауза 34.0→36.0 (2.0с), "конец" 36.0–36.6 (конец речи).
WORDS = [
    _w(0.0, 0.5, "intro"),       # далеко до клипа
    _w(30.0, 30.4, "слово1"),
    _w(30.5, 31.0, "слово2"),
    _w(31.1, 31.6, "стоп"),      # пауза после → граница 31.6
    _w(33.0, 33.5, "далее"),
    _w(33.6, 34.0, "ещё"),       # пауза после → граница 34.0
    _w(36.0, 36.6, "конец"),     # последнее слово → граница 36.6
]
CFG = dict(tail_sec=0.3, window_sec=1.5, pause_sec=0.35, max_duration=59)


def test_end_midword_snaps_to_pause_plus_tail():
    # end=31.3 в середине слова «стоп» (31.1–31.6) → к паузе 31.6 + хвост 0.3 = 31.9
    r = _reel(30.0, 31.3)
    snap_segments([r], WORDS, **CFG)
    assert abs(r.end - 31.9) < 1e-6              # пауза 31.6 + хвост 0.3
    assert r.start == 30.0                       # начало уже на границе слова — не двинулось


def test_start_midword_snaps_to_word_boundary():
    # start=30.6 в середине «слово2» → к началу фразы 30.0 (граница слова после паузы)
    r = _reel(30.6, 33.4)
    snap_segments([r], WORDS, **CFG)
    assert r.start == 30.0
    assert r.start != 30.6                        # не начинается с обрубка слова


def test_start_pulled_to_phrase_beginning_within_window():
    # start=33.7 в середине «ещё» (фраза «далее ещё» началась в 33.0 после паузы) →
    # лёгкое вытягивание к началу мысли 33.0, в пределах окна ±1.5с (не к 36.0 за окном)
    r = _reel(33.7, 36.4)
    snap_segments([r], WORDS, **CFG)
    assert r.start == 33.0                        # начало смысловой фразы, не середина


def test_end_fallback_to_word_end_when_no_pause_nearby():
    # плотная речь без пауз: нет паузы рядом → к ближайшему КОНЦУ слова (не середине)
    dense = [_w(40.0 + 0.4 * i, 40.0 + 0.4 * i + 0.3, "wд") for i in range(12)]  # без зазоров > pause
    r = _reel(40.0, 40.55)                        # 40.55 в середине 2-го слова (40.4–40.7)
    snap_segments([r], dense, **CFG)
    # ближайший конец слова к 40.55 — 40.7, + хвост 0.3 = 41.0; не середина слова
    assert abs(r.end - 41.0) < 1e-6


def test_tail_trimmed_to_not_exceed_max_duration():
    # max_duration мал: граница 31.6 в пределах, но 31.6+0.3 вышло бы за лимит → хвост подрезан
    r = _reel(30.0, 31.3)
    snap_segments([r], WORDS, tail_sec=0.3, window_sec=1.5, pause_sec=0.35, max_duration=1.7)
    assert r.end == 31.7                          # ровно start+max_duration (хвост 0.3→0.1)
    assert r.end - r.start <= 1.7 + 1e-9


def test_no_boundary_in_range_leaves_segment_untouched():
    # предложенные границы далеко от любых слов (в «тишине» вне ±search) → не трогаем
    r = _reel(50.0, 52.0)
    snap_segments([r], WORDS, **CFG)
    assert (r.start, r.end) == (50.0, 52.0)


def test_empty_transcript_leaves_segment_untouched():
    # нет word-level (тишина/пустой транскрипт) → нечего подтягивать, сегмент как есть
    r = _reel(30.0, 31.3)
    snap_segments([r], [], **CFG)
    assert (r.start, r.end) == (30.0, 31.3)


def test_multiple_reels_each_snapped():
    r1 = _reel(30.0, 31.3)       # end → 31.9
    r2 = _reel(33.0, 35.0)       # end=35.0 в тишине после «ещё» (34.0); пауза 34.0 в ±1.5 → 34.3
    snap_segments([r1, r2], WORDS, **CFG)
    assert abs(r1.end - 31.9) < 1e-6
    assert abs(r2.end - 34.3) < 1e-6   # 34.0 (пауза) + 0.3
