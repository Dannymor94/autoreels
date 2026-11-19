# M228 — Архитектурное решение: поэтапные, детерминированные исправления (R2)

**Статус:** PROPOSAL · требует Sol M228 QA и M230 arch review до любого кода  
**Base:** `main@3c011e94263e16e5780936b4769d3490cd03b682`  
**PRODUCTION_DIFF=NONE**  
**M229_CODE_GO=NO** — реализация не авторизована до Sol M228 PASS + явного GO-решения координатора + M230 arch review

---

## 1. Принципы проектирования

1. **Детерминизм прежде всего.** Каждое изменение должно давать одинаковый результат при одинаковом входе.
2. **Текстово-облачный пайплайн.** Никакой логики, зависящей от бинарных медиа-данных.
3. **Pydantic Manifest-контракт.** Все поля `Proposal` проходят финальный валидатор до записи в review.
4. **Content-based idempotency.** Одинаковый source_sha + config → одинаковый выход (нет UUID, нет wall-clock).
5. **Feature-flag off parity.** Когда `hook_clauses=false` / `context_start=false` и т. д. — поведение идентично текущему.
6. **Защита ручного отбора.** Любой `manual`-маркер сохраняется; автоматика не перезаписывает.
7. **Nonempty input, zero output = не успех.** `cmd_autocut` при нулевых предложениях → rc≠0.
8. **Question-led loop — поддерживаемый путь.** Клип, начинающийся с `role=question`, является законным в question-loop конструкции (`autocut.py:1183,1270,1298`). Запрет только на вопрос как **последний** unit (#8a).

---

## 2. Граница генерации и учёт seeds (#1, #9) — PROPOSAL за M230 arch gate

### Текущая проблема
- `used_seeds` / `taken` могут подавить eligible alternative (разрыв #1, `autocut.py:1175,1262–1264`).
- `build_passage` прерывается на `overlong nxt` без попытки `prv` (#9a); достигает target на question, удаляет post-loop, ответ не посещается (#9b).
- Нет счётчиков попыток seeds; потери invisible до пула.

### Предлагаемая граница (гипотеза — не финальный дизайн)

Различать **перечисление кандидатов** (что входит в пул для рассмотрения) и **финальный отбор** (что принимается из пула с enforcement overlap/dedup):

```
propose() входит с ordered seeds:
  для каждого seed_unit:
    if seed_unit.id in used_seeds:
      счётчик SKIPPED++
      # HYPOTHESIS: consider bounded re-attempt for independently eligible seeds
      # Arch gate: when is re-attempt safe? What is the stopping bound?
      continue
    clip = build_passage(seed_unit, ...)   # стабильные IDs по (t0, id)
    if clip is None:
      счётчик NONE_BY_REASON[reason]++
      continue
    ... context_start, overlap check at SELECTION time ...
    pool.append(clip); счётчик ADDED++
  emit: {total_seeds, eligible, attempted, none_reasons, added}
```

**Контракт восстановления #1 (ожидает M230 arch approval):**
- Bounded альтернативное перечисление: попытка не более N независимо eligible seeds даже если уже в `used_seeds`.
- Stable identity: порядок units в clip детерминирован по `(t0, id)`.
- Dedup/overlap: финальное перекрытие clips по фактическим units проверяется при **selection** из пула, не при перечислении.
- Intentional overlap prohibition сохраняется: финальные принятые клипы не должны пересекаться по units.
- Stopping condition: ограничение попыток по pool size или максимальному числу альтернатив.
- **Не утверждать** поздний downstream rejection в реальных медиа — NOT_REPRODUCED.

**Регрессионный контракт #1:**
- Fail-before: u2 (eligible alone, non-overlapping с u1 по units) не попадает в пул при текущем коде.
- Pass-after: u2 достигает пула; финальные принятые клипы не содержат одни и те же units.
- Тест не должен доказывать bypass overlap — он доказывает bounded enumeration.

**`build_passage` #9a — прv-fallback (гипотеза):**
- При `overlong nxt` → продолжить цикл и пробовать `prv` eligible units, **не break**.
- Это изменение в теле `build_passage`, не в `propose` напрямую, но вызывается из propose body.
- Requires M230 arch review.

**`build_passage` #9b — answer-after-question (гипотеза, только за arch gate):**
- После удаления question unit post-loop — рассмотреть доступный answer unit.
- **Не имплементировать** без arch review: семантика «всегда ли добавлять answer» — продуктовое решение.
- Дизайн `build_passage` возвращает `None` или `clip` — изменение сигнатуры на `(clip, reason)` является гипотезой и также требует arch review.

**Инвариант Proposal (финальный валидатор — гипотеза):**
- `Proposal.duration >= min_sec` после context_start.
- Последний unit не является вопросом (кроме explicit question-loop).
- Все `refers` ссылки удовлетворены в clip.
- Примечание: первый unit **может быть** question в поддерживаемой question-loop конструкции.

---

## 3. Финальная граница консистентности (#2, #4, #5, #6, #7, #8) — PROPOSAL за M230 arch gate

### Текущие проблемы
- `context_start` может укоротить до < min_sec без повторной проверки (#5).
- t0/t1 смещения 0.4с/1.0с после alignment-корректировки (#6) — не доказано в реальных медиа.
- `fix_open_end` / post-trim оставляет short piece (#8b).
- Body opener не проходит start-морфологические проверки (#2).
- `fit_rhythm` удаляет unit, refs не удовлетворены (#7).
- `select_global` принимает кандидата, который может позже тихо упасть (#4).

### Финальный валидатор (гипотеза — не код; pending M230 arch design)

```
validate_proposal(clip, params, alignment, prosody) -> Result:
  ПРОВЕРКИ (в порядке применения, все как REJECT с reason — не auto-repair без arch approval):
  1. duration >= min_sec                          # #5
  2. t0/t1 delta-лог (observational в M231)       # #6 — HYPOTHESIS до M231 instr.
  3. opener проходит start_strict/answer_start    # #2
  4. все refers clip-а удовлетворены              # #7
  5. нет question как ПОСЛЕДНИЙ unit              # #8a (question-first законен)
  6. min(piece.sec) >= rhythm.min_piece_sec       # #8b — fail-closed, see below
  7. post-select counter                          # #4 — counter только в M231

  СЕМАНТИКА: REJECT с logged reason (не тихий drop);
             repair только если есть arch-approved neighbor-контракт;
             без доказанного repair → fail-closed.
```

**#8b — repair semantics (fail-closed, NOT_VERIFIED):**  
Если после trim возникает кусок < min_piece_sec и нет доказанного legal repair-соседа — `REJECTED` с reason. Repair добавляется только после arch-approved neighbor-контракта (M230). **Не обещать recovery** без доказательства соседа.

**#6 — alignment validator (HYPOTHESIS до M231):**  
t0/t1 валидация — гипотеза, не внедряется до M231 наблюдения delta-лога на синтетике. Реальный playback mismatch NOT_REPRODUCED.

---

## 4. Минимальная проводка callback/flag (#3) — PROPOSAL за M230 arch gate

### Текущая проблема
`propose` вызывает `_hook_cands(clauses=None)`, игнорируя sentences-clauses (`autocut.py` — 6 вызовов).

### Гипотеза (pending M230)

При `hook_clauses=true` и наличии clauses callback → передать в `_hook_cands`.

**Контракт feature-flag off:**
- `hook_clauses=false` → поведение идентично текущему (clauses=None).
- `hook_clauses=true` и clauses=None → как сейчас (graceful degradation, warning).
- `hook_clauses=true` и clauses=callback → передать; новое поведение.

**Это изменение затрагивает `propose` signature/body — требует M230 arch review.**  
Semantic вопрос: нужно ли спасать clause как hook? — pending owner/architect approval.

---

## 5. Observability-first для #11 — только счётчики в M231; мутации отложены

### M231: только добавить счётчики (не менять алгоритм)

```
Stage counters (machine-readable, additive, не меняют selection):
  eligible:     N
  attempted:    N  (прошли eligible + seed_punch gate)
  none_reasons: {too_short: N, no_neighbors: N, question_end: N, ...}
  pool_added:   N
  fill_added:   N  (weak-seed)
  selected:     N
  rejected_by_validator: N (с reason dict)
  accepted:     N
```

Вывод в stderr как JSON-line, **только на синтетике / consent-free фикстурах** в M231.  
Реальные owner-данные — отдельный явный owner authorization (см. §6 ниже).

**Что НЕ входит в M231 (отложено до arch review / post-M230):**
- Изменение сигнатуры `teaser_misses` (добавить start_pause/clauses параметры) — мутация, не наблюдение.
- Поведенческое выравнивание `teaser_misses` ↔ `_hook_cands` — pending M230.
- Добавление `no_start`, `open_end` в weak-seed fill propose — мутация.
- Сохранение rhythm_out в weak-seed fill — мутация.
- Post-select fallback (#4) — мутация; только counter в M231.

---

## 6. Ограждение реальных медиа

Инструментация M231 использует **только синтетические, consent-free, no-side-effect фикстуры**.  
Любое использование owner-видео, реальных owner-логов, реальной просодии/alignment владельца:
- требует отдельного явного письменного owner authorization;
- требует privacy plan;
- не является условием M231 SUCCESS.

M237 A/B рендер — отдельное разрешение.

---

## 7. #10 и #12 — без изменений

**#10 (`hook_judge_top=6`):** намеренный бюджет. Не менять до измеренного пользовательского эффекта.

**#12 (tie-break):** `reversed([60,60,60])` = тот же массив; реальная перестановка ID не проверялась. DEFER до owner-демонстрации реального failing case. `stable_sort_by(id)` при tie — только гипотеза.

---

## 8. Граф зависимостей (пересмотрен)

```
Sol M228 PASS + явный GO-координатора
  └─► M229 (подготовка: docs + тест-каркас, M229_CODE_GO=NO)
        ├─► M230 (Arch review — ДО ЛЮБОГО propose body/signature кода)
        │     ├── Covers: #1, #2, #3, #5, #7, #8a, #8b, #9a, #9b
        │     ├── Owner approval semantic decisions
        │     └─► M231 (Observability ONLY: counters #11, delta-log #6)
        │           └─► Sol M231 PASS + recorded coordinator GO
        │                 └─► M232 (separately gated FIX_NOW impl; conditional #4/#6 fixes)
        │                 └─► M233 (Regression suite)
        │                       └─► M236 (Final QA + merge)
        │                             └─► M237 (A/B, отд. разрешение)
        └─► (параллельно с M230 arch) → документация и тест-каркас
```

**Правило:** никакой `propose` body/signature code до M230 arch review.  
Код M232 только после M230 arch approval, независимого Sol M231 PASS и отдельного явного coordinator GO для каждого source-changing пакета. M231 — исключительно additive observability.

---

## 9. Контракты и инварианты (резюме)

| Инвариант | Проверяемое условие | Статус |
|-----------|---------------------|--------|
| Proposal.duration ≥ min_sec | всегда, в финальном валидаторе | Proposal (M230) |
| Last unit != question (кроме question-loop) | финальный валидатор | Proposal (M230) |
| All refers satisfied | финальный валидатор | Proposal (M230) |
| Seed attempt → counted | propose счётчик | M231 (additive only) |
| None reason → logged | propose счётчик | M231 (additive only) |
| feature_flag=off → no behaviour change | каждый новый parameter | M230+ |
| manual selection preserved | не трогать manual-маркеры | Существующий |
| nonempty input + zero output → rc≠0 | cmd_autocut | Существующий |
| Overlap dedup at selection | финальный отбор из пула | Существующий + M230 |
| Question-led loop законен | первый unit может быть question | Поддерживается сейчас |
