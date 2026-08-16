"""Диагностика обрывов фраз: классификация КОНЦА каждого клипа по транскрипту (детерминированно).

Отвечает на «какой этап рвёт фразу» после правок snap/padding/рубрики. Классы конца:
- CLEAN — конец предложения (.!?) / пауза ≥ min_pause / конец речи;
- SOFT  — пауза max_micro_pause…min_pause на нормальном слове (естественный вдох, приемлемо);
- HARD  — жёсткий обрыв: висячее слово / после запятой / мид-слово (пауза < max_micro_pause).
Для HARD — причина (механизм): PAD-хвост (перелёт за чистую фразу ≈ tail_pad) или snap-fallback.

Ядро (classify_end/summarize) — чистые функции без IO/конфига: единица под юнит-тесты.
"""
from __future__ import annotations

from dataclasses import dataclass

from autoreels.cloud.snap import _clean, _ends_midphrase, _is_sentence_end, _phrase_end_times
from autoreels.core.models import Word

_SENT_PUNCT = ".!?…"


@dataclass
class EndDiag:
    """Разбор конца одного клипа."""
    reel_id: str
    duration: float
    last_words: str
    end_type: str          # фраза(.!?) / пауза≥N / конец речи / висячее / запятая / мид-слово / пауза
    pause_after: float | None
    verdict: str           # CLEAN / SOFT / HARD
    cause: str             # "" для CLEAN/SOFT; для HARD — механизм


def _hard_cause(end: float, words: list[Word], end_type: str, *, min_pause: float,
                max_micro_pause: float, tail_pad_sec: float, hanging_words) -> str:
    """Механизм HARD-обрыва: перелёт padding-хвоста за чистую фразу (≈ tail_pad) → PAD-хвост,
    иначе — snap-fallback (в сегменте нет чистой границы)."""
    ends = _phrase_end_times(words, min_pause=min_pause, max_micro_pause=max_micro_pause,
                             hanging_words=hanging_words)
    pe = max([t for t in ends if t <= end + 0.05], default=None)
    if pe is not None and 0.05 < (end - pe) <= tail_pad_sec + 0.35:
        return f"PAD-хвост +{end - pe:.2f}с"
    if end_type in ("висячее", "запятая"):
        return f"{end_type} (snap-fallback)"
    return "snap-fallback (нет чистой границы)"


def classify_end(reel_id: str, start: float, end: float, words: list[Word], *,
                 min_pause: float, max_micro_pause: float, tail_pad_sec: float,
                 hanging_words) -> EndDiag:
    """Классифицировать конец клипа [start, end] по словам транскрипта. Чистая функция."""
    dur = round(end - start, 1)
    prev = [w for w in words if w.t1 <= end + 0.05]
    last_words = " ".join(w.word for w in prev[-5:])
    if not prev:
        return EndDiag(reel_id, dur, "", "нет слов", None, "HARD", "нет слов в клипе")
    lw = prev[-1]
    # Перекрытие таймкодов Whisper: следующее слово начинается ВНУТРИ конца предложения
    # («психосоматика.» 1090.5–1092.1, «И» 1092.04–1092.12) — клип кончается на «.», а «И» лишь
    # захватило край. Считаем концом само предложение, а не перекрывший его артефакт.
    while len(prev) >= 2 and prev[-1].t0 < prev[-2].t1 and _is_sentence_end(prev[-2].word):
        prev = prev[:-1]
        lw = prev[-1]
    nxt = [w for w in words if w.t0 > lw.t1 + 0.001]
    gap = round(nxt[0].t0 - lw.t1, 2) if nxt else None
    raw = lw.word.strip()

    def hard(end_type):
        return EndDiag(reel_id, dur, last_words, end_type, gap, "HARD",
                       _hard_cause(end, words, end_type, min_pause=min_pause,
                                   max_micro_pause=max_micro_pause, tail_pad_sec=tail_pad_sec,
                                   hanging_words=hanging_words))

    if raw and raw[-1] in _SENT_PUNCT:
        return EndDiag(reel_id, dur, last_words, "фраза(.!?)", gap, "CLEAN", "")
    if gap is None:
        return EndDiag(reel_id, dur, last_words, "конец речи", None, "CLEAN", "")
    if _ends_midphrase(lw.word):
        return hard("запятая")
    if _clean(lw.word) in set(hanging_words):
        return hard("висячее")
    if gap >= min_pause:
        return EndDiag(reel_id, dur, last_words, f"пауза≥{min_pause:.1f}", gap, "CLEAN", "")
    if gap < max_micro_pause:
        return hard("мид-слово")
    return EndDiag(reel_id, dur, last_words, "пауза", gap, "SOFT", "")   # 0.4…1.5с — приемлемо


def summarize(diags: list[EndDiag]) -> dict:
    """Сводка: сколько CLEAN/SOFT/HARD + разбивка HARD по причинам."""
    out = {"clean": 0, "soft": 0, "hard": 0, "causes": {}}
    for d in diags:
        out[d.verdict.lower()] += 1
        if d.verdict == "HARD":
            key = d.cause.split(" +")[0]        # «PAD-хвост +0.70с» → «PAD-хвост»
            out["causes"][key] = out["causes"].get(key, 0) + 1
    return out
