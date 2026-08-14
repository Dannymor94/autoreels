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

import os
import sys

_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_DONE = "✓"
_LINE_WIDTH = 72   # минимальная ширина строки (заполняется пробелами на TTY)
_CLEAR_EOL = "\033[K"   # ANSI «стереть до конца строки» — вместо добивки пробелами

_BAR_WIDTH = 20         # ячеек в прогресс-баре по умолчанию
_BAR_FILL = "█"
_BAR_EMPTY = "░"


def render_bar(pct: float, width: int = _BAR_WIDTH) -> str:
    """Текстовый прогресс-бар `[█████░░░░░]` по проценту (0..100), клип за границы.

    Визуальная «загрузка» — видно и что идёт, и сколько осталось, одним взглядом.
    Ширина в СИМВОЛАХ (█/░ — по одному символу Python), скобки не считаются в width.
    """
    p = max(0.0, min(100.0, float(pct)))
    filled = int(round(width * p / 100.0))
    filled = max(0, min(width, filled))
    return "[" + _BAR_FILL * filled + _BAR_EMPTY * (width - filled) + "]"


def is_tty() -> bool:
    """True если вывод — интерактивный терминал (обновляем строку через \\r).

    Страховка от неверного автодетекта: AUTOREELS_FORCE_TTY=1 форсит перезапись,
    AUTOREELS_NO_TTY=1 форсит построчный вывод (для пайпа в файл).
    """
    if os.environ.get("AUTOREELS_NO_TTY") == "1":
        return False
    if os.environ.get("AUTOREELS_FORCE_TTY") == "1":
        return True
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
    bar = render_bar(pct)
    msg = f"  {label}: {bar} {pct}% · {i}/{total} {mark}{extra_str}"

    if is_tty():
        # Дополняем пробелами, чтобы стереть хвост предыдущей строки
        padded = f"\r{msg:<{_LINE_WIDTH}}"
        if done:
            print(padded.rstrip(), flush=True)   # с newline
        else:
            print(padded, end="", flush=True)    # без newline
    else:
        print(msg, flush=True)


def print_bar_line(
    label: str,
    pct: float,
    *,
    tick: int = 0,
    done: bool = False,
    extra: str = "",
) -> None:
    """Одна перезаписываемая строка-бар для этапа с известным % (не по чанкам: напр. ffmpeg).

    TTY: `\\r` + очистка до конца строки + бар, БЕЗ `\\n` — живая перезапись на месте.
    Non-TTY: обычная строка (вызывающий сам дросселирует частоту, чтобы не спамить лог).
    `tick` крутит спиннер — видно «жизнь» даже когда % растёт медленно.
    """
    p = max(0.0, min(100.0, float(pct)))
    mark = _DONE if done else spinner(tick)
    bar = render_bar(p)
    extra_str = f"  {extra}" if extra else ""
    msg = f"  {label}: {bar} {int(p)}% {mark}{extra_str}"
    if is_tty():
        end = "\n" if done else ""
        sys.stdout.write(f"\r{_CLEAR_EOL}{msg}{end}")
        sys.stdout.flush()
    else:
        print(msg, flush=True)


def print_spin_line(label: str, *, tick: int = 0, done: bool = False, extra: str = "") -> None:
    """Живой спиннер без процента — для этапа без измеримого прогресса (видно, что идёт работа).

    TTY: перезапись строки со сменой кадра спиннера. Non-TTY: печатаем только финал (done),
    чтобы не спамить лог тикающими строками.
    """
    mark = _DONE if done else spinner(tick)
    extra_str = f"  {extra}" if extra else ""
    msg = f"  {label}… {mark}{extra_str}"
    if is_tty():
        end = "\n" if done else ""
        sys.stdout.write(f"\r{_CLEAR_EOL}{msg}{end}")
        sys.stdout.flush()
    elif done:
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


# ------------------------------------------------------------------- скачивание (байтовый прогресс)

def format_duration(sec: float) -> str:
    """Секунды → «H:MM:SS» (с часами) или «M:SS» (без) — для ETA и итога."""
    total = int(max(0, round(sec)))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def format_speed(bytes_per_sec: float) -> str:
    """Скорость в МБ/с (≥1 МБ/с) или КБ/с (медленнее)."""
    mb = bytes_per_sec / (1 << 20)
    if mb >= 1:
        return f"{mb:.1f} МБ/с"
    return f"{bytes_per_sec / (1 << 10):.0f} КБ/с"


def _gb(nbytes: float) -> str:
    return f"{nbytes / (1 << 30):.1f}"


def eta_seconds(total: int | None, downloaded: int, speed_bps: float) -> float | None:
    """Оценка «осталось» = (всего − скачано) / скорость. None если неизвестно/готово."""
    if not total or speed_bps <= 0 or total <= downloaded:
        return None
    return (total - downloaded) / speed_bps


def format_download_line(downloaded: int, total: int | None, speed_bps: float) -> str:
    """Читаемая строка прогресса скачивания.

    Известен размер: «↓ скачивание: 26% | 3.3/12.5 ГБ | 2.0 МБ/с | осталось ~1:19:00».
    Размер неизвестен: «↓ скачивание: 3.3 ГБ | 2.0 МБ/с» (без % и ETA).
    """
    speed = format_speed(speed_bps)
    if total:
        pct = int(100 * downloaded / total) if total > 0 else 0
        parts = [f"↓ скачивание: {pct}%", f"{_gb(downloaded)}/{_gb(total)} ГБ", speed]
        eta = eta_seconds(total, downloaded, speed_bps)
        if eta is not None:
            parts.append(f"осталось ~{format_duration(eta)}")
        return " | ".join(parts)
    return f"↓ скачивание: {_gb(downloaded)} ГБ | {speed}"


def format_download_done(total_bytes: int, elapsed_sec: float) -> str:
    """Итоговая строка: «✓ скачано 12.5 ГБ за 1:48:00»."""
    return f"✓ скачано {_gb(total_bytes)} ГБ за {format_duration(elapsed_sec)}"


def print_download_progress(downloaded: int, total: int | None, speed_bps: float) -> None:
    """Обновить ОДНУ строку прогресса скачивания.

    TTY: `\\r` + очистка до конца строки (`\\033[K`) + текст, БЕЗ `\\n` — курсор в начало,
    хвост прошлой строки стёрт, следующее обновление перезапишет на месте (без переноса,
    в отличие от добивки пробелами до фикс. ширины — та переносилась на узких терминалах).
    Не-TTY (пайп/файл): обычная строка с `\\n`.
    """
    line = format_download_line(downloaded, total, speed_bps)
    if is_tty():
        sys.stdout.write(f"\r{_CLEAR_EOL}{line}")
        sys.stdout.flush()
    else:
        print(line, flush=True)


def print_download_done(total_bytes: int, elapsed_sec: float) -> None:
    """Напечатать итог скачивания. TTY: закрывает перезаписываемую строку через `\\n`."""
    line = format_download_done(total_bytes, elapsed_sec)
    if is_tty():
        sys.stdout.write(f"\r{_CLEAR_EOL}{line}\n")
        sys.stdout.flush()
    else:
        print(line, flush=True)
