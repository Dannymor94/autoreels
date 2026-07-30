"""Форматы вывода транскрипта для отдельной команды `autoreels transcribe`.

Ядро (`run`) держит транскрипт word-level внутри тира. Здесь — человеко-читаемые
проекции для генерации контента и субтитров, БЕЗ участия LLM (детерминированный код):

- `to_text`  — связный текст, разбитый на абзацы по длинным паузам, без таймкодов
               (под переработку в пост/статью). Абзац = группа предложений; новый абзац
               начинается там, где пауза между предложениями превышает paragraph_pause_sec.
- `to_srt`   — субтитры с таймкодами (`HH:MM:SS,mmm`), нумерация реплик.
- `to_vtt`   — WebVTT (те же реплики, `HH:MM:SS.mmm`, заголовок `WEBVTT`).
- `to_json`  — сырой word-level [{word,t0,t1}] (полные данные).

Предложения режутся тем же `_split_into_sentences`, что и compress (пунктуация или пауза
> sentence_pause_sec) — единый источник границ мысли, без дублирования логики.
"""
from __future__ import annotations

import json

from autoreels.cloud.compress import _split_into_sentences
from autoreels.core.models import Transcript, Word


def _sentences(transcript: Transcript, pause_sec: float) -> list[list[Word]]:
    """Непустые предложения транскрипта (переиспользует границы compress)."""
    return [s for s in _split_into_sentences(transcript.words, pause_sec) if s]


def _join(words: list[Word]) -> str:
    return " ".join(w.word for w in words)


def to_text(
    transcript: Transcript, *, sentence_pause_sec: float, paragraph_pause_sec: float
) -> str:
    """Связный читаемый текст, абзацы по длинным паузам, без таймкодов.

    Слова склеиваются в предложения, предложения — в абзацы. Новый абзац начинается,
    когда пауза между концом предыдущего предложения и началом следующего превышает
    `paragraph_pause_sec` (естественная смена мысли). Абзацы разделяются пустой строкой.
    """
    sents = _sentences(transcript, sentence_pause_sec)
    if not sents:
        return ""

    paragraphs: list[list[str]] = []
    current: list[str] = []
    for i, sent in enumerate(sents):
        if current:
            gap = sent[0].t0 - sents[i - 1][-1].t1
            if gap > paragraph_pause_sec:
                paragraphs.append(current)
                current = []
        current.append(_join(sent))
    if current:
        paragraphs.append(current)

    return "\n\n".join(" ".join(p) for p in paragraphs)


def _ts(sec: float, sep: str) -> str:
    """Таймкод HH:MM:SS<sep>mmm (`sep=','` для SRT, `'.'` для VTT)."""
    ms_total = int(round(sec * 1000))
    h, ms_total = divmod(ms_total, 3_600_000)
    m, ms_total = divmod(ms_total, 60_000)
    s, ms = divmod(ms_total, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _cues(transcript: Transcript, pause_sec: float, sep: str) -> list[str]:
    """Реплики субтитров: одна реплика на предложение (t0 первого → t1 последнего слова)."""
    blocks: list[str] = []
    for idx, sent in enumerate(_sentences(transcript, pause_sec), 1):
        stamp = f"{_ts(sent[0].t0, sep)} --> {_ts(sent[-1].t1, sep)}"
        blocks.append(f"{idx}\n{stamp}\n{_join(sent)}")
    return blocks


def to_srt(transcript: Transcript, *, sentence_pause_sec: float) -> str:
    """SRT-субтитры: нумерованные реплики с таймкодами `HH:MM:SS,mmm`."""
    cues = _cues(transcript, sentence_pause_sec, ",")
    return ("\n\n".join(cues) + "\n") if cues else ""


def to_vtt(transcript: Transcript, *, sentence_pause_sec: float) -> str:
    """WebVTT: заголовок `WEBVTT` + реплики с таймкодами `HH:MM:SS.mmm`."""
    cues = _cues(transcript, sentence_pause_sec, ".")
    body = "\n\n".join(cues)
    return f"WEBVTT\n\n{body}\n" if cues else "WEBVTT\n"


def to_json(transcript: Transcript) -> str:
    """Сырой word-level: [{word, t0, t1}] (полные данные, для дальнейшей обработки)."""
    records = [{"word": w.word, "t0": w.t0, "t1": w.t1} for w in transcript.words]
    return json.dumps(records, ensure_ascii=False, indent=2)
