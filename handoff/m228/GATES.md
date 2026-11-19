# M228 — Ворота: GO/NO-GO и план вех M229–M237 (R2)

**Статус:** PROPOSAL · требует независимого Sol QA M228  
**PRODUCTION_DIFF=NONE**  
**M229_CODE_GO=NO** — реализация не авторизована до Sol M228 PASS + явного GO-решения координатора + M230 arch review

---

## 1. Рекомендация: GO_SCOPED

**GO_SCOPED** — рекомендуется переход к M229 preparation (docs + тест-каркас, без production кода).

**Обоснование (скорректировано с учётом Sol R1):**
- Уровни доказательств по группам:
  - #1, #2, #3, #5: CLI_CONFIRMED (bounded) или CLI_HELPER_BOUNDARY — достаточно для планирования.
  - #7, #8, #9: HELPER_CONFIRMED — достаточно для планирования; не CLI-уровень.
  - #4, #6, #11: требуют инструментации до исправления — не блокируют M229 preparation.
  - #10: намеренное поведение; #12: DEFER до runtime proof.
- Ни одна находка не имеет RENDER-уровня; исправления не расширяют заявленные доказательства.
- Все FIX_NOW находки затрагивают `propose` body или вызываемые из него функции → **все ожидают M230 arch review** перед кодом.

**Ограничения GO_SCOPED:**
- **M229_CODE_GO=NO** до: (1) Sol M228 PASS, (2) явного GO-решения координатора, (3) M230 arch review completion.
- Любое изменение `propose` body, signature, или вызываемых из него функций (`build_passage`, `context_start`, `_hook_cands`) требует M230 arch review.
- Не авторизует рендер, платные API, изменение owner-данных.
- Sol PASS одного этапа не является автоматическим авторизацией кода следующего — требуется явное coordinator GO decision.

---

## 2. Предложение вех M229–M237

### M229 — Preparation: документация и тест-каркас (M229_CODE_GO=NO)

**Задача:** подготовить test scaffolding и negative failing tests; никаких изменений production кода.  
**Разрешено:**
- Написать failing regression tests (fail-before для каждого FIX_NOW находки).
- Документировать exact code paths для M230 arch review.
- Анализ callgraph: какие символы затрагивает каждая находка.

**Запрещено:** любое изменение `src/`, `tests/` production suite, `config/`.  
**Регрессионный контракт M229:**
- Существующий тест-сьют проходит на baseline `3c011e94...` без изменений.
- Новые failing тесты демонстрируют defect-before: fail на baseline, pass после fix.
- Негативные тесты (expected rejection) PASS путём assertion correct rejection.

**Авторизация:** Sol M229 PASS + явный coordinator GO до M230.

---

### M230 — Arch review ВСЕ FIX_NOW (#1, #2, #3, #5, #7, #8, #9)

**Задача:** arch review сильной моделью (GPT или Claude Opus) + owner approval semantic decisions.  
**Covers:** все находки, затрагивающие `propose` body/signature или вызываемые функции.  
**Разрешено:** только анализ + документация arch decisions; никаких правок production кода.  
**Нерешённые semantic вопросы (требуют owner/architect approval):**
- #3: спасать ли clause как hook при `hook_clauses=true`?
- #8b: какой сосед легален для short-tail repair?
- #9b: answer-after-question — всегда или только certain roles?
- #3/#7: backward-compatible signatures для `propose`?
- #1: bounded re-attempt — стоп-условие и допустимый N попыток?

**CI gates:** arch document принят; feature-off parity confirmed; owner approval semantic decisions.  
**Merge:** только после Sol M230 PASS + явного coordinator GO.  
**Авторизация кода:** явное coordinator GO для каждого пакета изменений после M230.

---

### M231 — Observability-only (#4, #6, #11) + Implementation FIX_NOW

**Задача часть A — observability (только additive counters, без мутаций алгоритма):**
- Per-stage счётчики: eligible/attempted/none_reasons/pool_added/selected/accepted.
- t0/t1 delta-лог (только вывод, не rejection): `{"t0_delta": 0.4, "t1_delta": 1.0}`.
- Вывод JSON-line в stderr.
- Только **синтетические / consent-free фикстуры**. Реальные owner-данные — отдельный authorization.

**Запрещено в M231:**
- Изменение сигнатуры `teaser_misses` или её поведения.
- Добавление `no_start`, `open_end` параметров в weak-seed fill propose.
- Сохранение rhythm_out в weak-seed fill.
- Post-select fallback (#4) — только counter.
- t0/t1 rejection validator (#6) — только delta-лог.

**Задача часть B — реализация FIX_NOW (условие: M230 arch approval получен):**
- #1, #2, #3, #5, #7, #8a, #8b, #9a + (если одобрено arch) #9b.
- Каждый с fail-before/pass-after тестом.
- Feature-off parity для новых параметров.
- Реализация только одобренных в M230 designs.

**Критерий SUCCESS M231:** synthetic тест демонстрирует per-stage счётчики; failing regression pass-after каждого FIX_NOW. Нет требования на owner-видео.  
**Senior QA:** Sol 6.1 review на synthetic outputs.

---

### M232 — Пост-M231 behavior fixes (#4 fallback, #6 boundary)

**Условие запуска:** M231 instrumentation показывает реальный failing case на синтетике.  
**#4:** post-select fallback реализация (если M231 counter показывает gap).  
**#6:** t0/t1 boundary enforcement (если M231 delta-лог показывает реальный mismatch).  
**Feature flags:** `fix_select_fallback=false` по умолчанию; `fix_timing_boundary=false`.

---

### M233 — Regression suite hardening

**Задача:** формализовать M229-M231 тесты в CI, добавить edge cases.  
**CI gates:** все тесты проходят на base_sha; ни один не обращается к owner-data; negatives PASS.

---

### M234–M235 — По результатам M231/M232

Вехи зависят от M231/M232 observational data. Не планировать детально до M232 PASS.

---

### M236 — Итоговый QA и документация

**Задача:** обновить ARCHITECTURE.md, закрыть все FIX_NOW.  
**Senior QA:** финальный Sol review перед производственным merge.  
**Нет A/B рендера** — это M237.

---

### M237 — A/B рендер (требует отдельного разрешения)

**Не авторизован в текущем плане.** Требует:
- Явного owner authorization на owner-данные и рендер.
- Privacy plan для любых реальных медиа.
- Отдельного Sol gate.

---

## 3. Нерешённые вопросы для owner/architect

| Вопрос | Влияние | Веха |
|--------|---------|------|
| #3: спасать ли clause как hook при `hook_clauses=true`? | Меняет количество hook-кандидатов | M230 |
| #8b: какой сосед легален для short-tail repair? | Определяет контракт build_passage | M230 |
| #9b: всегда ли добавлять answer после question-target? | Меняет semantics passage | M230 |
| #1: N попыток bounded re-attempt — какое значение? | Stopping condition | M230 |
| #10: измерить % clips без hook при 6 vs 8? | Решение о `hook_judge_top` | M237+ |
| A/B рендер (#4, #6): когда и на каких данных? | Доказательство real playback | M237 |
| M231 real owner-logs: нужно ли, когда, privacy plan? | Scope real data | M237 |

---

## 4. Реестр рисков

| Риск | Статус | Минимальная инструментация |
|------|--------|--------------------------|
| #1: late rejection после select_global в реальном media | NOT_REPRODUCED | M231: post-select счётчик (synthetic) |
| #3: реальная потеря hook при `clauses=None` | NOT_REPRODUCED | M231: лог hook-кандидатов с/без clauses |
| #4: тихий финальный drop после select_global | NOT_REPRODUCED | M231: selected→accepted счётчик |
| #6: playback silence / misalignment у пользователя | NOT_REPRODUCED | M231: delta-лог на синтетике |
| #7: несвязный клип у пользователя | NOT_REPRODUCED | M230: refers validator design |
| #8b: потеря repair-able clip | NOT_VERIFIED | M230: neighbor-contract proof |
| #9: seed пропущен без диагностики | HELPER | M229/M231: none_reasons counter |
| #11: точный per-seed CLI spy | NOT_INSTRUMENTED | M231: JSON-line stage counters |
| teaser_misses discrepancy в CLI с alignment | NOT_REPRODUCED | Post-M230: teaser_misses arch review |

---

## 5. Порядок зависимостей

```
Sol M228 PASS + явный coordinator GO
  └─► M229 (preparation: docs + test scaffolding, NO_CODE)
        └─► M230 (Arch review ВСЕХ FIX_NOW)
              ├── owner approval semantic decisions
              └─► Sol M230 PASS + явный coordinator GO
                    └─► M231 (observability + FIX_NOW impl)
                          └─► Sol M231 PASS
                                └─► M232 (post-instr. fixes)
                                      └─► M233 (regression)
                                            └─► M236 (final QA)
                                                  └─► M237 (A/B, отд. разрешение)
```

**Параллельно:** M229 test scaffolding и M230 arch analysis могут вестись одновременно.
