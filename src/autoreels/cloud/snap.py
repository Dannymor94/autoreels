"""R4: подтяжка границ сегментов к ЗАВЕРШЕНИЮ МЫСЛИ (детерминированный слой).

LLM предлагает start/end приблизительно — часто в середине слова ИЛИ на полуфразе (клип
обрывается «на союзе», хотя до max_duration ещё много запаса). Здесь КОД тянет границы к
естественным границам мысли (инвариант проекта: LLM ранжирует/предлагает, финальные границы
ставит код):

- `end` → тянется ВПЕРЁД до завершения мысли, пока (end-start) < max_duration:
  завершение = конец предложения (пунктуация Whisper .!?…) ИЛИ длинная пауза
  (> `min_pause_for_phrase_end`) ИЛИ конец речи. Микропаузы (< `max_micro_pause`) и
  висячие слова (союз/предлог/вводное из `hanging_words`) концом НЕ считаются;
- мысль не влезла в max_duration → откат к ПОСЛЕДНЕЙ целой фразе в пределах лимита
  (лучше короче, но целое, чем длиннее и оборванное);
- `start` → к началу фразы рядом (после паузы), НЕ на висячем слове (сдвиг вперёд);
- нет подходящей границы в окне ±`window_sec` (для start) → границу не трогаем.

PySceneDetect намеренно НЕ используется: статичная камера, один непрерывный план, склеек
нет — детектить нечего. R4 здесь = snap к завершению мысли.
"""
from __future__ import annotations

import sys

from autoreels.core.models import Reel, Word

# START-snap fallback when a caller omits hanging_start_words. It must NOT be the (much longer) end
# list — that strips valid openers like «Если», «Когда», «Я» (the ee01883 regression). Mirrors the
# R0Config.hanging_start_words default so a caller with no config still gets the short, safe list.
_DEFAULT_HANGING_START = ["и", "а", "но", "поэтому", "потому"]
_warned_missing_start_words = False

# Символы конца предложения (Whisper на русском роняет часть пунктуации, но не всю — где
# есть, доверяем ей как самому сильному сигналу завершения мысли).
_SENTENCE_END = ".!?…"
# Пунктуация СЕРЕДИНЫ фразы: запятая/двоеточие/точка с запятой/тире. Слово с ней на конце —
# мысль ещё не закончена (надёжнее порога паузы: «осознавать, [1.1с] понимать»).
_MIDPHRASE_PUNCT = ",;:—–-"
# Padding: минимальный зазор до соседнего слова — хвост/заход не касаются чужой речи вплотную.
_PAD_EPS = 0.05
# Макс. отступ начала слова от конца предложения, при котором слово считается спилловером
# следующей фразы (втянуто snap-хвостом ~tail_sec=0.3), а не отдельным содержательным словом.
_PAD_SPILL_MAX = 0.4

# Multi-word connectives that leave the thought hanging — the LAST word alone may not be in
# hanging_words, but the final N words together signal "more is coming". Listed as tuples of
# cleaned (lowercased, punctuation-stripped) tokens. Includes sub-phrases so that after the
# innermost word is trimmed (e.g. "чтобы" from "для того чтобы") the phrase "для того" is
# also caught by the next loop iteration.
_HANGING_END_PHRASES: frozenset[tuple[str, ...]] = frozenset({
    ("потому", "что"),
    ("так", "как"),
    ("то", "есть"),
    ("для", "того", "чтобы"),
    ("для", "того"),
    ("в", "то", "время", "как"),
    ("в", "то", "время"),
})
_HANGING_PHRASE_MAXLEN: int = max(len(p) for p in _HANGING_END_PHRASES)


def _clean(word: str) -> str:
    """Слово без обрамляющей пунктуации, в нижнем регистре — для сверки с hanging_words."""
    return word.strip().strip(_SENTENCE_END + ",;:\"'»«()—–-").lower()


def _is_sentence_end(word: str) -> bool:
    """Слово завершает предложение (пунктуация Whisper: .!?… или многоточие)."""
    s = word.strip()
    return bool(s) and (s[-1] in _SENTENCE_END or s.endswith("..."))


def _ends_midphrase(word: str) -> bool:
    """Слово оканчивается пунктуацией СЕРЕДИНЫ фразы (запятая/двоеточие/тире/;) — не конец мысли."""
    s = word.strip()
    return bool(s) and s[-1] in _MIDPHRASE_PUNCT


def _is_hanging(word: str, hanging_words) -> bool:
    """Висячее слово (союз/предлог/вводное) — на нём мысль не завершают."""
    return _clean(word) in set(hanging_words)


def tail_is_hanging_phrase(word_strs: list[str]) -> bool:
    """True if the last N cleaned tokens of word_strs match a known multi-word hanging phrase."""
    for phrase in _HANGING_END_PHRASES:
        n = len(phrase)
        if len(word_strs) >= n:
            if tuple(_clean(w) for w in word_strs[-n:]) == phrase:
                return True
    return False


def _nearest_in_window(target: float, candidates: list[float], window_sec: float) -> float | None:
    """Ближайший кандидат к target в пределах ±window_sec, иначе None."""
    in_range = [c for c in candidates if abs(c - target) <= window_sec]
    return min(in_range, key=lambda c: abs(c - target)) if in_range else None


def _pause_word_ends(words: list[Word], pause_sec: float) -> list[float]:
    """Концы слов, за которыми пауза > pause_sec (или конец речи) — простые границы фраз.

    Примитив по одной паузе (без пунктуации/висячих) — переиспользует trim.py для отреза
    слишком длинного клипа к ближайшей паузе. Полный «конец мысли» — в _phrase_end_times."""
    ends: list[float] = []
    for i, w in enumerate(words):
        if i == len(words) - 1 or (words[i + 1].t0 - w.t1) > pause_sec:
            ends.append(w.t1)
    return ends


def _phrase_end_times(words: list[Word], *, min_pause: float, max_micro_pause: float,
                      hanging_words) -> list[float]:
    """Времена концов слов, на которых ЗАВЕРШАЕТСЯ мысль.

    Конец предложения (пунктуация) — всегда (пунктуация сильнее висячести). Иначе — длинная
    пауза (> min_pause) или конец речи, но только если слово не висячее. Микропаузы
    (<= max_micro_pause) концом не считаются никогда.
    """
    ends: list[float] = []
    n = len(words)
    for i, w in enumerate(words):
        if _is_sentence_end(w.word):
            ends.append(w.t1)
            continue
        # Запятая/двоеточие/тире на конце → мысль продолжается, паузу игнорируем (любой длины).
        if _ends_midphrase(w.word):
            continue
        is_last = i == n - 1
        gap = None if is_last else (words[i + 1].t0 - w.t1)
        if gap is not None and gap <= max_micro_pause:
            continue  # микропауза внутри фразы — не конец
        long_pause_or_end = is_last or (gap is not None and gap > min_pause)
        if long_pause_or_end and not _is_hanging(w.word, hanging_words):
            ends.append(w.t1)
    return ends


def _phrase_start_indices(words: list[Word], *, min_pause: float) -> list[int]:
    """Индексы слов — начал фраз. Начало = первое слово; ИЛИ предыдущее слово закончило
    предложение (.!?); ИЛИ длинная пауза (> min_pause), но НЕ после запятой (после запятой —
    продолжение фразы, не начало: «он сказал, [пауза] что…» — не начинать с «что»)."""
    starts: list[int] = []
    for i, w in enumerate(words):
        if i == 0:
            starts.append(i)
            continue
        prev = words[i - 1]
        if _is_sentence_end(prev.word):
            starts.append(i)
        elif (w.t0 - prev.t1) > min_pause and not _ends_midphrase(prev.word):
            starts.append(i)
    return starts


def _relaxed_end(words: list[Word], *, start: float, end: float, limit: float, window_sec: float,
                 max_micro_pause: float, hanging_words) -> float | None:
    """Фолбэк, когда в сегменте НЕТ строгого завершения мысли (паузы ≥ min_pause / пунктуации).

    Иерархия (мягче, но НИКОГДА не на висячем слове / после запятой, если есть альтернатива):
      b) последняя пауза ≥ max_micro_pause (0.4с, не 1.5) на не-висячем/не-после-запятой слове;
      c) иначе — не-висячее слово перед МАКСИМАЛЬНОЙ паузой в сегменте;
      d) иначе — последнее не-висячее слово; совсем нет — ближайший конец слова (не полуслово).
    """
    seg = [(i, w) for i, w in enumerate(words) if start < w.t1 <= limit]
    if not seg:
        return None

    # (b) те же правила завершённости, но порог паузы = max_micro_pause вместо min_pause.
    soft = _phrase_end_times(words, min_pause=max_micro_pause, max_micro_pause=max_micro_pause,
                             hanging_words=hanging_words)
    forward = [t for t in soft if t >= end - window_sec and start < t <= limit]
    if forward:
        return min(forward)
    within = [t for t in soft if start < t <= limit]
    if within:
        return max(within)

    # (c) не-висячее слово перед максимальной паузой в сегменте.
    best_t, best_gap = None, -1.0
    for i, w in seg:
        gap = (words[i + 1].t0 - w.t1) if i + 1 < len(words) else None
        if gap is None or _ends_midphrase(w.word) or _is_hanging(w.word, hanging_words):
            continue
        if gap > best_gap:
            best_gap, best_t = gap, w.t1
    if best_t is not None:
        return best_t

    # (d) последнее не-висячее/не-после-запятой слово; иначе ближайший конец слова.
    clean = [w.t1 for _, w in seg if not _is_hanging(w.word, hanging_words) and not _ends_midphrase(w.word)]
    if clean:
        return _nearest_in_window(end, clean, window_sec) or max(clean)
    return _nearest_in_window(end, [w.t1 for _, w in seg], window_sec)


def _sentence_end_times(words: list[Word]) -> list[float]:
    """Времена концов слов с пунктуацией конца предложения (.!?…) — «чистые границы»."""
    return [w.t1 for w in words if _is_sentence_end(w.word)]


def _prefer_longer_end(chosen: float, *, start: float, limit: float, tail_sec: float,
                       words: list[Word], ratio: float, max_extra: int) -> float:
    """Пока клип (chosen+хвост) заметно короче лимита (< ratio·max_duration) — продлевать до
    СЛЕДУЮЩЕЙ чистой границы предложения (по одной), максимум на `max_extra` предложений.
    Пошагово с пере-проверкой ratio: как только клип дотянул до ratio·max_duration — стоп
    (не тянем до упора). Грамматически конец бывает раньше, чем спикер закончил мысль."""
    if ratio <= 0 or max_extra <= 0:
        return chosen
    sent_ends = sorted(_sentence_end_times(words))
    extra = 0
    while extra < max_extra and (chosen + tail_sec - start) < ratio * (limit - start):
        later = [t for t in sent_ends if t > chosen + 1e-6 and t <= limit]
        if not later:
            break
        chosen = later[0]        # следующая чистая граница
        extra += 1
    return chosen


def _snap_end(end: float, start: float, words: list[Word], *, tail_sec: float, window_sec: float,
              max_duration: float, min_pause: float, max_micro_pause: float,
              hanging_words, prefer_longer_below_ratio: float = 0.0,
              max_extra_sentences: int = 0) -> float | None:
    """Новый end: тянуть вперёд до завершения мысли в пределах max_duration; не влезло —
    откат к последней целой фразе; совсем нет завершений рядом → мягкая иерархия фолбэка
    (_relaxed_end) — конец предложения / пауза ≥0.4с / не-висячее слово, НЕ полуслово."""
    limit = start + max_duration
    ends = _phrase_end_times(words, min_pause=min_pause, max_micro_pause=max_micro_pause,
                             hanging_words=hanging_words)

    # Вперёд-first: ближайшее завершение мысли >= (end - окно), влезающее в лимит.
    # Окно назад — чтобы подхватить завершение, которое чуть раньше предложенного конца
    # (LLM промахнулся вперёд); вперёд тянем без окна — до конца мысли, пока есть запас.
    forward = [t for t in ends if t >= end - window_sec and start < t <= limit]
    if forward:
        chosen = min(forward)
    else:
        # Мысль не завершается до max_duration → откат к последней целой фразе в лимите.
        within = [t for t in ends if start < t <= limit]
        if within:
            chosen = max(within)
        else:
            # Нет строгих завершений — мягкая иерархия (не садиться на висячее/после запятой).
            chosen = _relaxed_end(words, start=start, end=end, limit=limit, window_sec=window_sec,
                                  max_micro_pause=max_micro_pause, hanging_words=hanging_words)
            if chosen is None:
                return None
    new_end = min(chosen + tail_sec, limit)
    return new_end if new_end > start else None


def _trim_start(
    start: float,
    end: float,
    max_duration: float,
    words: list[Word],
    pause_sec: float,
) -> tuple[float, str]:
    """Move start forward so (end - new_start) ≤ max_duration.

    Hierarchy:
    1. First word whose preceding word ends with sentence-terminal (. ? !) at t0 ≥ end-max_duration.
    2. First word after a pause > pause_sec at t0 ≥ end-max_duration.
    3. Hard cut at (end - max_duration).

    Returns (new_start, reason): reason in ("sentence", "pause", "hard_cut").
    """
    floor = end - max_duration
    in_window = [w for w in words if w.t0 >= start and w.t0 <= end]

    for i, w in enumerate(in_window):
        if w.t0 < floor or i == 0:
            continue
        if _is_sentence_end(in_window[i - 1].word):
            return w.t0, "sentence"

    for i, w in enumerate(in_window):
        if w.t0 < floor or i == 0:
            continue
        if (w.t0 - in_window[i - 1].t1) > pause_sec:
            return w.t0, "pause"

    return floor, "hard_cut"


def _snap_end_punctuation_first(
    r0_end: float,
    start: float,
    words: list[Word],
    *,
    max_end_search_sec: float,
    tail_sec: float,
    min_pause: float,
    max_micro_pause: float,
    hanging_words,
    max_duration: float,
) -> tuple[float | None, str]:
    """Punctuation-first end snap anchored on r0_end.

    Precondition: caller has already applied start-trim so that start + max_duration >= r0_end.
    End is NEVER moved backwards (no "max_duration" reason). Candidates that would exceed
    hard_limit are skipped; if none fit, returns (None, "no_end").

    Returns (new_end, reason):
      "sentence"      — first sentence-terminal word at/after r0_end within hard_limit
      "no_punctuation"— no sentence-terminal in window; pause-based fallback used
      "no_end"        — no acceptable end at/after r0_end; end stays at r0_end, caller adds
                        "unpunctuated" flag
    """
    hard_limit = start + max_duration
    search_cap = min(r0_end + max_end_search_sec, hard_limit)

    # 1. Punctuation-first: first sentence-terminal word at/after r0_end, within hard_limit.
    sentence_ends = sorted(
        w.t1 for w in words
        if w.t1 >= r0_end and w.t1 <= search_cap and _is_sentence_end(w.word)
    )
    for t in sentence_ends:
        if t + tail_sec <= hard_limit:
            return t + tail_sec, "sentence"

    # 2. Pause-based fallback within search window (no reachable punctuation found).
    phrase_ends = _phrase_end_times(words, min_pause=min_pause, max_micro_pause=max_micro_pause,
                                    hanging_words=hanging_words)
    within_cap = sorted(t for t in phrase_ends if t >= r0_end and t <= search_cap)
    for t in within_cap:
        if t + tail_sec <= hard_limit:
            return t + tail_sec, "no_punctuation"

    # 3. No good end at/after r0_end in window.
    return None, "no_end"


def _snap_start(start: float, end: float, words: list[Word], *, window_sec: float,
                min_pause: float, hanging_start_words) -> float | None:
    """Новый start: к началу фразы рядом (после паузы), НЕ на висячем НАЧАЛЬНОМ слове (сдвиг вперёд).

    `hanging_start_words` — короткий список слов-отсылок, с которых клип не должен начинаться
    (не end-список: «Если…»/«Когда…»/«Я…» — нормальные начала предложения)."""
    start_idx = _phrase_start_indices(words, min_pause=min_pause)
    cands = [words[i].t0 for i in start_idx]
    target = _nearest_in_window(start, cands, window_sec)
    if target is None:
        target = _nearest_in_window(start, [w.t0 for w in words], window_sec)
    if target is None:
        return None
    # Не начинать с висячего слова: сдвинуть вперёд, пока слово-начало не «висячее».
    idx = next((i for i, w in enumerate(words) if abs(w.t0 - target) < 1e-6), None)
    if idx is not None:
        while idx < len(words) and words[idx].t0 < end and _is_hanging(words[idx].word, hanging_start_words):
            idx += 1
        if idx < len(words):
            target = words[idx].t0
    return target if target < end else None


def try_rescue_clip(
    r: Reel,
    words: list[Word],
    *,
    min_duration: float,
    max_duration: float,
    min_pause: float,
    max_micro_pause: float,
    hanging_words,
) -> bool:
    """Расширить схлопнутый клип до ближайшей границы мысли. Мутирует r.end.

    True → r.end перенесён к ближайшему концу фразы, (r.end - r.start) >= min_duration.
    False → подходящего конца в пределах max_duration не нашлось, r не изменён.

    Порядок поиска:
      1. Строгие концы мысли (пунктуация / пауза > min_pause) — не на висячем слове;
      2. Мягкие концы (пауза > max_micro_pause) — если строгих нет.
    start не двигается: началo уже snap'нуто, отодвигать его назад рискованно.
    """
    limit = r.start + max_duration

    # Строгие концы мысли (тот же критерий, что snap_end)
    strict = _phrase_end_times(words, min_pause=min_pause, max_micro_pause=max_micro_pause,
                               hanging_words=hanging_words)
    for t in sorted(t for t in strict if t > r.end and t <= limit):
        if t - r.start >= min_duration:
            r.end = t
            return True

    # Мягкие концы (пауза > max_micro_pause — ниже порога «конца мысли», но выше микропаузы)
    relaxed = _phrase_end_times(words, min_pause=max_micro_pause, max_micro_pause=max_micro_pause,
                                hanging_words=hanging_words)
    for t in sorted(t for t in relaxed if t > r.end and t <= limit):
        if t - r.start >= min_duration:
            r.end = t
            return True

    return False


def snap_segments(reels: list[Reel], words: list[Word], *, tail_sec: float, window_sec: float,
                  max_duration: float, min_pause_for_phrase_end: float, max_micro_pause: float,
                  hanging_words, hanging_start_words=None, prefer_longer_below_ratio: float = 0.0,
                  max_extra_sentences: int = 0, max_end_search_sec: float | None = None,
                  min_clip_duration: float | None = None) -> None:
    """Подтянуть start/end каждого reel к завершению мысли (мутирует на месте).

    Пустой `words` → границы не трогаем. Порядок в пайплайне: snap → padding → trim.

    `hanging_words` решает КОНЕЦ (клип не заканчивается на висячем слове). START-подтяжка
    использует `hanging_start_words` — короткий список слов-отсылок, с которых клип не должен
    начинаться; None → встроенный короткий список `_DEFAULT_HANGING_START` (НЕ end-список — тот
    срезал бы «Если»/«Когда»/«Я» из первой фразы, баг ee01883), с одноразовым предупреждением.

    Если max_end_search_sec задан и r.r0_end не None — использует punctuation-first snap
    (конец предложения в окне r0_end + max_end_search_sec, без prefer_longer).
    Пишет r.end_drift_sec и r.end_snap_reason для каждого reel.

    min_clip_duration: клипы короче порога получают флаг "too_short".
    """
    if not words:
        return
    if hanging_start_words is None:
        # Fall back to the built-in SHORT list, never the end list (which would drop «Если»/«Когда»/
        # «Я» from a clip's first sentence — the ee01883 bug). Warn once so a stale config is noticed.
        global _warned_missing_start_words
        if not _warned_missing_start_words:
            print("  warning: hanging_start_words not provided — using built-in short list "
                  f"{_DEFAULT_HANGING_START}; add the key to config/r0.yaml to silence this",
                  file=sys.stderr)
            _warned_missing_start_words = True
        hanging_start_words = _DEFAULT_HANGING_START
    for r in reels:
        # An explicit review start (s:N) is the reviewer's exact choice — snap must land on that
        # sentence's first word, not the nearest phrase boundary, or it skips the intended word.
        if not getattr(r, "_explicit_start", False):
            new_start = _snap_start(r.start, r.end, words, window_sec=window_sec,
                                    min_pause=min_pause_for_phrase_end,
                                    hanging_start_words=hanging_start_words)
            if new_start is not None:
                r.start = new_start

        if max_end_search_sec is not None and r.r0_end is not None:
            # If clip already exceeds max_duration before snap, trim START first so that
            # end snap sees hard_limit >= r0_end and never needs to move end backwards.
            orig_start = r.start
            if r.r0_end > r.start + max_duration:
                window_words = [w for w in words
                                if w.t0 >= r.start - 0.1 and w.t1 <= r.r0_end + 0.1]
                new_start, snap_reason = _trim_start(
                    r.start, r.r0_end, max_duration, window_words, min_pause_for_phrase_end
                )
                r.start = new_start
                r.start_drift_sec = round(new_start - orig_start, 3)
                r.start_snap_reason = snap_reason

            new_end, reason = _snap_end_punctuation_first(
                r.r0_end, r.start, words,
                max_end_search_sec=max_end_search_sec,
                tail_sec=tail_sec,
                min_pause=min_pause_for_phrase_end,
                max_micro_pause=max_micro_pause,
                hanging_words=hanging_words,
                max_duration=max_duration,
            )
            r.end_snap_reason = reason
            if new_end is None:
                # No acceptable end at/after r0_end; keep end at r0_end, mark unpunctuated.
                # Duration check below sets "too_short" if needed.
                if "unpunctuated" not in r.flags:
                    r.flags.append("unpunctuated")
            else:
                r.end = new_end
                assert reason != "sentence" or r.end >= r.r0_end - 1e-6, (
                    f"invariant violated: reason='sentence' but end={r.end} < r0_end={r.r0_end}"
                )
                if reason == "no_punctuation" and "unpunctuated" not in r.flags:
                    r.flags.append("unpunctuated")
            r.end_drift_sec = r.end - r.r0_end
        else:
            new_end = _snap_end(r.end, r.start, words, tail_sec=tail_sec, window_sec=window_sec,
                                max_duration=max_duration, min_pause=min_pause_for_phrase_end,
                                max_micro_pause=max_micro_pause, hanging_words=hanging_words,
                                prefer_longer_below_ratio=prefer_longer_below_ratio,
                                max_extra_sentences=max_extra_sentences)
            if new_end is not None:
                r.end = new_end
            if r.r0_end is not None:
                r.end_drift_sec = r.end - r.r0_end

        if min_clip_duration is not None and (r.end - r.start) < min_clip_duration:
            if "too_short" not in r.flags:
                r.flags.append("too_short")


def apply_padding(
    reels: list[Reel],
    words: list[Word],
    *,
    tail_pad_sec: float,
    lead_pad_sec: float,
    max_duration: float,
    video_duration: float | None = None,
    hanging_words=None,
) -> None:
    """Добавить «воздух» до первого и после последнего слова клипа (мутирует на месте).

    Запускается ПОСЛЕ snap_segments. Находит первое/последнее слово в диапазоне [start, end],
    раздвигает границы: start -= lead_pad_sec, end += tail_pad_sec.
    Субтитры не затрагиваются — область паддинга это тишина/пауза без слов.

    CLAMP по соседним словам: хвост НЕ заезжает в начало следующего слова
    (`new_end ≤ next_word.t0 − _PAD_EPS`), заход НЕ заезжает в конец предыдущего
    (`new_start ≥ prev_word.t1 + _PAD_EPS`). Так фиксированные 0.7с «воздуха» никогда не
    втягивают речь соседней фразы (межфразовая пауза Whisper часто < tail_pad → был обрыв).
    Нет соседнего слова (край речи) — паддинг как есть. Заменяет узкий spillover-триммер.

    Ограничения:
    - start >= 0
    - end - start <= max_duration
    - end <= video_duration (если задана)
    """
    hanging_words = hanging_words or []
    for r in reels:
        idxs = [i for i, w in enumerate(words) if w.t0 >= r.start and w.t0 < r.end]
        if not idxs:
            continue

        # (1) Спилловер СЛЕДУЮЩЕЙ фразы за концом предложения. Если в клипе есть конец
        # предложения, а всё после него — короткий незавершённый фрагмент (слова начинаются
        # в пределах _PAD_SPILL_MAX после «.», среди них нет своего конца предложения) — это
        # начало следующей мысли, втянутое snap-хвостом («…психосоматика. И вот мы»). Обрезаем
        # до конца предложения: лучше 0.2с тишины, чем первое слово чужой фразы. Триммер (2)
        # ловит только ПОСЛЕДНЕЕ слово и на «…И вот мы» стопается (мы — обычное слово).
        sent_pos = [k for k, i in enumerate(idxs) if _is_sentence_end(words[i].word)]
        if sent_pos:
            last_se = sent_pos[-1]
            tail = idxs[last_se + 1:]
            se_t1 = words[idxs[last_se]].t1
            if (tail
                    and not any(_is_sentence_end(words[i].word) for i in tail)
                    and all(words[i].t0 - se_t1 <= _PAD_SPILL_MAX for i in tail)):
                idxs = idxs[:last_se + 1]

        # (2) Хвостовые слова, на которых клип не должен заканчиваться: висячее, с запятой,
        # или сразу за концом предложения. Пока не упрёмся в содержательный конец.
        # Пропускаем для явного e: (reviewer's choice — warn, not trim).
        if not getattr(r, "_explicit_end", False):
            while len(idxs) >= 2:
                li, pi = idxs[-1], idxs[-2]
                if _is_sentence_end(words[li].word):
                    break   # само слово завершает предложение — чистый конец, не срезаем
                tail_ws = [words[j].word for j in idxs[-_HANGING_PHRASE_MAXLEN:]]
                if (_is_sentence_end(words[pi].word)
                        or _is_hanging(words[li].word, hanging_words)
                        or _ends_midphrase(words[li].word)
                        or tail_is_hanging_phrase(tail_ws)):
                    idxs.pop()
                else:
                    break

        fi, la = idxs[0], idxs[-1]
        first_word, last_word = words[fi], words[la]

        # Заход: воздух до первого слова, но не в конец предыдущего слова (по индексу).
        new_start = max(0.0, first_word.t0 - lead_pad_sec)
        if fi > 0:
            new_start = max(new_start, words[fi - 1].t1 + _PAD_EPS)
        new_start = min(new_start, first_word.t0)          # не резать само первое слово

        # Хвост: воздух после последнего слова, но не в начало следующего (по индексу — ловит
        # и приклеенное впритык слово, у которого gap ≈ 0).
        new_end = last_word.t1 + tail_pad_sec
        if la + 1 < len(words):
            new_end = min(new_end, words[la + 1].t0 - _PAD_EPS)
        new_end = max(new_end, last_word.t1)               # не резать само последнее слово
        # Overlapping-timestamp guard: words after `la` in list order may have t0 < new_end
        # (Whisper places them there despite coming later in the utterance). Clamp to exclude
        # them when their t0 > last_word.t0 (i.e., we can push end below their t0 without
        # losing last_word from the subtitle window, which uses w.t0 < end).
        for k in range(la + 1, len(words)):
            if words[k].t0 >= new_end:
                break
            if words[k].t0 > last_word.t0:
                new_end = min(new_end, words[k].t0 - _PAD_EPS)
                break
        new_end = max(new_end, last_word.t0 + _PAD_EPS)   # keep last_word in window

        new_end = min(new_end, new_start + max_duration)
        if video_duration is not None:
            new_end = min(new_end, video_duration)

        r.start = new_start
        r.end = new_end

        # Record the nearest next-speech boundary for the render tier.  When the
        # overlapping-timestamp guard clamped new_end below last_word.t1, Whisper's
        # t1 will overshoot into the next sentence; the render's clean-tail extension
        # must not cross this boundary.  Set whenever the next word falls inside the
        # potential tail window (last_word.t1 + tail_pad_sec).
        _next_speech = next(
            (words[k] for k in range(la + 1, len(words)) if words[k].t0 > last_word.t0),
            None,
        )
        if _next_speech is not None and _next_speech.t0 < last_word.t1 + tail_pad_sec + 0.3:
            r.tail_next_word_start = _next_speech.t0


def trim_hanging_subtitles(reels: list[Reel], *, hanging_words) -> None:
    """Remove trailing hanging words from reel.subtitles (mutates in place).

    Handles the case where overlapping Whisper timestamps include a hanging word
    in the subtitle window even though apply_padding excluded it from idxs.
    Sets end_snap_reason='sentence_trimmed_hanging' when any trimming occurs.
    """
    hw_set = set(hanging_words or [])
    for r in reels:
        if not r.subtitles or not hw_set:
            continue
        trimmed = False
        while r.subtitles and (
                _clean(r.subtitles[-1].word) in hw_set
                or tail_is_hanging_phrase([s.word for s in r.subtitles[-_HANGING_PHRASE_MAXLEN:]])):
            r.subtitles.pop()
            trimmed = True
        if trimmed and r.end_snap_reason in ("sentence", "no_punctuation"):
            r.end_snap_reason = "sentence_trimmed_hanging"


# --------------------------------------------------------------------------- final speech density
# Fix 1 (video review): density is computed on the FINISHED clip — after merges, snap, padding —
# because a clip assembled from two blocks across a long pause passes the block-level check yet
# plays with dead air on screen (r08: 54.7s clip, 72.7% speech, one 14.6s interviewer pause).

def clip_speech_density(start: float, end: float, words: list[Word]) -> float:
    """Doля времени клипа, занятая речью: sum(overlap слова с [start,end]) / (end-start).

    1.0 — сплошная речь; ниже — паузы/тишина внутри клипа. Пустой/нулевой клип → 0.0.
    """
    dur = end - start
    if dur <= 0:
        return 0.0
    speech = 0.0
    for w in words:
        lo, hi = max(start, w.t0), min(end, w.t1)
        if hi > lo:
            speech += hi - lo
    return min(1.0, speech / dur)


def split_clip_at_largest_gap(
    start: float, end: float, words: list[Word], *,
    min_gap: float, min_duration: float, max_duration: float,
) -> tuple[float, float] | None:
    """Срезать клип по САМОЙ длинной внутренней паузе между словами, вернуть более длинную половину.

    Возвращает (new_start, new_end) более длинной половины, если:
      - есть пауза между соседними словами длиннее `min_gap`, и
      - длиннейшая половина укладывается в [min_duration, max_duration].
    Иначе None (клип не спасти срезом — вызывающий его снимет). Границы половин выравнены по
    словам (левая кончается на t1 слова перед паузой, правая начинается с t0 слова после),
    исходные start/end (с паддингом) сохраняются на внешних краях.
    """
    win = [w for w in words if w.t1 > start and w.t0 < end]
    if len(win) < 2:
        return None
    best_k, best_gap = None, min_gap
    for k in range(1, len(win)):
        gap = win[k].t0 - win[k - 1].t1
        if gap > best_gap:
            best_gap, best_k = gap, k
    if best_k is None:
        return None                       # ни одной паузы длиннее порога — резать негде
    left = (start, win[best_k - 1].t1)
    right = (win[best_k].t0, end)
    longer = left if (left[1] - left[0]) >= (right[1] - right[0]) else right
    dur = longer[1] - longer[0]
    if min_duration <= dur <= max_duration:
        return longer
    return None
