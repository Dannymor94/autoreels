"""R4: подтяжка границ сегментов к ЗАВЕРШЕНИЮ МЫСЛИ (детерминированный слой).

LLM предлагает start/end приблизительно — часто в середине слова ИЛИ на полуфразе (клип
обрывается «на союзе», хотя до max_duration ещё много запаса). Здесь КОД тянет границы к
естественным границам мысли (инвариант проекта: LLM ранжирует/предлагает, финальные границы
ставит код):

- `end` → тянется ВПЕРЁД до завершения мысли, пока (end-start) < max_duration:
  завершение = конец предложения (пунктуация Whisper .!?…) ИЛИ длинная пауза
  (> `min_pause_for_phrase_end`) ИЛИ конец речи. Микропаузы (< `max_micro_pause`) и
  висячие слова (союз/предлог/вводное из `hanging_words`) концом НЕ считаются;
- мысль не влезла в max_duration → откат к ПОСЛЕДНЕЙ целой фразе в пределах лимита
  (лучше короче, но целое, чем длиннее и оборванное);
- `start` → к началу фразы рядом (после паузы), НЕ на висячем слове (сдвиг вперёд);
- нет подходящей границы в окне ±`window_sec` (для start) → границу не трогаем.

PySceneDetect намеренно НЕ используется: статичная камера, один непрерывный план, склеек
нет — детектить нечего. R4 здесь = snap к завершению мысли.
"""
from __future__ import annotations

from autoreels.core.models import Reel, Word

# Символы конца предложения (Whisper на русском роняет часть пунктуации, но не всю — где
# есть, доверяем ей как самому сильному сигналу завершения мысли).
_SENTENCE_END = ".!?…"


def _clean(word: str) -> str:
    """Слово без обрамляющей пунктуации, в нижнем регистре — для сверки с hanging_words."""
    return word.strip().strip(_SENTENCE_END + ",;:\"'»«()").lower()


def _is_sentence_end(word: str) -> bool:
    """Слово завершает предложение (пунктуация Whisper: .!?… или многоточие)."""
    s = word.strip()
    return bool(s) and (s[-1] in _SENTENCE_END or s.endswith("..."))


def _is_hanging(word: str, hanging_words) -> bool:
    """Висячее слово (союз/предлог/вводное) — на нём мысль не завершают."""
    return _clean(word) in set(hanging_words)


def _nearest_in_window(target: float, candidates: list[float], window_sec: float) -> float | None:
    """Ближайший кандидат к target в пределах ±window_sec, иначе None."""
    in_range = [c for c in candidates if abs(c - target) <= window_sec]
    return min(in_range, key=lambda c: abs(c - target)) if in_range else None


def _pause_word_ends(words: list[Word], pause_sec: float) -> list[float]:
    """Концы слов, за которыми пауза > pause_sec (или конец речи) — простые границы фраз.

    Примитив по одной паузе (без пунктуации/висячих) — переиспользует trim.py для отреза
    слишком длинного клипа к ближайшей паузе. Полный «конец мысли» — в _phrase_end_times."""
    ends: list[float] = []
    for i, w in enumerate(words):
        if i == len(words) - 1 or (words[i + 1].t0 - w.t1) > pause_sec:
            ends.append(w.t1)
    return ends


def _phrase_end_times(words: list[Word], *, min_pause: float, max_micro_pause: float,
                      hanging_words) -> list[float]:
    """Времена концов слов, на которых ЗАВЕРШАЕТСЯ мысль.

    Конец предложения (пунктуация) — всегда (пунктуация сильнее висячести). Иначе — длинная
    пауза (> min_pause) или конец речи, но только если слово не висячее. Микропаузы
    (<= max_micro_pause) концом не считаются никогда.
    """
    ends: list[float] = []
    n = len(words)
    for i, w in enumerate(words):
        if _is_sentence_end(w.word):
            ends.append(w.t1)
            continue
        is_last = i == n - 1
        gap = None if is_last else (words[i + 1].t0 - w.t1)
        if gap is not None and gap <= max_micro_pause:
            continue  # микропауза внутри фразы — не конец
        long_pause_or_end = is_last or (gap is not None and gap > min_pause)
        if long_pause_or_end and not _is_hanging(w.word, hanging_words):
            ends.append(w.t1)
    return ends


def _phrase_start_indices(words: list[Word], *, min_pause: float) -> list[int]:
    """Индексы слов — начал фраз: первое слово или слово после длинной паузы (> min_pause)."""
    starts: list[int] = []
    for i, w in enumerate(words):
        if i == 0 or (w.t0 - words[i - 1].t1) > min_pause:
            starts.append(i)
    return starts


def _snap_end(end: float, start: float, words: list[Word], *, tail_sec: float, window_sec: float,
              max_duration: float, min_pause: float, max_micro_pause: float,
              hanging_words) -> float | None:
    """Новый end: тянуть вперёд до завершения мысли в пределах max_duration; не влезло —
    откат к последней целой фразе; совсем нет завершений рядом → к концу слова (не полуслово)."""
    limit = start + max_duration
    ends = _phrase_end_times(words, min_pause=min_pause, max_micro_pause=max_micro_pause,
                             hanging_words=hanging_words)

    # Вперёд-first: ближайшее завершение мысли >= (end - окно), влезающее в лимит.
    # Окно назад — чтобы подхватить завершение, которое чуть раньше предложенного конца
    # (LLM промахнулся вперёд); вперёд тянем без окна — до конца мысли, пока есть запас.
    forward = [t for t in ends if t >= end - window_sec and start < t <= limit]
    if forward:
        chosen = min(forward)
    else:
        # Мысль не завершается до max_duration → откат к последней целой фразе в лимите.
        within = [t for t in ends if start < t <= limit]
        if within:
            chosen = max(within)
        else:
            # Нет завершений мысли рядом — хотя бы к ближайшему концу слова (не полуслово).
            chosen = _nearest_in_window(end, [w.t1 for w in words if start < w.t1 <= limit],
                                        window_sec)
            if chosen is None:
                return None
    new_end = min(chosen + tail_sec, limit)
    return new_end if new_end > start else None


def _snap_start(start: float, end: float, words: list[Word], *, window_sec: float,
                min_pause: float, hanging_words) -> float | None:
    """Новый start: к началу фразы рядом (после паузы), НЕ на висячем слове (сдвиг вперёд)."""
    start_idx = _phrase_start_indices(words, min_pause=min_pause)
    cands = [words[i].t0 for i in start_idx]
    target = _nearest_in_window(start, cands, window_sec)
    if target is None:
        target = _nearest_in_window(start, [w.t0 for w in words], window_sec)
    if target is None:
        return None
    # Не начинать с висячего слова: сдвинуть вперёд, пока слово-начало не «висячее».
    idx = next((i for i, w in enumerate(words) if abs(w.t0 - target) < 1e-6), None)
    if idx is not None:
        while idx < len(words) and words[idx].t0 < end and _is_hanging(words[idx].word, hanging_words):
            idx += 1
        if idx < len(words):
            target = words[idx].t0
    return target if target < end else None


def snap_segments(reels: list[Reel], words: list[Word], *, tail_sec: float, window_sec: float,
                  max_duration: float, min_pause_for_phrase_end: float, max_micro_pause: float,
                  hanging_words) -> None:
    """Подтянуть start/end каждого reel к завершению мысли (мутирует на месте).

    Пустой `words` → границы не трогаем. Порядок в пайплайне: snap → padding → trim.
    """
    if not words:
        return
    for r in reels:
        new_start = _snap_start(r.start, r.end, words, window_sec=window_sec,
                                min_pause=min_pause_for_phrase_end, hanging_words=hanging_words)
        if new_start is not None:
            r.start = new_start
        new_end = _snap_end(r.end, r.start, words, tail_sec=tail_sec, window_sec=window_sec,
                            max_duration=max_duration, min_pause=min_pause_for_phrase_end,
                            max_micro_pause=max_micro_pause, hanging_words=hanging_words)
        if new_end is not None:
            r.end = new_end


def apply_padding(
    reels: list[Reel],
    words: list[Word],
    *,
    tail_pad_sec: float,
    lead_pad_sec: float,
    max_duration: float,
    video_duration: float | None = None,
) -> None:
    """Добавить «воздух» до первого и после последнего слова клипа (мутирует на месте).

    Запускается ПОСЛЕ snap_segments. Находит первое/последнее слово в диапазоне [start, end],
    раздвигает границы: start -= lead_pad_sec, end += tail_pad_sec.
    Субтитры не затрагиваются — область паддинга это тишина/пауза без слов.

    Ограничения:
    - start >= 0
    - end - start <= max_duration
    - end <= video_duration (если задана)
    """
    for r in reels:
        clip_words = [w for w in words if w.t0 >= r.start and w.t0 < r.end]
        if not clip_words:
            continue

        new_start = max(0.0, clip_words[0].t0 - lead_pad_sec)
        new_end = clip_words[-1].t1 + tail_pad_sec

        new_end = min(new_end, new_start + max_duration)
        if video_duration is not None:
            new_end = min(new_end, video_duration)

        r.start = new_start
        r.end = new_end
