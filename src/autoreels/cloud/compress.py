"""Сжатие транскрипта: word-level → sentence-level ПРОЕКЦИЯ для LLM (шаг 5).

Это сжатие ВХОДА в LLM (чтобы влезть в 6K TPM Groq), НЕ потеря данных. word-level
живёт в `Transcript` и обязан дожить до R1 (snap границ) и R3 (субтитры) — поэтому
`compress_transcript` ничего не мутирует, а возвращает текстовую проекцию.

Формат строки — контракт с prompts/r0_system.md §1 (рассогласование сломает R0):
    [START-END] текст предложения
одна строка = одно предложение, таймкоды — абсолютные секунды.

Граница предложения: по пунктуации (.?!…) ИЛИ по паузе между словами > порога
(`sentence_pause_sec` из config/r0.yaml — Whisper на русском часто роняет пунктуацию).

Принудительное дробление: предложение длиннее `max_sentence_sec` режется по границам
СЛОВ на под-строки ≤ порога — чтобы у R0 не было строк-гигантов (момент внутри гиганта
иначе недостижим: LLM выбирает только целые строки). Слова никогда не режутся посередине.
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


def _split_into_sentences(words: list[Word], pause_sec: float) -> list[list[Word]]:
    """Разбить слова на предложения по пунктуации или паузе > pause_sec."""
    sentences: list[list[Word]] = []
    current: list[Word] = []
    for i, w in enumerate(words):
        current.append(w)
        is_last = i == len(words) - 1
        gap_breaks = not is_last and (words[i + 1].t0 - w.t1) > pause_sec
        if is_last or _ends_sentence(w.word) or gap_breaks:
            sentences.append(current)
            current = []
    return sentences


def _best_cut(words: list[Word]) -> int:
    """Индекс реза по самой длинной внутренней паузе; при равенстве — ближе к середине."""
    mid = len(words) / 2
    gaps = [(words[k].t0 - words[k - 1].t1, k) for k in range(1, len(words))]
    max_gap = max(g for g, _ in gaps)
    candidates = [k for g, k in gaps if abs(g - max_gap) <= 1e-9]
    return min(candidates, key=lambda k: abs(k - mid))


def _enforce_max(sentence: list[Word], max_sec: float | None) -> list[list[Word]]:
    """Раздробить предложение длиннее max_sec по СМЫСЛУ — рекурсивно по самым длинным
    паузам внутри (естественная граница мысли), а не по фиксированной секунде. Рез всегда
    на границе слова; куски не короче чем нужно (легальные моменты ≤ max_sec остаются целыми).
    """
    if max_sec is None or len(sentence) <= 1:
        return [sentence]
    if (sentence[-1].t1 - sentence[0].t0) <= max_sec:
        return [sentence]
    k = _best_cut(sentence)
    return _enforce_max(sentence[:k], max_sec) + _enforce_max(sentence[k:], max_sec)


def compress_transcript(
    transcript: Transcript, *, pause_sec: float, max_sentence_sec: float | None = None
) -> str:
    """Вернуть sentence-level проекцию транскрипта (read-only, без мутации).

    `max_sentence_sec=None` → без принудительного дробления (обратная совместимость).
    """
    lines: list[str] = []
    for sentence in _split_into_sentences(transcript.words, pause_sec):
        for chunk in _enforce_max(sentence, max_sentence_sec):
            lines.append(_format_line(chunk))
    return "\n".join(lines)
