"""R4: детерминированная подтяжка границ сегментов к словам/паузам (cloud/snap.py).

LLM предлагает start/end приблизительно (часто в середине слова → резкий обрыв). КОД
подтягивает границы к word-таймкодам транскрипта: end → к концу слова/паузе + небольшой
хвост (фраза договаривается); start → к началу слова/после паузы. Рубрика/LLM не трогаются.
Нет подходящей границы рядом → сегмент не меняется. Хвост не выводит за max_duration пресета.
"""
import pytest

from autoreels.cloud.snap import apply_padding, snap_segments
from autoreels.core.models import Reel, Word

HANGING = ["и", "а", "но", "что", "это", "как", "в", "на",
           "потому", "чтобы", "если", "когда", "то", "есть", "вот"]


def _w(t0: float, t1: float, word: str = "x") -> Word:
    return Word(word=word, t0=t0, t1=t1)


def _reel(start: float, end: float) -> Reel:
    return Reel(id="r01", start=start, end=end, score=80,
                hook="h", title="t", description="d", reason="r", topic="x")


# Транскрипт: две фразы с паузой между ними (паузы — gap между словами > min_pause 0.6).
#  с1: 30.0–31.6 ("слово1 слово2 стоп"), пауза 31.6→33.0 (1.4с),
#  с2: 33.0–34.0 ("далее ещё"), пауза 34.0→36.0 (2.0с), "конец" 36.0–36.6 (конец речи).
WORDS = [
    _w(0.0, 0.5, "intro"),       # далеко до клипа
    _w(30.0, 30.4, "слово1"),
    _w(30.5, 31.0, "слово2"),
    _w(31.1, 31.6, "стоп"),      # пауза 1.4с после → завершение мысли 31.6
    _w(33.0, 33.5, "далее"),
    _w(33.6, 34.0, "ещё"),       # пауза 2.0с после → завершение 34.0
    _w(36.0, 36.6, "конец"),     # последнее слово → завершение 36.6
]
CFG = dict(tail_sec=0.3, window_sec=1.5, max_duration=59,
           min_pause_for_phrase_end=0.6, max_micro_pause=0.4, hanging_words=HANGING)


def test_end_midword_snaps_to_phrase_end_plus_tail():
    # end=31.3 в середине «стоп» → завершение мысли (пауза) 31.6 + хвост 0.3 = 31.9
    r = _reel(30.0, 31.3)
    snap_segments([r], WORDS, **CFG)
    assert abs(r.end - 31.9) < 1e-6
    assert r.start == 30.0                       # начало уже на границе фразы — не двинулось


def test_start_midword_snaps_to_word_boundary():
    # start=30.6 в середине «слово2» → к началу фразы 30.0 (после паузы)
    r = _reel(30.6, 33.4)
    snap_segments([r], WORDS, **CFG)
    assert r.start == 30.0
    assert r.start != 30.6


def test_start_pulled_to_phrase_beginning_within_window():
    # start=33.7 в середине «ещё» → к началу мысли 33.0 в пределах окна ±1.5с
    r = _reel(33.7, 36.4)
    snap_segments([r], WORDS, **CFG)
    assert r.start == 33.0


def test_end_extends_to_end_of_continuous_utterance():
    # Плотная речь без пауз/пунктуации: мысль завершается лишь в конце блока (последнее слово).
    dense = [_w(40.0 + 0.4 * i, 40.0 + 0.4 * i + 0.3, "wд") for i in range(12)]
    r = _reel(40.0, 40.55)                        # предложен конец в середине блока
    snap_segments([r], dense, **CFG)
    # тянем до конца непрерывной мысли: последнее слово t1=44.7 + хвост 0.3 = 45.0
    assert abs(r.end - 45.0) < 1e-6


def test_tail_trimmed_to_not_exceed_max_duration():
    # max_duration мал: завершение 31.6 в пределах, но 31.6+0.3 вышло бы за лимит → хвост подрезан
    r = _reel(30.0, 31.3)
    snap_segments([r], WORDS, tail_sec=0.3, window_sec=1.5, max_duration=1.7,
                  min_pause_for_phrase_end=0.6, max_micro_pause=0.4, hanging_words=HANGING)
    assert r.end == 31.7                          # ровно start+max_duration (хвост 0.3→0.1)
    assert r.end - r.start <= 1.7 + 1e-9


def test_no_boundary_in_range_leaves_segment_untouched():
    # предложенные границы далеко от любых слов (в «тишине» вне окна) → не трогаем
    r = _reel(50.0, 52.0)
    snap_segments([r], WORDS, **CFG)
    assert (r.start, r.end) == (50.0, 52.0)


def test_empty_transcript_leaves_segment_untouched():
    r = _reel(30.0, 31.3)
    snap_segments([r], [], **CFG)
    assert (r.start, r.end) == (30.0, 31.3)


def test_multiple_reels_each_snapped():
    r1 = _reel(30.0, 31.3)       # end → 31.9 (завершение 31.6 + хвост)
    r2 = _reel(33.0, 35.0)       # end=35.0; завершение 34.0 (пауза 2.0с) в окне → 34.3
    snap_segments([r1, r2], WORDS, **CFG)
    assert abs(r1.end - 31.9) < 1e-6
    assert abs(r2.end - 34.3) < 1e-6


# ================================================== завершение мысли: пунктуация / союзы / откат

# Транскрипт с пунктуацией и висячими словами: мысль тянется до конца предложения.
#  «клип начинается тут потому что» (висячий конец на "что") → продолжить до «мысль.»
THOUGHT_WORDS = [
    _w(10.0, 10.4, "клип"),
    _w(10.5, 10.9, "начинается"),
    _w(11.0, 11.3, "тут"),
    _w(11.4, 11.8, "потому"),     # висячее
    _w(11.9, 12.3, "что"),        # висячее — пауза 0.9с после, но конец на союзе → НЕ конец
    _w(13.2, 13.6, "главная"),
    _w(13.7, 14.4, "мысль."),     # пунктуация → конец предложения = завершение 14.4
    _w(16.0, 16.5, "дальше"),     # новая фраза
]
TCFG = CFG


def test_end_extends_past_hanging_conjunction_to_sentence_end():
    # Предложенный конец 12.3 приходится на «что» (висячее) с паузой после → НЕ обрывать там,
    # тянуть до конца предложения «мысль.» (14.4) + хвост 0.3 = 14.7.
    r = _reel(10.0, 12.3)
    snap_segments([r], THOUGHT_WORDS, **TCFG)
    assert abs(r.end - 14.7) < 1e-6


def test_end_uses_sentence_punctuation_as_completion():
    # Даже с запасом времени тянем ровно до конца предложения (пунктуация), не дальше.
    r = _reel(10.0, 13.5)
    snap_segments([r], THOUGHT_WORDS, **TCFG)
    assert abs(r.end - 14.7) < 1e-6              # «мысль.» 14.4 + 0.3, не до «дальше»


def test_micro_pause_not_treated_as_thought_end():
    # Микропаузы (0.1с между словами) внутри фразы — не конец; тянем до реального завершения.
    micro = [
        _w(20.0, 20.4, "раз"),
        _w(20.5, 20.9, "два"),       # пауза 0.1 (микро) — не конец
        _w(21.0, 21.4, "три"),       # пауза 0.1 — не конец
        _w(21.5, 22.2, "финиш."),    # пунктуация → конец 22.2
    ]
    r = _reel(20.0, 20.6)            # предложен конец на «два» (микропауза рядом)
    snap_segments([r], micro, **CFG)
    assert abs(r.end - 22.5) < 1e-6  # не 20.9, а «финиш.» 22.2 + 0.3


def test_thought_too_long_rolls_back_to_last_complete_phrase():
    # Мысль не завершается до max_duration → откат к последней целой фразе в пределах лимита.
    words = [
        _w(0.0, 0.5, "первая"),
        _w(0.6, 1.2, "фраза."),      # завершение 1.2 (в пределах лимита)
        _w(1.5, 2.0, "потом"),
        _w(2.1, 2.6, "длинная"),
        _w(2.7, 3.2, "мысль"),       # без пунктуации/пауз до конца — не влезает
        _w(3.3, 3.8, "которая"),
        _w(3.9, 4.4, "тянется"),
    ]
    r = _reel(0.0, 2.4)              # предложен конец на «длинная»; лимит start+max=0+2.0=2.0
    snap_segments([r], words, tail_sec=0.0, window_sec=1.5, max_duration=2.0,
                  min_pause_for_phrase_end=0.6, max_micro_pause=0.4, hanging_words=HANGING)
    # вперёд завершения в [end-окно, лимит]: единственное завершение <=2.0 — «фраза.» 1.2 → откат
    assert abs(r.end - 1.2) < 1e-6
    assert r.end - r.start <= 2.0 + 1e-9         # целая фраза, влезает в лимит


def test_start_not_on_hanging_word():
    # Начало фразы — висячее слово «и» → сдвинуть вперёд к первому не-висячему слову.
    words = [
        _w(5.0, 5.3, "и"),           # начало фразы, но висячее
        _w(5.4, 5.7, "потом"),       # тоже висячее? нет — "потом" не в списке ("потому" — да)
        _w(5.8, 6.4, "главное"),
        _w(6.5, 7.2, "мысль."),
    ]
    r = _reel(5.0, 7.0)
    snap_segments([r], words, **CFG)
    assert r.start == 5.4            # не с «и» (5.0), а со следующего слова


# ============================================== взаимодействие snap → padding → trim

def test_snap_then_padding_ends_on_completed_thought():
    """snap тянет до конца предложения, padding добавляет воздух — конец на завершённой мысли."""
    r = _reel(10.0, 12.3)                          # обрыв на «что» (висячее)
    snap_segments([r], THOUGHT_WORDS, **TCFG)      # → end 14.7 (мысль. 14.4 + хвост)
    apply_padding([r], THOUGHT_WORDS, tail_pad_sec=0.7, lead_pad_sec=0.3, max_duration=59)
    # padding: последнее слово клипа — «мысль.» (t1=14.4) → end = 14.4 + 0.7 = 15.1
    assert abs(r.end - 15.1) < 1e-6
    assert abs(r.start - 9.7) < 1e-6               # первое слово 10.0 - 0.3


def test_snap_padding_trim_keeps_whole_thought_within_max():
    """Полный конвейер snap→padding→trim: клип завершён по мысли и влезает в max → не режется."""
    from autoreels.cloud.select import flag_durations
    from autoreels.cloud.trim import trim_too_long
    r = _reel(10.0, 12.3)
    snap_segments([r], THOUGHT_WORDS, **TCFG)
    apply_padding([r], THOUGHT_WORDS, tail_pad_sec=0.7, lead_pad_sec=0.3, max_duration=59)
    flag_durations([r], min_duration=15, max_duration=59)
    trim_too_long([r], THOUGHT_WORDS, max_duration=59, pause_sec=0.35, policy="trim")
    assert "too_long" not in r.flags               # в пределах пресета — не режется
    assert abs(r.end - 15.1) < 1e-6                # конец мысли сохранён


def test_snap_keeps_end_within_max_so_trim_is_noop():
    """snap никогда не выводит end за max_duration → trim (too_long) не срабатывает."""
    from autoreels.cloud.select import flag_durations
    r = _reel(10.0, 12.3)
    snap_segments([r], THOUGHT_WORDS, tail_sec=0.3, window_sec=1.5, max_duration=6.0,
                  min_pause_for_phrase_end=0.6, max_micro_pause=0.4, hanging_words=HANGING)
    assert r.end - r.start <= 6.0 + 1e-9
    flag_durations([r], min_duration=15, max_duration=6)
    assert "too_long" not in r.flags


# ============================== реальные примеры из диагностики (порог 1.5с + запятая)

# Продакшн-порог 1.5с (из config/r0.yaml после фикса).
RCFG = dict(tail_sec=0.3, window_sec=1.5, max_duration=59,
            min_pause_for_phrase_end=1.5, max_micro_pause=0.4, hanging_words=HANGING)


def _snap_end_time(words, end, start=0.0, **over):
    from autoreels.cloud.snap import _snap_end
    cfg = {**RCFG, **over}
    return _snap_end(end, start, words, tail_sec=cfg["tail_sec"], window_sec=cfg["window_sec"],
                     max_duration=cfg["max_duration"], min_pause=cfg["min_pause_for_phrase_end"],
                     max_micro_pause=cfg["max_micro_pause"], hanging_words=cfg["hanging_words"])


@pytest.mark.parametrize("gap", [0.7, 1.0, 1.12])
def test_short_thinking_pause_is_not_thought_end(gap):
    """Диагностика: паузы 0.7/1.0/1.12с — thinking-паузы, НЕ конец мысли (тянем дальше)."""
    from autoreels.cloud.snap import _phrase_end_times
    words = [
        _w(0.0, 1.0, "делаем"),                     # gap параметризован
        _w(1.0 + gap, 2.0 + gap, "самая"),          # продолжение (строчное)
        _w(2.1 + gap, 3.5 + gap, "мысль."),         # реальный конец (пунктуация)
    ]
    ends = _phrase_end_times(words, min_pause=1.5, max_micro_pause=0.4, hanging_words=HANGING)
    assert 1.0 not in ends                           # «делаем» (пауза < 1.5) — не конец
    assert (2.0 + gap) not in ends                   # «самая» — не конец
    assert (3.5 + gap) in ends                       # «мысль.» — конец (пунктуация)


@pytest.mark.parametrize("gap", [2.06, 3.48, 7.6])
def test_long_pause_is_thought_end(gap):
    """Диагностика: паузы 2.06/3.48/7.6с — реальные разрывы, конец мысли (режем)."""
    from autoreels.cloud.snap import _phrase_end_times
    words = [
        _w(0.0, 1.0, "собой"),
        _w(1.0 + gap, 2.0 + gap, "а"),               # после длинной паузы
    ]
    ends = _phrase_end_times(words, min_pause=1.5, max_micro_pause=0.4, hanging_words=HANGING)
    assert 1.0 in ends                               # «собой» (пауза > 1.5) — конец


@pytest.mark.parametrize("gap", [0.74, 1.12, 3.0])
def test_comma_word_never_thought_end(gap):
    """Слово с запятой → НЕ конец мысли при ЛЮБОЙ паузе (запятая = середина фразы)."""
    from autoreels.cloud.snap import _phrase_end_times
    words = [
        _w(0.0, 1.0, "осознавать,"),                 # запятая на конце
        _w(1.0 + gap, 2.0 + gap, "понимать."),
    ]
    ends = _phrase_end_times(words, min_pause=1.5, max_micro_pause=0.4, hanging_words=HANGING)
    assert 1.0 not in ends                           # «осознавать,» — не конец даже при 3с паузе
    assert (2.0 + gap) in ends                       # «понимать.» — конец


def test_start_not_after_comma():
    """Начало клипа не встаёт на продолжение после запятой (пауза после запятой ≠ начало фразы)."""
    from autoreels.cloud.snap import _phrase_start_indices
    words = [
        _w(0.0, 0.5, "сказал,"),                     # запятая
        _w(3.0, 3.5, "что"),                         # пауза 2.5с, но это продолжение
        _w(3.6, 4.5, "важно."),
        _w(6.0, 6.5, "Новая"),                       # после «важно.» — реальное начало
    ]
    starts = _phrase_start_indices(words, min_pause=1.5)
    assert 1 not in starts                           # «что» — не начало (после запятой)
    assert 3 in starts                               # «Новая» — начало (после «важно.»)


# ================================================================== apply_padding

# Транскрипт для тестов паддинга: фраза 10.0–12.5, пауза, фраза 20.0–22.0
PAD_WORDS = [
    _w(10.0, 10.6, "первое"),
    _w(10.7, 11.2, "второе"),
    _w(11.3, 12.5, "последнее"),   # последнее слово фразы
    _w(20.0, 20.8, "новая"),
    _w(21.0, 22.0, "фраза"),
]
PAD_CFG = dict(tail_pad_sec=0.7, lead_pad_sec=0.3, max_duration=59)


def test_tail_pad_extends_end_after_last_word():
    """end = last_word.t1 + tail_pad_sec (0.7с воздуха после последнего слова)."""
    r = _reel(10.0, 12.5)
    apply_padding([r], PAD_WORDS, **PAD_CFG)
    assert abs(r.end - (12.5 + 0.7)) < 1e-6   # 12.5 + 0.7 = 13.2


def test_lead_pad_extends_start_before_first_word():
    """start = first_word.t0 - lead_pad_sec (0.3с захода до первого слова)."""
    r = _reel(10.0, 12.5)
    apply_padding([r], PAD_WORDS, **PAD_CFG)
    assert abs(r.start - (10.0 - 0.3)) < 1e-6   # 10.0 - 0.3 = 9.7


def test_tail_pad_capped_at_max_duration():
    """tail_pad не выводит клип за max_duration."""
    r = _reel(10.0, 12.5)
    apply_padding([r], PAD_WORDS, tail_pad_sec=0.7, lead_pad_sec=0.3, max_duration=2.5)
    # new_start = 9.7, max_end = 9.7 + 2.5 = 12.2; last_word.t1 + 0.7 = 13.2 > 12.2 → cap
    assert r.end - r.start <= 2.5 + 1e-9
    assert abs(r.end - (r.start + 2.5)) < 1e-6


def test_lead_pad_capped_at_zero():
    """lead_pad не уходит раньше начала видео (не отрицательный start)."""
    r = _reel(0.1, 12.5)          # первое слово в 10.0, но клип начинается в 0.1
    apply_padding([r], PAD_WORDS, **PAD_CFG)
    assert r.start >= 0.0


def test_tail_pad_capped_at_video_duration():
    """tail_pad не выводит за конец исходного видео."""
    r = _reel(10.0, 12.5)
    apply_padding([r], PAD_WORDS, tail_pad_sec=0.7, lead_pad_sec=0.3,
                  max_duration=59, video_duration=12.8)
    assert r.end <= 12.8 + 1e-9


def test_no_words_in_clip_leaves_unchanged():
    """Нет слов в диапазоне клипа — границы не меняются."""
    r = _reel(50.0, 55.0)   # вне PAD_WORDS (10-22с)
    apply_padding([r], PAD_WORDS, **PAD_CFG)
    assert (r.start, r.end) == (50.0, 55.0)


def test_subtitles_not_affected_by_padding():
    """Субтитры на reel не меняются при паддинге — pad-зона это тишина."""
    r = _reel(10.0, 12.5)
    r.subtitles = [{"word": "последнее", "t0": 11.3, "t1": 12.5}]
    apply_padding([r], PAD_WORDS, **PAD_CFG)
    # границы клипа расширились, субтитры остались теми же объектами
    assert r.subtitles == [{"word": "последнее", "t0": 11.3, "t1": 12.5}]


def test_padding_drops_glued_next_sentence_start():
    """«…конструкция. И вот»: слова после конца предложения — начало следующей фразы; хвост
    их не втягивает и НЕ добавляет tail в их речь (clamp по соседнему слову)."""
    words = [
        _w(0.0, 1.0, "статичная"),
        _w(1.0, 2.0, "конструкция."),                # конец предложения, t1=2.0
        _w(2.0, 2.1, "И"),                           # приклеено (gap 0.0), союз → начало след. фразы
        _w(2.1, 2.3, "вот"),                         # тоже приклеено, висячее
    ]
    r = _reel(0.0, 2.4)                              # клип включает «И», «вот» (t0 < 2.4)
    apply_padding([r], words, tail_pad_sec=0.7, lead_pad_sec=0.3, max_duration=59,
                  hanging_words=HANGING)
    assert abs(r.end - 2.0) < 1e-6                   # end ровно по «конструкция.» — «И» впритык, tail=0


def test_padding_tail_clamped_before_next_word():
    """Хвост (0.7с) НЕ заезжает в начало следующего слова — обрезается до next.t0 − _PAD_EPS."""
    words = [
        _w(0.0, 1.0, "первое"),
        _w(1.5, 2.0, "второе"),                      # последнее слово клипа
        _w(2.2, 2.6, "третье"),                      # следующее слово: gap 0.2 < tail_pad 0.7
    ]
    r = _reel(0.0, 2.1)                              # клип = первое, второе (t0 < 2.1)
    apply_padding([r], words, tail_pad_sec=0.7, lead_pad_sec=0.3, max_duration=59,
                  hanging_words=HANGING)
    assert abs(r.end - (2.2 - 0.05)) < 1e-6          # клампнут перед «третье», не 2.0+0.7=2.7


def test_padding_tail_full_at_end_of_speech():
    """Нет следующего слова (конец речи) — tail_pad как есть (0.7с воздуха)."""
    words = [_w(0.0, 1.0, "первое"), _w(1.5, 2.0, "конец.")]
    r = _reel(0.0, 2.1)
    apply_padding([r], words, tail_pad_sec=0.7, lead_pad_sec=0.3, max_duration=59,
                  hanging_words=HANGING)
    assert abs(r.end - (2.0 + 0.7)) < 1e-6           # полный хвост — некуда заезжать


def test_padding_lead_clamped_after_prev_word():
    """Заход (0.3с) НЕ заезжает в конец предыдущего слова — ограничен prev.t1 + _PAD_EPS."""
    words = [_w(0.0, 1.0, "раньше"), _w(1.2, 2.0, "клип."), ]  # gap 0.2 < lead_pad 0.3
    r = _reel(1.2, 2.0)
    apply_padding([r], words, tail_pad_sec=0.7, lead_pad_sec=0.3, max_duration=59,
                  hanging_words=HANGING)
    assert abs(r.start - (1.0 + 0.05)) < 1e-6        # клампнут после «раньше», не 1.2−0.3=0.9


def test_padding_no_hanging_words_backward_compatible():
    """Без hanging_words (старые вызовы) — спилловер-обрезка не срабатывает по союзам."""
    r = _reel(10.0, 12.5)
    apply_padding([r], PAD_WORDS, **PAD_CFG)          # без hanging_words
    assert abs(r.end - (12.5 + 0.7)) < 1e-6


# --------- РЕАЛЬНЫЕ примеры из диагностики длинных роликов (обрывы фраз вернулись) ---------

def test_padding_real_neрealizovanny_eto():
    """«…нереализованный. Это всего…» (реальные тайминги): хвост 0.7с НЕ въезжает в «Это»
    (начало след. фразы, gap 0.52) — был обрыв +0.70, стал чистый конец на «нереализованный.»."""
    words = [_w(178.09, 178.57, "какой-то"), _w(178.57, 179.69, "нереализованный."),
             _w(180.21, 180.35, "Это"), _w(180.35, 180.69, "всего")]
    r = _reel(170.0, 179.99)                          # snap-конец = нереализованный.t1 + tail 0.3
    apply_padding([r], words, tail_pad_sec=0.7, lead_pad_sec=0.3, max_duration=59,
                  hanging_words=HANGING)
    assert abs(r.end - (180.21 - 0.05)) < 1e-6        # клампнут перед «Это», не 179.69+0.7=180.39
    assert r.end > 179.69                             # «нереализованный.» включён + воздух


def test_padding_real_prochuvstvovat_pogovori():
    """«…прочувствовать. Поговори…» (реальные тайминги, gap 0.16): хвост 0.7с НЕ въезжает в
    «Поговори» — был обрыв (речь след. фразы), стал чистый конец на «прочувствовать.»."""
    words = [_w(85.28, 85.44, "были"), _w(85.44, 86.68, "прочувствовать."),
             _w(86.84, 87.18, "Поговори"), _w(87.18, 87.34, "с")]
    r = _reel(80.0, 86.98)                            # snap-конец = прочувствовать.t1 + tail 0.3
    apply_padding([r], words, tail_pad_sec=0.7, lead_pad_sec=0.3, max_duration=59,
                  hanging_words=HANGING)
    assert abs(r.end - (86.84 - 0.05)) < 1e-6         # клампнут перед «Поговори», не 86.68+0.7
    assert r.end >= 86.68


def test_snap_fallback_lands_on_non_hanging_not_hanging():
    """Нет пунктуации и пауз ≥1.5с (сплошная речь): фолбэк садится на не-висячее слово,
    НЕ на «это»/«есть». (реальная картина «…нереализованный. Это» без пунктуации Whisper)."""
    words = [_w(0.0, 0.4, "поэтому"), _w(0.4, 0.9, "важно"),
             _w(1.5, 2.0, "это")]                     # is_last, висячее, gap 0.6 после «важно»
    r = _reel(0.0, 1.8)
    snap_segments([r], words, tail_sec=0.3, window_sec=1.5, max_duration=59,
                  min_pause_for_phrase_end=1.5, max_micro_pause=0.4, hanging_words=HANGING)
    assert abs(r.end - (0.9 + 0.3)) < 1e-6            # конец на «важно»(0.9)+tail, не на «это»


def test_padding_drops_trailing_comma_word():
    """Клип не заканчивается на слове-с-запятой: хвостовое «…никогда,» срезается (реальный
    случай r04 из честного пере-прогона), end уходит на предыдущее содержательное слово."""
    words = [_w(0.0, 0.5, "было"), _w(0.5, 1.0, "интересно"),
             _w(1.0, 1.5, "никогда,"),                # запятая на конце — мысль продолжается
             _w(1.6, 2.1, "думал")]
    r = _reel(0.0, 1.6)                               # клип включает «никогда,» (t0 < 1.6)
    apply_padding([r], words, tail_pad_sec=0.7, lead_pad_sec=0.3, max_duration=59,
                  hanging_words=HANGING)
    assert r.end < 1.5                                # не заканчивается на «никогда,» (t1=1.5)
    assert r.end >= 1.0                               # осталось на «интересно» (t1=1.0)


def test_padding_trims_next_sentence_spillover_to_period():
    """«…психосоматика. И вот мы» — snap-хвост втянул начало след. фразы; padding обрезает до «.»
    (триммер последнего слова стопался на «мы» — обычное слово; нужен трим короткого спилловера)."""
    words = [_w(0.0, 1.0, "нашем"), _w(1.0, 2.0, "психосоматика."),
             _w(1.98, 2.06, "И"), _w(2.06, 2.34, "вот"), _w(2.34, 2.5, "мы"), _w(2.5, 3.0, "уже")]
    r = _reel(0.0, 2.3)                              # клип захватил «И вот» (t0 < 2.3)
    apply_padding([r], words, tail_pad_sec=0.7, lead_pad_sec=0.3, max_duration=59,
                  hanging_words=HANGING)
    assert abs(r.end - 2.0) < 1e-6                   # конец на «психосоматика.» (2.0), не на «мы»


def test_padding_keeps_sentence_end_after_prior_sentence_end():
    """«…что? Умрёте. И мы» — «Умрёте.» само завершает предложение; НЕ срезаем его как спилловер
    после «что?» (guard в триммере: слово-конец-предложения — чистый конец)."""
    words = [_w(0.0, 1.0, "что?"), _w(1.0, 2.0, "умрёте."),
             _w(2.05, 2.13, "И"), _w(2.13, 2.3, "мы")]
    r = _reel(0.0, 2.3)
    apply_padding([r], words, tail_pad_sec=0.7, lead_pad_sec=0.3, max_duration=59,
                  hanging_words=HANGING)
    assert abs(r.end - 2.0) < 1e-6                   # конец на «умрёте.», не откат к «что?»


def test_snap_fallback_lands_on_non_comma_not_after_comma():
    """Фолбэк не садится ПОСЛЕ запятой, если есть не-запятая альтернатива."""
    words = [_w(0.0, 0.4, "поэтому"), _w(0.4, 0.9, "важно"),
             _w(1.5, 2.0, "смотри,")]                 # is_last, запятая, gap 0.6 после «важно»
    r = _reel(0.0, 1.8)
    snap_segments([r], words, tail_sec=0.3, window_sec=1.5, max_duration=59,
                  min_pause_for_phrase_end=1.5, max_micro_pause=0.4, hanging_words=HANGING)
    assert abs(r.end - (0.9 + 0.3)) < 1e-6            # конец на «важно», не на «смотри,»
