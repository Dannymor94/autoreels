"""too_long trim: обрезка или отбраковка длинных сегментов (детерминированный слой).

Политика задаётся конфигом r0.yaml `too_long_policy`:
- trim  (дефолт): обрезать хвост по ближайшей паузе перед лимитом; жёсткий рез если
  подходящей паузы нет. Флаг too_long снимается. Начало сохраняется.
- drop: убрать сегмент из списка. Там, где LLM ошибся с длиной — не показывать.
- keep: оставить как есть (прежнее поведение). Флаг too_long остаётся.

Переиспользует snap-логику: поиск конца фразы (пауза > pause_sec) из snap.py.
"""
from __future__ import annotations

from autoreels.cloud.snap import _pause_word_ends
from autoreels.core.models import Reel, Word

_FLAG = "too_long"


def _trim_end(start: float, max_duration: float, words: list[Word], pause_sec: float) -> float:
    """Новый end: конец слова перед паузой ≤ start+max_duration; жёсткий рез если нет паузы."""
    limit = start + max_duration
    # Концы слов, за которыми пауза — кандидаты на «конец фразы»
    phrase_ends = [t for t in _pause_word_ends(words, pause_sec) if t <= limit]
    if phrase_ends:
        return max(phrase_ends)          # самый поздний конец фразы до лимита
    # Нет паузы — ближайший конец слова до лимита
    word_ends = [w.t1 for w in words if w.t1 <= limit]
    if word_ends:
        return max(word_ends)
    # Нет слов до лимита — жёсткий рез
    return limit


def trim_too_long(
    reels: list[Reel],
    words: list[Word],
    *,
    max_duration: float,
    pause_sec: float,
    policy: str,
) -> None:
    """Применить политику too_long_policy ко всем рилам с флагом too_long.

    Мутирует reels на месте (drop — удаляет элементы из списка).
    """
    if policy == "keep":
        return

    if policy == "drop":
        reels[:] = [r for r in reels if _FLAG not in r.flags]
        return

    if policy == "trim":
        for r in reels:
            if _FLAG not in r.flags:
                continue
            # Слова внутри временного окна [start, start+max_duration]
            window_words = [w for w in words if w.t0 >= r.start and w.t1 <= r.start + max_duration + 1]
            r.end = _trim_end(r.start, max_duration, window_words, pause_sec)
            r.flags = [f for f in r.flags if f != _FLAG]
        return

    raise ValueError(f"неизвестная политика too_long: {policy!r}; допустимо: trim | drop | keep")
