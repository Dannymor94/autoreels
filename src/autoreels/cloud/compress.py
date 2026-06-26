"""Сжатие транскрипта: word-level → sentence-level ПРОЕКЦИЯ для LLM (шаг 5).

Это сжатие ВХОДА в LLM (чтобы влезть в 6K TPM Groq), НЕ потеря данных. word-level
живёт в `Transcript` и обязан дожить до R1 (snap границ) и R3 (субтитры) — поэтому
`compress_transcript` ничего не мутирует, а возвращает текстовую проекцию.

Формат строки — контракт с prompts/r0_system.md §1 (рассогласование сломает R0):
    [START-END] текст предложения
одна строка = одно предложение, таймкоды — абсолютные секунды.

Граница предложения: по пунктуации (.?!…) ИЛИ по паузе между словами > порога
(`sentence_pause_sec` из config/r0.yaml — Whisper на русском часто роняет пунктуацию).
"""
from __future__ import annotations

from autoreels.core.models import Transcript, Word

_SENTENCE_END = (".", "?", "!", "…")
# Закрывающие кавычки/скобки после терминальной пунктуации («…травма.» / (так).)
_TRAILING = "»\"')]"


def _ends_sentence(word: str) -> bool:
    """Слово завершает предложение (после отбрасывания закрывающих кавычек/скобок)."""
    return word.rstrip(_TRAILING).endswith(_SENTENCE_END)


def _format_line(words: list[Word]) -> str:
    start = words[0].t0
    end = words[-1].t1
    text = " ".join(w.word for w in words)
    # Zero-pad до 4 целых разрядов + 1 знак после точки (R0_SPEC §1: [0124.3-0131.0]).
    return f"[{start:06.1f}-{end:06.1f}] {text}"


def compress_transcript(transcript: Transcript, *, pause_sec: float) -> str:
    """Вернуть sentence-level проекцию транскрипта (read-only, без мутации)."""
    lines: list[str] = []
    current: list[Word] = []

    for i, w in enumerate(transcript.words):
        current.append(w)
        is_last = i == len(transcript.words) - 1
        gap_breaks = (
            not is_last
            and (transcript.words[i + 1].t0 - w.t1) > pause_sec
        )
        if is_last or _ends_sentence(w.word) or gap_breaks:
            lines.append(_format_line(current))
            current = []

    return "\n".join(lines)
