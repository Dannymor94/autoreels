"""R0 (ядро): промпт → LLM → парсинг строгого JSON → валидация → дедуп → отбор.

Принцип: **LLM предлагает и ранжирует, код решает и валидирует.** Скоры/границы от модели —
черновик; флаги, отбраковку, дедуп, ранжирование ставит детерминированный код здесь.

MVP-0 (5a): без чанкинга и snap к словам (это M1/шаг 6). Пустой `segments: []` — валидный
результат (CLAUDE.md инвариант 3), не ошибка.
"""
from __future__ import annotations

import json

from autoreels.cloud.providers import LLMProvider
from autoreels.core.models import Reel


# ----------------------------------------------------------------- токены/чанкинг

def _count_tokens(text: str) -> int:
    """Грубая оценка числа токенов: 4 символа ≈ 1 токен. Достаточно для чанкинга."""
    return max(1, len(text) // 4)


def split_compressed(compressed: str, chunk_tokens: int, overlap_tokens: int) -> list[str]:
    """Разбить сжатый транскрипт на перекрывающиеся чанки по строкам (предложениям).

    Каждый чанк — целые строки `[t0-t1] текст`, общий размер ≤ chunk_tokens (грубо).
    Чанк i+1 начинается с последних overlap_tokens строк чанка i (overlap-зона).
    Если весь текст помещается в chunk_tokens — возвращается [compressed].
    Гарантия завершения: позиция всегда движется вперёд (min +1 строка за итерацию).
    """
    lines = [ln for ln in compressed.splitlines() if ln.strip()]
    if not lines:
        return []
    if _count_tokens(compressed) <= chunk_tokens:
        return [compressed]

    chunks: list[str] = []
    i = 0
    while i < len(lines):
        # Набираем строки до chunk_tokens
        j = i
        tokens = 0
        while j < len(lines):
            t = _count_tokens(lines[j])
            if tokens + t > chunk_tokens and j > i:
                break
            tokens += t
            j += 1

        chunks.append("\n".join(lines[i:j]))
        if j >= len(lines):
            break

        # Вычисляем overlap: идём назад от j, пока не наберём overlap_tokens
        back = j
        ov = 0
        while back > i:
            t = _count_tokens(lines[back - 1])
            if ov + t > overlap_tokens:
                break
            ov += t
            back -= 1

        # Следующий чанк начинается с back, но минимум на 1 строку вперёд от i
        i = max(i + 1, back)

    return chunks if chunks else [compressed]

# Чек-флаги длины (ставит код, не модель — CLAUDE.md инвариант 6).
FLAG_TOO_LONG = "too_long"
FLAG_TOO_SHORT = "too_short"


class SelectError(Exception):
    """Невосстановимая ошибка R0 (например, LLM вернул невалидный JSON после ретрая)."""


# ------------------------------------------------------------------- сборка промпта

def _extract_prompt_body(text: str) -> str:
    """Рантайм-промпт живёт в первом ```-блоке r0_system.md; вне блока — документация."""
    lines = text.splitlines()
    fences = [i for i, ln in enumerate(lines) if ln.strip().startswith("```")]
    if len(fences) >= 2:
        return "\n".join(lines[fences[0] + 1 : fences[1]])
    return text


def build_prompt(
    system_text: str,
    fewshot: dict,
    compressed: str,
    *,
    min_score: int,
    min_duration: int,
    max_duration: int,
) -> list[dict]:
    """Собрать chat-сообщения: system (рубрика с подставленными переменными) +
    few-shot (input→output пары) + сжатый транскрипт последним user-сообщением.
    """
    system = (
        _extract_prompt_body(system_text)
        .replace("{{min_score}}", str(min_score))
        .replace("{{min_duration}}", str(min_duration))
        .replace("{{max_duration}}", str(max_duration))
    )
    messages: list[dict] = [{"role": "system", "content": system}]
    for ex in fewshot.get("examples", []):
        messages.append({"role": "user", "content": ex["input"]})
        messages.append({"role": "assistant", "content": json.dumps(ex["output"], ensure_ascii=False)})
    messages.append({"role": "user", "content": compressed})
    return messages


# -------------------------------------------------------------------------- парсинг

def parse_segments(raw: str) -> list[dict]:
    """Строгий парсинг JSON-контракта R0 → список сегментов. Кидает SelectError на брак."""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SelectError(f"невалидный JSON от LLM: {e}") from e
    if not isinstance(obj, dict) or not isinstance(obj.get("segments"), list):
        raise SelectError("в ответе LLM нет массива 'segments'")
    return obj["segments"]


def segments_to_reels(segments: list[dict]) -> list[Reel]:
    """Сегменты JSON → Reel-объекты (provisional id; финальный id ставит select)."""
    reels: list[Reel] = []
    for i, seg in enumerate(segments, 1):
        reels.append(Reel(
            id=f"r{i:02d}",
            start=seg["start"], end=seg["end"], score=seg["score"],
            hook=seg["hook"], title=seg["title"], description=seg["description"],
            reason=seg.get("reason", ""), topic=seg.get("topic", ""),
        ))
    return reels


# ------------------------------------------------------- валидаторы (код, не модель)

def flag_durations(reels: list[Reel], *, min_duration: int, max_duration: int) -> None:
    """Проставить too_long/too_short по длине вне пресета (мутирует flags на месте)."""
    for r in reels:
        dur = r.end - r.start
        if dur < min_duration and FLAG_TOO_SHORT not in r.flags:
            r.flags.append(FLAG_TOO_SHORT)
        if dur > max_duration and FLAG_TOO_LONG not in r.flags:
            r.flags.append(FLAG_TOO_LONG)


def filter_by_score(reels: list[Reel], *, min_score: int) -> list[Reel]:
    """Отбраковать сегменты со score < min_score."""
    return [r for r in reels if r.score >= min_score]


def _overlap_ratio(a: Reel, b: Reel) -> float:
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    shorter = min(a.end - a.start, b.end - b.start)
    return inter / shorter if shorter > 0 else 0.0


def dedup(reels: list[Reel], *, overlap_threshold: float) -> list[Reel]:
    """Пересечение > порога → оставить сегмент с большим score (жадно, по убыванию score)."""
    kept: list[Reel] = []
    for r in sorted(reels, key=lambda x: -x.score):
        if all(_overlap_ratio(r, k) <= overlap_threshold for k in kept):
            kept.append(r)
    return kept


# ------------------------------------------------------------------- верхний уровень

def _complete_and_parse(provider: LLMProvider, messages: list[dict]) -> list[dict]:
    """Вызвать LLM и распарсить; один ретрай на невалидном JSON, потом SelectError."""
    last_err: SelectError | None = None
    for _ in range(2):  # первичный вызов + один ретрай
        raw = provider.complete(messages)
        try:
            return parse_segments(raw)
        except SelectError as e:
            last_err = e
    raise SelectError(f"LLM вернул невалидный JSON после ретрая: {last_err}")


def _select_one(compressed: str, *, system_text: str, fewshot: dict,
                provider: LLMProvider, r0_cfg) -> list[Reel]:
    """Одиночный R0-запрос (без чанкинга): промпт → LLM → валидация → дедуп."""
    messages = build_prompt(
        system_text, fewshot, compressed,
        min_score=r0_cfg.min_score,
        min_duration=r0_cfg.min_duration,
        max_duration=r0_cfg.max_duration,
    )
    segments = _complete_and_parse(provider, messages)
    reels = segments_to_reels(segments)
    flag_durations(reels, min_duration=r0_cfg.min_duration, max_duration=r0_cfg.max_duration)
    reels = filter_by_score(reels, min_score=r0_cfg.min_score)
    reels = dedup(reels, overlap_threshold=r0_cfg.dedup_overlap_threshold)
    reels.sort(key=lambda r: -r.score)
    if r0_cfg.max_reels is not None:
        reels = reels[:r0_cfg.max_reels]
    for i, r in enumerate(reels, 1):
        r.id = f"r{i:02d}"
    return reels


def select_chunked(
    compressed: str,
    *,
    system_text: str,
    fewshot: dict,
    provider: LLMProvider,
    r0_cfg,
) -> list[Reel]:
    """R0 с чанкингом: транскрипт → чанки → LLM на каждый → смерж + дедуп по t0.

    Чанки перекрываются (overlap_tokens) → один и тот же момент может попасть в два
    соседних чанка. После смержа: cross-chunk dedup_reels (первый по t0), затем
    ранжирование по score и сквозная нумерация.
    """
    from autoreels.cloud.chunk_transcribe import dedup_reels, renumber_reels

    chunking = r0_cfg.chunking
    chunks = split_compressed(compressed, chunking.r0_chunk_tokens, chunking.r0_overlap_tokens)

    all_reels: list[Reel] = []
    for i, chunk in enumerate(chunks):
        print(f"  R0 чанк {i + 1}/{len(chunks)}…", flush=True)
        messages = build_prompt(
            system_text, fewshot, chunk,
            min_score=r0_cfg.min_score,
            min_duration=r0_cfg.min_duration,
            max_duration=r0_cfg.max_duration,
        )
        try:
            segs = _complete_and_parse(provider, messages)
        except SelectError as e:
            print(f"  ⚠ R0 чанк {i + 1} провалился: {e}", flush=True)
            continue
        reels = segments_to_reels(segs)
        flag_durations(reels, min_duration=r0_cfg.min_duration, max_duration=r0_cfg.max_duration)
        all_reels.extend(filter_by_score(reels, min_score=r0_cfg.min_score))

    # Дедуп по t0 (первый по хронологии при пересечении > порога)
    all_reels = dedup_reels(all_reels, chunking.dedup_overlap_ratio)
    all_reels.sort(key=lambda r: -r.score)
    if r0_cfg.max_reels is not None:
        all_reels = all_reels[:r0_cfg.max_reels]
    return renumber_reels(all_reels)


def select(
    compressed: str,
    *,
    system_text: str,
    fewshot: dict,
    provider: LLMProvider,
    r0_cfg,
) -> list[Reel]:
    """R0 end-to-end: диспетчер одиночного запроса или чанкинга.

    Если chunking включён и транскрипт превышает r0_chunk_tokens → select_chunked.
    Иначе (или если chunking не сконфигурирован) → одиночный запрос.
    Возвращает отранжированные по score Reel-объекты ([] — валидный результат).
    """
    chunking = getattr(r0_cfg, "chunking", None)
    if chunking and chunking.enabled and _count_tokens(compressed) > chunking.r0_chunk_tokens:
        return select_chunked(compressed, system_text=system_text, fewshot=fewshot,
                              provider=provider, r0_cfg=r0_cfg)
    return _select_one(compressed, system_text=system_text, fewshot=fewshot,
                       provider=provider, r0_cfg=r0_cfg)
