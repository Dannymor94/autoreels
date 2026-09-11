"""too_long trim: обрезка или отбраковка длинных сегментов (детерминированный слой).

Политика задаётся конфигом r0.yaml `too_long_policy`:
- trim  (дефолт): обрезать НАЧАЛО клипа, сохраняя конец, поставленный punctuation-first snap.
  Иерархия: первое слово после sentence-terminal mark (. ? !) в диапазоне [end-max, end];
  фолбэк — первое слово после паузы > pause_sec; жёсткий рез (end - max_duration) если нет.
  Конец двигается назад ТОЛЬКО когда финальное предложение само > max_duration (нет ни одного
  sentence-terminal mark перед порогом).
  Флаг too_long снимается. start_drift_sec / start_snap_reason фиксируют сдвиг.
- drop: убрать сегмент из списка.
- keep: оставить как есть. Флаг too_long остаётся.
"""
from __future__ import annotations

from autoreels.cloud.snap import _is_sentence_end
from autoreels.core.models import Reel, Word

_FLAG = "too_long"


def _trim_start(
    start: float,
    end: float,
    max_duration: float,
    words: list[Word],
    pause_sec: float,
) -> tuple[float, str]:
    """Новый start: сдвинуть вперёд так, чтобы (end - new_start) ≤ max_duration.

    Иерархия (применяется к словам в [start, end]):
    1. Первое слово w ≥ floor=(end-max_duration), предыдущее слово — sentence-terminal (. ? !).
    2. Первое слово w ≥ floor, перед которым пауза > pause_sec.
    3. Жёсткий рез: floor.

    Returns (new_start, reason): reason in ("sentence", "pause", "hard_cut").
    """
    floor = end - max_duration
    in_window = [w for w in words if w.t0 >= start and w.t0 <= end]

    # 1. sentence boundary at or after floor
    for i, w in enumerate(in_window):
        if w.t0 < floor:
            continue
        if i == 0:
            continue
        prev = in_window[i - 1]
        if _is_sentence_end(prev.word):
            return w.t0, "sentence"

    # 2. pause boundary at or after floor
    for i, w in enumerate(in_window):
        if w.t0 < floor:
            continue
        if i == 0:
            continue
        prev = in_window[i - 1]
        if (w.t0 - prev.t1) > pause_sec:
            return w.t0, "pause"

    # 3. hard cut
    return floor, "hard_cut"


def _last_sentence_end(words: list[Word], limit: float) -> float | None:
    """Последний t1 слова с sentence-terminal mark, не превышающий limit. None если нет."""
    ends = [w.t1 for w in words if _is_sentence_end(w.word) and w.t1 <= limit]
    return max(ends) if ends else None


def trim_too_long(
    reels: list[Reel],
    words: list[Word],
    *,
    max_duration: float,
    pause_sec: float,
    policy: str,
    min_duration: float = 0.0,
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
        to_remove: list[Reel] = []
        for r in reels:
            if _FLAG not in r.flags:
                continue

            orig_start = r.start
            orig_end = r.end
            window = [w for w in words if w.t0 >= orig_start - 0.1 and w.t1 <= orig_end + 0.1]
            floor = orig_end - max_duration   # минимально допустимый start

            # Есть ли хоть одна естественная граница (sentence или пауза) в [floor, end]?
            # Если нет — только жёсткий рез start; предпочтительнее trim end к терминалу.
            has_natural_boundary = False
            for idx, w in enumerate(window):
                if w.t0 < floor or idx == 0:
                    continue
                prev = window[idx - 1]
                if _is_sentence_end(prev.word) or (w.t0 - prev.t1) > pause_sec:
                    has_natural_boundary = True
                    break

            if not has_natural_boundary and orig_end - orig_start > max_duration:
                # Нет sentence boundary, за которой можно начать: trim end к ближайшему терминалу
                new_end = _last_sentence_end(window, orig_start + max_duration)
                if new_end is not None:
                    r.end = new_end
                else:
                    r.end = orig_start + max_duration
                r.end_snap_reason = "max_duration_end_trim"
                r.flags = [f for f in r.flags if f != _FLAG]
                if r.end - r.start < min_duration:
                    to_remove.append(r)
                continue

            # Нормальный путь: trim от начала, конец сохраняется
            new_start, reason = _trim_start(orig_start, orig_end, max_duration, window, pause_sec)
            r.start = new_start
            r.start_drift_sec = round(new_start - orig_start, 3)
            r.start_snap_reason = reason
            r.flags = [f for f in r.flags if f != _FLAG]
            if r.end - r.start < min_duration:
                to_remove.append(r)

        for r in to_remove:
            if r in reels:
                reels.remove(r)
        return

    raise ValueError(f"неизвестная политика too_long: {policy!r}; допустимо: trim | drop | keep")
