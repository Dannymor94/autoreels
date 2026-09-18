"""R0 (ядро): промпт → LLM → парсинг строгого JSON → валидация → дедуп → отбор.

Принцип: **LLM предлагает и ранжирует, код решает и валидирует.** Скоры/границы от модели —
черновик; флаги, отбраковку, дедуп, ранжирование ставит детерминированный код здесь.

MVP-0 (5a): без чанкинга и snap к словам (это M1/шаг 6). Пустой `segments: []` — валидный
результат (CLAUDE.md инвариант 3), не ошибка.
"""
from __future__ import annotations

import json
import time

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
    i: int = 0
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


def _effective_chunk_tokens(
    system_text: str,
    fewshot: dict,
    chunk_tokens: int,
    *,
    max_output_tokens: int = 900,
    template_overhead: int = 400,
    groq_limit: int = 8000,
    underestimation_factor: float = 1.45,
) -> int:
    """Derive safe chunk budget so the scaled request stays within groq_limit.

    Formula (solving for chunk_budget_est):
      (system_est + fewshot_est + chunk_budget_est) × factor + template + max_out ≤ limit
      → chunk_budget_est = (limit − max_out − template) / factor − system_est − fewshot_est

    Also capped by the configured r0_chunk_tokens upper bound.
    Minimum 500 tokens to avoid infinite chunking loops.
    underestimation_factor should come from the persisted token_scale state (GroqLLM),
    defaulting to 1.45 on first run (calibrates to observed ~1.37-1.40 after a few runs).
    """
    system_tok = _count_tokens(system_text)
    fewshot_tok = 0
    for ex in fewshot.get("examples", []):
        fewshot_tok += _count_tokens(ex.get("input", ""))
        fewshot_tok += _count_tokens(json.dumps(ex.get("output", ""), ensure_ascii=False))
    limit_budget = int((groq_limit - max_output_tokens - template_overhead) / underestimation_factor) - system_tok - fewshot_tok
    return max(500, min(chunk_tokens, limit_budget))


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
    target_candidates: int | None = None,
) -> list[dict]:
    """Собрать chat-сообщения: system (рубрика с подставленными переменными) +
    few-shot (input→output пары) + сжатый транскрипт последним user-сообщением.
    """
    system = (
        _extract_prompt_body(system_text)
        .replace("{{min_score}}", str(min_score))
        .replace("{{min_duration}}", str(min_duration))
        .replace("{{max_duration}}", str(max_duration))
        .replace("{{target_candidates}}", str(target_candidates) if target_candidates else "all qualifying")
    )
    messages: list[dict] = [{"role": "system", "content": system}]
    for ex in fewshot.get("examples", []):
        messages.append({"role": "user", "content": ex["input"]})
        messages.append({"role": "assistant", "content": json.dumps(ex["output"], ensure_ascii=False)})
    messages.append({"role": "user", "content": compressed})
    return messages


# -------------------------------------------------------------------------- парсинг

def parse_segments(raw) -> list[dict]:
    """Строгий парсинг JSON-контракта R0 → список сегментов. Кидает SelectError на брак.

    None/пустой ответ проверяется ДО json.loads: провайдер под нагрузкой отдаёт HTTP 200 с
    пустым телом, а json.loads(None) кидает TypeError (не JSONDecodeError) — раньше это роняло
    всё видео. Теперь → SelectError, т.е. обычный провал чанка (retry/failed, видео живёт)."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise SelectError("пустой ответ от LLM (провайдер вернул None/пустое тело)")
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


def filter_by_duration(reels: list[Reel], *, min_meaningful_sec: float) -> list[Reel]:
    """Отбраковать сегменты короче min_meaningful_sec (планка «законченной мысли»).

    Детерминированный отсев «пустых» коротышей: LLM склонна переоценивать «лучший кусок
    в чанке» даже когда мысль не завершена. Планка выше технического min_duration пресета —
    короткий сегмент снимается независимо от score. Лечит «пустые 15-сек клипы».
    """
    return [r for r in reels if (r.end - r.start) >= min_meaningful_sec]


def diagnose_collapse(r: Reel) -> str:
    """Объяснить, почему клип оказался слишком коротким после snap+padding.

    Сравнивает r0_start/r0_end (границы до snap) с финальными start/end.
    Если r0_* не сохранены (старый манифест) — сообщает об этом.
    """
    final_dur = r.end - r.start
    if r.r0_start is None or r.r0_end is None:
        return f"длина {final_dur:.1f}с (r0_start/r0_end не сохранены — старый манифест)"
    r0_dur = r.r0_end - r.r0_start
    # Если R0-длина лишь чуть больше финала (в пределах 1с) — snap тут ни при чём,
    # момент был коротким уже на этапе LLM-выборки.
    if r0_dur < final_dur + 1.0:
        return f"R0 вернул {r0_dur:.1f}с — момент был коротким при выборке"
    return f"R0 {r0_dur:.1f}с → snap/padding схлопнули до {final_dur:.1f}с"



def filter_min_clip_duration(reels: list[Reel], *, min_clip_duration: float) -> list[Reel]:
    """Пост-snap фильтр: убрать клипы короче min_clip_duration.

    Вызывается ПОСЛЕ snap+padding+trim (пост-snap). Отличается от filter_by_duration
    (пре-snap): snap может схлопнуть хороший 18с момент до 1с — этот фильтр ловит такие случаи.
    Перед применением этого фильтра вызовите try_rescue_clip (snap.py) для попытки расширения.
    """
    return [r for r in reels if r.end - r.start >= min_clip_duration]


_DEFAULT_DANGLING = frozenset({
    "поэтому", "потому", "и", "вот", "то", "так", "любом", "же",
    "он", "она", "они", "его", "её", "их", "им", "ним",
    "это", "этот", "эта", "эти", "того", "этого",
    "который", "которая", "которые",
    "ведь", "значит", "тоже", "также",
    "а", "но", "или", "либо", "однако",
})


_TERMINAL_MARKS = frozenset(".?!")


def _word_ends_sentence(w) -> bool:
    """True if word ends with a sentence-terminal punctuation mark."""
    return bool(w.word) and w.word.rstrip("»\"')").endswith(tuple(_TERMINAL_MARKS))


def filter_dangling_start(
    reels: list[Reel],
    transcript_words: list,
    *,
    dangling_words: list[str] | None = None,
    min_duration: float = 15.0,
    max_start_repair_sec: float = 10.0,
) -> tuple[list[Reel], list[dict]]:
    """Drop (or repair) clips whose snapped first word begins lowercase or is a dangling connective.

    Repair priority (in order):
    (a) If a sentence-terminal mark (.?!) exists within max_start_repair_sec, move start to the
        word immediately after it — regardless of case or connective status.
    (b) Otherwise, scan for first uppercase non-dangling word within the window.
    (c) Only if neither works: drop.

    Pre-pass: an opening sentence that ends in '…'/'...' (ellipsis) is an incomplete fragment;
    the clip is advanced past it (up to 3 such sentences) before the main check runs.

    The connective list applies only to path (b), not to words following a terminal mark.
    Must be called AFTER snap. Returns (kept, discarded_entries).
    """
    from autoreels.local.subtitles import words_in_window
    dw = _DEFAULT_DANGLING | set(dangling_words or [])
    kept, disc = [], []
    for r in reels:
        # Pre-pass: skip opening sentences that end in ellipsis ('…' / '...').
        for _ in range(3):
            clip_words = words_in_window(transcript_words, r.start, r.end)
            if not clip_words:
                break
            deadline = r.start + max_start_repair_sec
            ellipsis_idx = None
            for i, w in enumerate(clip_words):
                if w.t0 > deadline:
                    break
                ws = w.word.rstrip()
                if ws.endswith(("…", "...")):
                    ellipsis_idx = i
                    break
                if ws.endswith((".", "?", "!")):
                    break   # clean sentence end — stop looking for ellipsis
            if ellipsis_idx is None:
                break
            if ellipsis_idx + 1 >= len(clip_words):
                break
            nw = clip_words[ellipsis_idx + 1]
            if nw.t0 > deadline or r.end - nw.t0 < min_duration:
                break
            r.start = nw.t0
            r.start_snap_reason = "repaired_to_sentence"
            if "start_repaired" not in r.flags:
                r.flags.append("start_repaired")

        clip_words = words_in_window(transcript_words, r.start, r.end)
        first_8 = " ".join(w.word for w in clip_words[:8])
        if not clip_words:
            kept.append(r)
            continue
        fw = clip_words[0].word.strip()
        fw_clean = fw.strip(".,!?;:—–-«»\"'()").lower()
        is_lowercase = bool(fw) and fw[0].islower()
        is_dangling = fw_clean in dw
        orig_start = r.start
        if is_lowercase or is_dangling:
            repair_deadline = orig_start + max_start_repair_sec
            repaired = False
            # (a) terminal-mark scan: first word after a sentence-ending word
            for i, w in enumerate(clip_words[:-1]):
                if w.t0 > repair_deadline:
                    break
                if _word_ends_sentence(w):
                    nw = clip_words[i + 1]
                    if nw.t0 <= repair_deadline and r.end - nw.t0 >= min_duration:
                        r.start = nw.t0
                        r.start_repair_sec = nw.t0 - orig_start
                        r.start_snap_reason = "repaired_to_sentence"
                        r.flags.append("start_repaired")
                        repaired = True
                    break
            # (b) uppercase non-dangling scan (only if (a) didn't fire)
            if not repaired:
                for w in clip_words[1:]:
                    if w.t0 > repair_deadline:
                        break
                    wc = w.word.strip(".,!?;:—–-«»\"'()").lower()
                    if w.word and w.word[0].isupper() and wc not in dw:
                        new_start = w.t0
                        if r.end - new_start >= min_duration:
                            r.start = new_start
                            r.start_repair_sec = new_start - orig_start
                            r.start_snap_reason = "repaired_to_sentence"
                            r.flags.append("start_repaired")
                            repaired = True
                        break
            if not repaired:
                reason = "dangling_start: " + (
                    "первое слово со строчной буквы" if is_lowercase
                    else f"висячее слово «{fw_clean}»"
                )
                r.flags.append("dangling_start")
                disc.append({"id": r.id, "score": r.score, "reason": reason, "first_words": first_8})
            else:
                kept.append(r)
        else:
            kept.append(r)
    return kept, disc


def apply_top_n(
    reels: list[Reel],
    *,
    max_reels: int | None,
    transcript_words: list | None = None,
) -> tuple[list[Reel], list[dict]]:
    """Sort by score desc, apply top-N cut, assign rank 1-N. Returns (kept, discarded_entries).

    Human-merged reels (flags contains 'human_merged') are always kept and do not count
    against the max_reels budget.
    """
    from autoreels.local.subtitles import words_in_window
    reels_sorted = sorted(reels, key=lambda r: -r.score)
    if max_reels is None:
        kept, cut = reels_sorted, []
    else:
        merged = [r for r in reels_sorted if "human_merged" in r.flags]
        others = [r for r in reels_sorted if "human_merged" not in r.flags]
        n_others = max(0, max_reels - len(merged))
        kept = merged + others[:n_others]
        cut = others[n_others:]
    disc = []
    for pos, r in enumerate(cut, (max_reels or 0) + 1):
        first_8 = ""
        if transcript_words:
            clip_words = words_in_window(transcript_words, r.start, r.end)
            first_8 = " ".join(w.word for w in clip_words[:8])
        disc.append({"id": r.id, "score": r.score,
                     "reason": f"below top-{max_reels} cut (rank: {pos})",
                     "first_words": first_8})
    for i, r in enumerate(kept, 1):
        r.rank = i
    return kept, disc


def _overlap_ratio(a: Reel, b: Reel) -> float:
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    shorter = min(a.end - a.start, b.end - b.start)
    return inter / shorter if shorter > 0 else 0.0


def dedup(reels: list[Reel], *, overlap_threshold: float, dropped: list[dict] | None = None) -> list[Reel]:
    """Пересечение > порога → оставить сегмент с большим score (жадно, по убыванию score).

    If `dropped` is given, appends sidecar-ready dicts for each eliminated reel.
    """
    kept: list[Reel] = []
    for r in sorted(reels, key=lambda x: -x.score):
        winner = next((k for k in kept if _overlap_ratio(r, k) > overlap_threshold), None)
        if winner is None:
            kept.append(r)
        elif dropped is not None:
            dropped.append({
                "id": r.id, "score": r.score,
                "reason": f"overlap_dedup: overlaps {winner.id}",
                "first_words": r.hook[:80],
            })
    return kept


# ------------------------------------------------------------------- верхний уровень

def _complete_and_parse(provider: LLMProvider, messages: list[dict]) -> list[dict]:
    """Вызвать LLM и распарсить; один ретрай на невалидном/пустом ответе, потом SelectError.

    Пустой ответ провайдера (ProviderEmptyResponse — пул уже пробовал сиблинга) сразу становится
    провалом чанка: не роняем видео, select_chunked ловит SelectError и продолжает."""
    from autoreels.cloud.providers import ProviderEmptyResponse, ProviderError, ProviderTimeout
    last_err: SelectError | None = None
    for _ in range(2):  # первичный вызов + один ретрай
        try:
            raw = provider.complete(messages)
        except (ProviderEmptyResponse, ProviderTimeout, ProviderError) as e:
            # Пул уже пробовал сиблингов → провал ЧАНКА (select_chunked ловит SelectError,
            # продолжает; всё видео не падает). Сообщение несёт провайдера/причину.
            # ProviderError (базовый) ловим тоже: любая ошибка провайдера — chunk-fail,
            # не video-kill. Так error-body-в-HTTP-200 (OpenRouter) не ронит весь прогон.
            raise SelectError(f"{e}") from e
        try:
            return parse_segments(raw)
        except SelectError as e:
            last_err = e
    raise SelectError(f"LLM вернул невалидный/пустой ответ после ретрая: {last_err}")


def _select_one(compressed: str, *, system_text: str, fewshot: dict,
                provider: LLMProvider, r0_cfg, _dropped: list[dict] | None = None) -> list[Reel]:
    """Одиночный R0-запрос (без чанкинга): промпт → LLM → валидация → дедуп.

    Top-N cut, rank, and dangling_start filter happen later (after snap) in __main__.
    """
    target = getattr(r0_cfg, "target_candidates", None)
    messages = build_prompt(
        system_text, fewshot, compressed,
        min_score=r0_cfg.min_score,
        min_duration=r0_cfg.min_duration,
        max_duration=r0_cfg.max_duration,
        target_candidates=target,
    )
    segments = _complete_and_parse(provider, messages)
    reels = segments_to_reels(segments)
    flag_durations(reels, min_duration=r0_cfg.min_duration, max_duration=r0_cfg.max_duration)
    reels = filter_by_score(reels, min_score=r0_cfg.min_score)
    reels = filter_by_duration(reels, min_meaningful_sec=r0_cfg.min_meaningful_sec)
    reels = dedup(reels, overlap_threshold=r0_cfg.dedup_overlap_threshold, dropped=_dropped)
    for i, r in enumerate(reels, 1):
        r.id = f"c{i:03d}"
    return reels


def select_chunked(
    compressed: str,
    *,
    system_text: str,
    fewshot: dict,
    provider: LLMProvider,
    r0_cfg,
    _dropped: list[dict] | None = None,
    _failed_chunks: list[dict] | None = None,
) -> list[Reel]:
    """R0 с чанкингом: транскрипт → чанки → LLM на каждый → смерж + дедуп по t0.

    Top-N cut, rank, and dangling_start filter happen later (after snap) in __main__.
    """
    from autoreels.cloud.chunk_transcribe import dedup_reels
    from autoreels.core.progress import chunk_progress, chunk_start, throttle_wait

    chunking = r0_cfg.chunking
    max_out = getattr(r0_cfg, "max_output_tokens", 900)
    factor = getattr(provider, "token_scale_factor", 1.45)
    effective_tokens = _effective_chunk_tokens(
        system_text, fewshot, chunking.r0_chunk_tokens,
        max_output_tokens=max_out,
        underestimation_factor=factor,
    )
    print(
        f"  ℹ R0 chunk budget: {effective_tokens} tok "
        f"(factor={factor:.3f}; config upper bound: {chunking.r0_chunk_tokens})",
        flush=True,
    )
    chunks = split_compressed(compressed, effective_tokens, chunking.r0_overlap_tokens)

    est_sec = len(chunks) * (chunking.r0_chunk_delay_sec + 15)
    chunk_start("R0", len(chunks), est_sec=est_sec)

    target = getattr(r0_cfg, "target_candidates", None)
    all_reels: list[Reel] = []
    for i, chunk in enumerate(chunks):
        if i > 0:
            throttle_wait(chunking.r0_chunk_delay_sec)
            time.sleep(chunking.r0_chunk_delay_sec)
        chunk_progress("R0", i + 1, len(chunks),
                       extra=f"найдено {len(all_reels)} моментов")
        messages = build_prompt(
            system_text, fewshot, chunk,
            min_score=r0_cfg.min_score,
            min_duration=r0_cfg.min_duration,
            max_duration=r0_cfg.max_duration,
            target_candidates=target,
        )
        _t0 = time.monotonic()
        try:
            segs = _complete_and_parse(provider, messages)
        except SelectError as e:
            elapsed = round(time.monotonic() - _t0, 1)
            print(f"\n  ⚠ R0 чанк {i + 1} провалился ({elapsed:.0f}с потрачено): {e}", flush=True)
            if _failed_chunks is not None:
                _failed_chunks.append({
                    "chunk_idx": i + 1,
                    "error": str(e),
                    "time_lost_sec": elapsed,
                })
            continue
        reels = segments_to_reels(segs)
        flag_durations(reels, min_duration=r0_cfg.min_duration, max_duration=r0_cfg.max_duration)
        reels = filter_by_score(reels, min_score=r0_cfg.min_score)
        reels = filter_by_duration(reels, min_meaningful_sec=r0_cfg.min_meaningful_sec)
        all_reels.extend(reels)
        provider_name = getattr(provider, "last_provider", None)
        via = f"via {provider_name} · " if provider_name else ""
        chunk_progress("R0", i + 1, len(chunks),
                       extra=f"{via}найдено {len(all_reels)} моментов")

    chunk_progress("R0", len(chunks), len(chunks),
                   extra=f"найдено {len(all_reels)} моментов", done=True)

    all_reels = dedup_reels(all_reels, chunking.dedup_overlap_ratio, dropped=_dropped)
    for i, r in enumerate(all_reels, 1):
        r.id = f"c{i:03d}"
    return all_reels


def select(
    compressed: str,
    *,
    system_text: str,
    fewshot: dict,
    provider: LLMProvider,
    r0_cfg,
    _dropped: list[dict] | None = None,
    _failed_chunks: list[dict] | None = None,
) -> list[Reel]:
    """R0 end-to-end: диспетчер одиночного запроса или чанкинга.

    Returns all post-dedup candidates with c{NNN} ids. Top-N cut, rank assignment,
    and dangling_start filter happen after snap in __main__ (they need snapped boundaries).
    If `_dropped` list is given, it is populated with overlap_dedup sidecar entries.
    If `_failed_chunks` list is given, failed chunk records ({chunk_idx, error, time_lost_sec})
    are appended there for the manifest sidecar (visible coverage gaps).
    """
    chunking = getattr(r0_cfg, "chunking", None)
    if chunking and chunking.enabled:
        max_out = getattr(r0_cfg, "max_output_tokens", 900)
        factor = getattr(provider, "token_scale_factor", 1.45)
        # Use effective budget (not raw config) as chunking threshold so that even
        # transcripts that fit in r0_chunk_tokens are chunked when the total request
        # (system+fewshot+chunk+template+max_tokens) would exceed the Groq limit.
        effective = _effective_chunk_tokens(system_text, fewshot, chunking.r0_chunk_tokens,
                                            max_output_tokens=max_out,
                                            underestimation_factor=factor)
        if _count_tokens(compressed) > effective:
            return select_chunked(compressed, system_text=system_text, fewshot=fewshot,
                                  provider=provider, r0_cfg=r0_cfg, _dropped=_dropped,
                                  _failed_chunks=_failed_chunks)
    return _select_one(compressed, system_text=system_text, fewshot=fewshot,
                       provider=provider, r0_cfg=r0_cfg, _dropped=_dropped)


# ---- interview host-turn detection ----

_SECOND_PERSON = frozenset({
    # informal (ты)
    "ты", "тебе", "тебя", "твой", "твоя", "твоё", "твоего", "твоему", "твою", "твоих",
    # formal (вы)
    "вы", "вас", "вам", "вашу", "ваш", "ваши", "вашего", "вашему",
})
_HOST_OPENERS = (
    # informal
    "расскажи", "а как ты", "а что ты", "бывало ли", "как ты",
    # formal
    "расскажите", "скажите", "как вы", "что вы", "почему вы", "когда вы",
)


_DASH_CHARS = ("—", "–")   # em-dash / en-dash: Whisper speaker-change marker


def _first_word_clean(word: str) -> str:
    """Strip leading dash/punct and lower-case for first-word comparisons."""
    return word.lstrip("".join(_DASH_CHARS) + " ").lower()


def detect_host_turns(transcript_words) -> list[tuple[float, float]]:
    """Return (start, end) spans of host turns (interrogative OR declarative).

    A turn qualifies when:
      (a) sentence ends with '?' AND (has second-person word OR starts with a host-opener), OR
      (b) sentence first word starts with 'ты'/'вы' (direct address to guest), OR
      (c) sentence first word starts with an em/en dash (Whisper speaker-change marker).

    Note on dash marking: in the PXL corpus only ~2 % of sentences carry a dash, so
    (c) is supplementary — it adds a handful of turns the heuristic would otherwise miss.
    The primary signal is (a)+(b).

    Condition (b) already catches declarative host turns like "Ты коснулся книги, ты стал
    автором книги…" because the sentence starts with "Ты". A potential condition (d) —
    short sentence with ты/вы + past-tense verb mid-sentence — is NOT added: in Russian,
    the guest freely uses ты to address the viewer ("когда ты честен с собой"), and a
    past-tense verb + ты mid-sentence is common in guest speech too. No reliable
    structural feature separates host address from guest narrative without a speaker-ID
    model; adding (d) would eat guest speech.

    ponytail: O(n) scan over word list; splits on terminal punct.
    """
    if not transcript_words:
        return []

    turns = []
    sent_words = []

    def _flush(buf):
        if not buf:
            return
        text = " ".join(w.word for w in buf).lower()
        last = buf[-1].word.rstrip()
        first_clean = _first_word_clean(buf[0].word)

        # (a) interrogative with second-person or opener
        if last.endswith("?"):
            has_2p = any(w.word.lower() in _SECOND_PERSON for w in buf)
            has_opener = any(text.startswith(op) for op in _HOST_OPENERS)
            if has_2p or has_opener:
                turns.append((buf[0].t0, buf[-1].t1))
                return

        # (b) declarative direct address: sentence starts with ты/вы
        if first_clean in ("ты", "вы"):
            turns.append((buf[0].t0, buf[-1].t1))
            return

        # (c) dash-marked speaker change
        if buf[0].word.startswith(_DASH_CHARS):
            turns.append((buf[0].t0, buf[-1].t1))

    for w in transcript_words:
        sent_words.append(w)
        if w.word.rstrip().endswith((".", "?", "!", "…")):
            _flush(sent_words)
            sent_words = []
    _flush(sent_words)  # trailing incomplete sentence
    return turns


# ---- interview snap stage ----

_MERGED_TAIL_SEC = 15.0   # look-back window for host turns at the tail of a merged reel


def _trim_tail_question(r, tx_words, max_tail_words: int = 8) -> bool:
    """Cut before a trailing question + short answer at the end of a clip.

    Pattern: '…resolved thought. Question? Short fragment.' — the question opens a new
    topic that belongs to the next exchange. Cut before the question when fewer than
    max_tail_words follow it.

    Returns True when the clip was shortened.
    """
    from autoreels.local.subtitles import words_in_window
    clip_words = words_in_window(tx_words, r.start, r.end)
    if not clip_words:
        return False

    # Find the last '?' in the clip.
    last_q_idx = None
    for i, w in enumerate(clip_words):
        if w.word.rstrip().endswith("?"):
            last_q_idx = i

    if last_q_idx is None:
        return False
    words_after = len(clip_words) - last_q_idx - 1
    if words_after >= max_tail_words:
        return False
    # Require at least some content before the question to avoid trimming the whole clip.
    if last_q_idx < 3:
        return False

    # Walk back to the start of the question sentence (first word after previous terminal).
    sent_start = last_q_idx
    for j in range(last_q_idx - 1, -1, -1):
        if clip_words[j].word.rstrip().endswith((".", "!", "?")):
            sent_start = j + 1
            break
    else:
        sent_start = 0

    r.end = clip_words[sent_start].t0 - 0.15
    r.end_snap_reason = "before_trailing_question"
    return True


def _trim_tail_affirmation(r, tx_words, affirmations: frozenset) -> bool:
    """If the last sentence of the clip is a single-word affirmation, trim it.

    Returns True when the clip was shortened. Mutates r.end and r.end_snap_reason.
    Only trims when the affirmation is a standalone sentence (preceded by terminal
    punct) and the word is in `affirmations` (lower-cased, punct-stripped).
    """
    if not affirmations:
        return False
    from autoreels.local.subtitles import words_in_window
    from autoreels.cloud.snap import _clean, _is_sentence_end

    clip_words = words_in_window(tx_words, r.start, r.end)
    if not clip_words:
        return False

    # Walk backwards: find the last sentence boundary, then check if tail is one affirmation word.
    # A "standalone sentence" = the single tail word that follows a sentence-terminal.
    tail = clip_words[-1]
    if not _is_sentence_end(tail.word):
        return False   # last word must end a sentence (else it's mid-sentence, don't trim)
    if len(clip_words) < 2:
        return False
    prev = clip_words[-2]
    if not _is_sentence_end(prev.word):
        return False   # previous word must also be a sentence-terminal (one-word sentence check)
    # The tail word is a complete one-word sentence; check if it's an affirmation.
    if _clean(tail.word) not in affirmations:
        return False
    # Trim: move end to just before this affirmation word.
    r.end = tail.t0 - 0.05
    r.end_snap_reason = "before_host_turn"
    return True


def _stage_interview_snap(
    reels: list,
    host_turns: list[tuple[float, float]],
    *,
    tx_words: list,
    r0_cfg,
) -> tuple[list, list[dict]]:
    """Enforce interview clip boundaries: end before host turn, optionally include host question."""
    from autoreels.local.subtitles import words_in_window

    kept = []
    disc = []
    min_dur = getattr(r0_cfg, "min_clip_duration", 15.0)
    affirmations = frozenset(getattr(r0_cfg, "host_affirmations", []))

    max_tail_words = getattr(r0_cfg, "trailing_question_words", 8)

    for r in reels:
        is_merged = "human_merged" in r.flags

        if is_merged:
            # Internal host turns between merged blocks are intentional — keep them.
            # Only trim host turns that appear in the last _MERGED_TAIL_SEC of the merged
            # span: those are closing remarks the reviewer did not intend to include.
            r0_end = r.r0_end if r.r0_end is not None else r.end
            tail_turns = [
                (ts, te) for ts, te in host_turns
                if ts >= r0_end - _MERGED_TAIL_SEC and ts < r.end + 10.0
                and te <= r.end + 10.0
            ]
            if tail_turns:
                earliest_ts = min(ts for ts, _ in tail_turns)
                r.end = earliest_ts - 0.15
                r.end_snap_reason = "before_host_turn"
        else:
            # --- end rule: move back before earliest host turn after r0_start ---
            r0_start = r.r0_start if r.r0_start is not None else r.start
            intruding = [
                (ts, te) for ts, te in host_turns
                if ts > r0_start and ts < r.end + 10.0 and te <= r.end + 10.0
            ]
            if intruding:
                earliest_ts = min(ts for ts, _ in intruding)
                r.end = earliest_ts - 0.15
                r.end_snap_reason = "before_host_turn"

        # --- trailing trims applied to all reels ---
        _trim_tail_question(r, tx_words, max_tail_words)
        _trim_tail_affirmation(r, tx_words, affirmations)

        # drop if too short after end adjustment
        if r.end - r.start < min_dur:
            first_words = " ".join(w.word for w in words_in_window(tx_words, r.start, r.end)[:8])
            disc.append({
                "id": r.id,
                "score": r.score,
                "reason": "interview_snap_too_short",
                "first_words": first_words,
            })
            continue

        # --- start rule: include preceding host question (non-merged only) ---
        if not is_merged:
            r0_start = r.r0_start if r.r0_start is not None else r.start
            preceding = [
                (ts, te) for ts, te in host_turns
                if te <= r0_start and (r0_start - te) <= 8.0 and (te - ts) <= 12.0
            ]
            if preceding:
                closest = max(preceding, key=lambda x: x[1])
                r.start = closest[0]
                r.start_snap_reason = "host_question_included"

        kept.append(r)

    return kept, disc
