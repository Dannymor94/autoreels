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

from autoreels.core.models import Reel, Word

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
    (_relaxed_end) — конец предложения / пауза ≥0.4с / не-висячее слово, НЕ полуслово.

    prefer_longer: короткий клип с запасом времени продлевается до следующей чистой границы."""
    limit = start + max_duration
    ends = _phrase_end_times(words, min_pause=min_pause, max_micro_pause=max_micro_pause,
                             hanging_words=hanging_words)

    # Вперёд-first: ближайшее завершение мысли >= (end - окно), влезающее в лимит.
    # Окно назад — чтобы подхватить завершение, которое чуть раньше предложенного конца
    # (LLM промахнулся вперёд); вперёд тянем без окна — до конца мысли, пока есть запас.
    forward = [t for t in ends if t >= end - window_sec and start < t <= limit]
    if forward:
        chosen = min(forward)
        # Клип грамматически завершён, но короткий и есть запас → тянуть до след. чистой границы.
        chosen = _prefer_longer_end(chosen, start=start, limit=limit, tail_sec=tail_sec,
                                    words=words, ratio=prefer_longer_below_ratio,
                                    max_extra=max_extra_sentences)
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


def _snap_start(start: float, end: float, words: list[Word], *, window_sec: float,
                min_pause: float, hanging_words) -> float | None:
    """Новый start: к началу фразы рядом (после паузы), НЕ на висячем слове (сдвиг вперёд)."""
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
        while idx < len(words) and words[idx].t0 < end and _is_hanging(words[idx].word, hanging_words):
            idx += 1
        if idx < len(words):
            target = words[idx].t0
    return target if target < end else None


def snap_segments(reels: list[Reel], words: list[Word], *, tail_sec: float, window_sec: float,
                  max_duration: float, min_pause_for_phrase_end: float, max_micro_pause: float,
                  hanging_words, prefer_longer_below_ratio: float = 0.0,
                  max_extra_sentences: int = 0) -> None:
    """Подтянуть start/end каждого reel к завершению мысли (мутирует на месте).

    Пустой `words` → границы не трогаем. Порядок в пайплайне: snap → padding → trim.
    prefer_longer_*: короткий грамматически-завершённый клип продлевается до след. чистой границы.
    """
    if not words:
        return
    for r in reels:
        new_start = _snap_start(r.start, r.end, words, window_sec=window_sec,
                                min_pause=min_pause_for_phrase_end, hanging_words=hanging_words)
        if new_start is not None:
            r.start = new_start
        new_end = _snap_end(r.end, r.start, words, tail_sec=tail_sec, window_sec=window_sec,
                            max_duration=max_duration, min_pause=min_pause_for_phrase_end,
                            max_micro_pause=max_micro_pause, hanging_words=hanging_words,
                            prefer_longer_below_ratio=prefer_longer_below_ratio,
                            max_extra_sentences=max_extra_sentences)
        if new_end is not None:
            r.end = new_end


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
        while len(idxs) >= 2:
            li, pi = idxs[-1], idxs[-2]
            if _is_sentence_end(words[li].word):
                break   # само слово завершает предложение — чистый конец, не срезаем
            if (_is_sentence_end(words[pi].word)
                    or _is_hanging(words[li].word, hanging_words)
                    or _ends_midphrase(words[li].word)):
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

        new_end = min(new_end, new_start + max_duration)
        if video_duration is not None:
            new_end = min(new_end, video_duration)

        r.start = new_start
        r.end = new_end
