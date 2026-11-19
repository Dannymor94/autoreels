# M228 — Архитектурное решение: поэтапные, детерминированные исправления

**Статус:** PROPOSAL (не авторизован для кода до Sol M228 QA и arch review M230)  
**База:** `main@3c011e94263e16e5780936b4769d3490cd03b682`  
**PRODUCTION_DIFF=NONE**

---

## 1. Принципы проектирования

1. **Детерминизм прежде всего.** Каждое изменение должно давать одинаковый результат при одинаковом входе.
2. **Текстово-облачный пайплайн.** Никакой логики, зависящей от бинарных медиа-данных.
3. **Pydantic Manifest-контракт.** Все поля `Proposal` проходят финальный валидатор до записи в review.
4. **Content-based idempotency.** Одинаковый source_sha + config → одинаковый выход (нет UUID, нет wall-clock).
5. **Feature-flag off parity.** Когда `hook_clauses=false` / `context_start=false` и т. д. — поведение идентично текущему.
6. **Защита ручного отбора.** Любой `manual`-маркер сохраняется; автоматика не перезаписывает.
7. **Nonempty input, zero output = не успех.** `cmd_autocut` при нулевых предложениях → rc≠0.

---

## 2. Граница генерации и учёт seeds (#1, #9)

### Текущая проблема
- `used_seeds` / `taken` могут подавить eligible alternative (разрыв #1).
- `build_passage` прерывается на `overlong nxt` без попытки `prv` (#9a); достигает target на question, удаляет post-loop, ответ не посещается (#9b).
- Нет счётчиков попыток seeds; потери invisible до пула.

### Предлагаемая граница

```
propose() входит с ordered seeds:
  для каждого seed_unit:
    if seed_unit.id in used_seeds: счётчик SKIPPED++; continue
    clip = build_passage(seed_unit, ...)   # стабильные IDs
    if clip is None: счётчик NONE_BY_REASON[reason]++; continue
    ... context_start, overlap check ...
    pool.append(clip); счётчик ADDED++
  emit: {total_seeds, eligible, attempted, none_reasons, added}
```

**`build_passage` контракт (детали, не код):**
- При `overlong nxt` → продолжить цикл и пробовать `prv` eligible units, **не break**.
- После loop, если last unit = question → extend с первым available answer unit перед trim.
- Возвращать `(clip, reason)` вместо `None` — reason идёт в счётчик.
- Stable IDs: порядок units в clip детерминирован по `(t0, id)`.

**Инвариант Proposal:**
- `Proposal.duration >= min_sec` после context_start.
- Первый unit не является question (или explicit intro).
- Последний unit не является вопросом.
- Все `refers` ссылки удовлетворены в clip.

---

## 3. Единая финальная граница консистентности (#2, #4, #5, #6, #7, #8)

### Текущая проблема
- `context_start` может укоротить до < min_sec без повторной проверки (#5).
- t0/t1 смещения 0.4с/1.0с после alignment-корректировки (#6).
- `fix_open_end` / post-trim оставляет short piece (#8b).
- Body opener не проходит start-морфологические проверки (#2).
- `fit_rhythm` удаляет unit, refs не удовлетворены (#7).
- `select_global` принимает кандидата, который может позже тихо упасть (#4).

### Финальный валидатор (гипотеза — не код)

Единая точка входа перед записью Proposal в review:

```
validate_proposal(clip, params, alignment, prosody) -> Result:
  ПРОВЕРКИ (в порядке применения):
  1. duration >= min_sec                          # #5
  2. t0 == first word t0, t1 == last word t1      # #6 (если alignment есть)
  3. opener проходит start_strict/answer_start    # #2
  4. все refers clip-а удовлетворены              # #7
  5. нет question как last unit                   # #8a
  6. min(piece.sec) >= rhythm.min_piece_sec       # #8b (после trim)
  7. select_global конфликт пересматривается      # #4

  СЕМАНТИКА: проверки 1–6 — REJECT с reason (не repair без proof);
             repair только если есть явный neighbor-контракт;
             без repair → REJECTED с logged reason.
```

**Важные оговорки (гипотезы — не доказаны):**
- Repair для #8b (короткий хвост после trim) требует доказанного соседа. Пока NOT_VERIFIED → reject с reason, не тихий drop.
- Проверки, не имеющие CLI-доказательства (#6 с реальным media), помечаются `HYPOTHESIS` до M231 instrument.
- Не объявлять эти проверки "working" до CLI-подтверждения.

---

## 4. Минимальная проводка callback/flag (#3)

### Текущая проблема
`propose` вызывает `_hook_cands(clauses=None)`, игнорируя sentences-clauses.

### Решение

При `hook_clauses=true` и наличии clauses callback → передать в `_hook_cands`.

**Контракт feature-flag off:**
- `hook_clauses=false` → поведение идентично текущему (clauses=None).
- `hook_clauses=true` и clauses=None → как сейчас (graceful degradation, warning).
- `hook_clauses=true` и clauses=callback → передать; новое поведение.

Это минимальное изменение signature (`propose` получает `clauses` parameter).  
**Arch review M230 обязателен** перед правкой `propose`.

---

## 5. Observability-first для #11

### Добавить счётчики (не менять алгоритм)

```
Stage counters (machine-readable, в каждом propose call):
  eligible:     N
  attempted:    N  (прошли eligible + seed_punch gate)
  none_reasons: {too_short: N, no_neighbors: N, question_end: N, ...}
  pool_added:   N
  fill_added:   N  (weak-seed)
  selected:     N
  rejected_validator: N (с reason dict)
  accepted:     N
```

Вывести в stderr как JSON-line: `{"stage": "propose", "eligible": 2, "attempted": 2, "none_reasons": {"too_short": 1}, "pool_added": 1}`.

**`teaser_misses` выравнивание:**
Добавить `start_pause` и `clauses` параметры, реплицируя логику `_hook_cands`.  
Или рефакторить оба через shared helper (arch review M230).

**Weak-seed fill propose:**
Добавить `no_start`, `open_end` параметры; не выбрасывать rhythm_out.

---

## 6. #10 и #12 — без изменений

**#10 (`hook_judge_top=6`):** намеренный бюджет. Не менять до измеренного пользовательского эффекта (например, % сборок без hook при бюджете 6 vs 8).

**#12 (tie-break):** `reversed([60,60,60])` = тот же массив; перестановки ID не демонстрировали разный результат. Добавить `stable_sort_by(id)` при tie — только если owner показывает реальный failing case.

---

## 7. Граф зависимостей

```
M229 ─── FIX_NOW (не требует arch)
  ├── #1  used_seeds fallback
  ├── #2  body opener check
  ├── #5  min_sec re-check post context_start
  ├── #8a question-as-last fix
  └── #9a build_passage prv fallback

M230 ─── ARCH REVIEW (сильная модель)
  ├── #3  clauses wiring в propose
  ├── #7  refers validator
  ├── #8b trim repair semantics
  └── #9b answer-after-question в passage

M231 ─── INSTRUMENT_FIRST
  ├── #4  post-select fallback + счётчики
  ├── #6  t0/t1 alignment validator (с реальным media)
  └── #11 per-stage counters + teaser_misses align

M232+ ── по результатам M231 instrumentation
```

**Правило:** никакой M229-код до Sol PASS M228. Никакой M230-propose-код до arch review M230.

---

## 8. Контракты и инварианты (резюме)

| Инвариант | Проверяемое условие |
|-----------|---------------------|
| Proposal.duration ≥ min_sec | всегда, в финальном валидаторе |
| Proposal.t0 == first_word.t0 | если alignment присутствует |
| Proposal.t1 == last_word.t1 | если alignment присутствует |
| Last unit != question | финальный валидатор |
| All refers satisfied | финальный валидатор |
| Seed attempt → counted | propose счётчик |
| None reason → logged | build_passage возвращает reason |
| feature_flag=off → no behaviour change | каждый новый parameter |
| manual selection preserved | не трогать manual-маркеры |
| nonempty input + zero output → rc≠0 | cmd_autocut |
