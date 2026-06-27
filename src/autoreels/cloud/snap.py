"""R4: подтяжка границ сегментов к границам слов/паузам (детерминированный слой).

LLM предлагает start/end приблизительно — нередко в СЕРЕДИНЕ слова, отчего ffmpeg режет
клип на полуслове. Здесь КОД подтягивает границы к word-таймкостам транскрипта (инвариант
проекта: LLM ранжирует/предлагает, финальные границы ставит детерминированный код):

- `end` → к ближайшей ГРАНИЦЕ СЛОВА рядом с предложенным концом, предпочитая ПАУЗУ
  (зазор между словами > pause_sec — естественный конец фразы); + хвост `tail_sec`,
  чтобы фраза договорилась, а не обрывалась впритык;
- `start` → к началу слова рядом, предпочитая начало после паузы (клип не стартует с обрубка);
- нет подходящей границы в окне ±`window_sec` → границу не трогаем (не ломаем);
- хвост не выводит клип за `max_duration` пресета (если упирается — хвост подрезается;
  уже-длинный сегмент по самой границе слова не режем — это забота too_long-флага, не snap).

PySceneDetect намеренно НЕ используется: статичная камера, один непрерывный план, склеек
нет — детектить нечего, лишнюю зависимость не тащим. R4 здесь = snap к словам/паузам.
"""
from __future__ import annotations

from autoreels.core.models import Reel, Word


def _pause_word_ends(words: list[Word], pause_sec: float) -> list[float]:
    """Концы слов, за которыми идёт пауза > pause_sec (или конец речи) — границы фраз."""
    ends: list[float] = []
    for i, w in enumerate(words):
        is_last = i == len(words) - 1
        if is_last or (words[i + 1].t0 - w.t1) > pause_sec:
            ends.append(w.t1)
    return ends


def _pause_word_starts(words: list[Word], pause_sec: float) -> list[float]:
    """Начала слов, перед которыми пауза > pause_sec (или начало речи) — начала фраз."""
    starts: list[float] = []
    for i, w in enumerate(words):
        is_first = i == 0
        if is_first or (w.t0 - words[i - 1].t1) > pause_sec:
            starts.append(w.t0)
    return starts


def _nearest_in_window(target: float, candidates: list[float], window_sec: float) -> float | None:
    """Ближайший кандидат к target в пределах ±window_sec, иначе None."""
    in_range = [c for c in candidates if abs(c - target) <= window_sec]
    return min(in_range, key=lambda c: abs(c - target)) if in_range else None


def _snap_end(end: float, start: float, words: list[Word], *,
              tail_sec: float, window_sec: float, pause_sec: float, max_duration: float) -> float | None:
    """Новый end (граница слова/паузы + хвост, в пределах max) или None если границы рядом нет."""
    # 1) предпочитаем паузу (естественный конец фразы); 2) иначе ближайший конец слова.
    target = _nearest_in_window(end, _pause_word_ends(words, pause_sec), window_sec)
    if target is None:
        target = _nearest_in_window(end, [w.t1 for w in words], window_sec)
    if target is None:
        return None
    # Хвост, но не за max_duration. Никогда не режем НИЖЕ границы слова `target` (иначе
    # снова обрыв на полуслове / порча уже-длинного сегмента — это дело too_long-флага).
    desired = target + tail_sec
    new_end = min(desired, max(target, start + max_duration))
    return new_end if new_end > start else None


def _snap_start(start: float, end: float, words: list[Word], *,
                window_sec: float, pause_sec: float) -> float | None:
    """Новый start (начало слова/после паузы) или None если границы рядом нет."""
    target = _nearest_in_window(start, _pause_word_starts(words, pause_sec), window_sec)
    if target is None:
        target = _nearest_in_window(start, [w.t0 for w in words], window_sec)
    if target is None:
        return None
    return target if target < end else None


def snap_segments(reels: list[Reel], words: list[Word], *,
                  tail_sec: float, window_sec: float, pause_sec: float, max_duration: float) -> None:
    """Подтянуть start/end каждого reel к словам/паузам транскрипта (мутирует на месте).

    Пустой `words` или отсутствие границы рядом → соответствующая граница не меняется.
    """
    if not words:
        return
    for r in reels:
        new_start = _snap_start(r.start, r.end, words, window_sec=window_sec, pause_sec=pause_sec)
        if new_start is not None:
            r.start = new_start
        new_end = _snap_end(r.end, r.start, words, tail_sec=tail_sec, window_sec=window_sec,
                            pause_sec=pause_sec, max_duration=max_duration)
        if new_end is not None:
            r.end = new_end
