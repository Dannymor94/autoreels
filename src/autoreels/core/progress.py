"""Live progress output for long-running chunked operations (R0, Whisper).

TTY: overwrites current line with \\r — keeps terminal clean, looks like a progress bar.
Non-TTY (pipe, CI, log redirect): plain newline-terminated lines — parseable, no escape codes.

Usage:
    chunk_start("R0", total=54, est_sec=900)
    for i, chunk in enumerate(chunks, 1):
        chunk_progress("R0", i, total, extra=f"найдено {found} моментов")
    chunk_progress("R0", total, total, done=True)
"""
from __future__ import annotations

import sys

_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_DONE = "✓"
_LINE_WIDTH = 72   # минимальная ширина строки (заполняется пробелами на TTY)


def is_tty() -> bool:
    """True если stdout — интерактивный терминал."""
    return sys.stdout.isatty()


def spinner(i: int) -> str:
    """Символ спиннера для итерации i."""
    return _SPINNER[i % len(_SPINNER)]


def chunk_progress(
    label: str,
    i: int,
    total: int,
    extra: str = "",
    *,
    done: bool = False,
) -> None:
    """Напечатать строку прогресса для чанка i из total.

    TTY: перезаписывает текущую строку через \\r.
    Non-TTY: новая строка на каждый вызов.
    done=True: финальная строка (✓, на TTY — с newline).
    """
    pct = int(100 * i / total) if total > 0 else 100
    mark = _DONE if done else spinner(i - 1)
    extra_str = f"  {extra}" if extra else ""
    msg = f"  {label}: чанк {i}/{total} ({pct}%) {mark}{extra_str}"

    if is_tty():
        # Дополняем пробелами, чтобы стереть хвост предыдущей строки
        padded = f"\r{msg:<{_LINE_WIDTH}}"
        if done:
            print(padded.rstrip(), flush=True)   # с newline
        else:
            print(padded, end="", flush=True)    # без newline
    else:
        print(msg, flush=True)


def throttle_wait(sec: float, source: str = "Groq") -> None:
    """Сообщить что ждём rate limit от source.

    TTY: на той же строке (через \\r) — не засоряет историю паузами.
    Non-TTY: отдельная строка.
    """
    msg = f"  ждём {source} (rate limit, ~{sec:.0f}с)…"
    if is_tty():
        print(f"\r{msg:<{_LINE_WIDTH}}", end="", flush=True)
    else:
        print(msg, flush=True)


def chunk_start(label: str, total: int, est_sec: float | None = None) -> None:
    """Напечатать банер перед стартом чанкинга.

    Показывает количество чанков и оценку времени (если est_sec >= 30).
    """
    if est_sec is not None and est_sec >= 30:
        est_min = est_sec / 60
        print(f"  {label}: {total} чанков, ~{est_min:.0f} мин", flush=True)
    else:
        print(f"  {label}: {total} чанков", flush=True)
