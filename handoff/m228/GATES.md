# M228 — Ворота: GO/NO-GO и план вех M229–M236

**Статус:** PROPOSAL · требует независимого Sol QA M228  
**PRODUCTION_DIFF=NONE**

---

## 1. Рекомендация: GO_SCOPED

**GO_SCOPED** — рекомендуется переход к планированию M229+.

**Обоснование:**
- 7 находок (FIX_NOW) имеют независимо принятые доказательства уровня CLI_HELPER_BOUNDARY или выше.
- 3 находки (INSTRUMENT_FIRST) требуют инструментации до исправления — не блокируют M229.
- 2 находки (NO_FIX_INTENTIONAL) — намеренное поведение, нет действия.
- Ни одна находка не имеет RENDER-уровня; исправления не расширяют заявленные доказательства.
- Архитектурные принципы (#4, #7, #8b, #9b) требуют отдельного M230 arch review.

**Ограничения GO_SCOPED:**
- Не авторизует изменение `propose` без M230 arch gate.
- Не авторизует изменение `select_global` постselector behaviour без M231 instrumentation.
- Не авторизует рендер, платные API, изменение owner-данных.

---

## 2. Предложение вех M229–M236

### M229 — Изолированные FIX_NOW (нет arch-зависимости)

**Задачи:** #1, #2, #5, #8a, #9a  
**Разрешённые пути:** `src/autoreels/cloud/autocut.py` (конкретные функции)  
**Запрещено:** изменять `propose` signature, `select_global`, `fill_pool`  
**Feature flags:** нет новых — все изменения в существующей логике  
**Тесты (детерминированные, без рендера):**
- #1: `eligible u2 alone → в пуле, когда u1 taken`
- #2: `body opener → rejected start_strict`
- #5: `context_start → dur >= min_sec`
- #8a: `последний unit = question → trim или reject`
- #9a: `overlong nxt → прv fallback → build_passage не None`

**CI gates:** 100% тестов проходят на `base_sha`; тесты изолированы от owner-данных  
**Rollback:** любой тест-fail или rc≠0 на синтетике → откат  
**Senior QA:** Sol 6.1 независимый review перед merge в main

---

### M230 — Arch review + propose wiring (#3, #7, #8b, #9b)

**Задача:** Arch review сильной моделью (GPT или Claude Opus) перед кодом  
**Разрешённые пути:** анализ только, никаких правок до acceptance  
**Решения, требующие owner/architect approval:**
- Semantic: clauses rescue — нужно ли спасать clause как hook?
- Repair semantics для #8b: какой сосед легален? контракт?
- #9b: answer-after-question — всегда или только certain roles?
- Новые signatures `propose(clauses=...)` — backward-compatible?

**CI gates:** arch document принят, feature-off parity тест  
**Merge:** только после Sol M230 PASS + owner approval semantic decisions

---

### M231 — Инструментация (#4, #6, #11)

**Задачи:** per-stage счётчики, t0/t1 alignment validator, teaser_misses align  
**Разрешённые пути:** `src/autoreels/cloud/autocut.py`, `src/autoreels/__main__.py`  
**Выход:** JSON-line логи `{"stage": "propose", "eligible": N, ...}`  
**Критерий SUCCESS:** реальный прогон на owner-видео показывает per-seed детализацию  
**Нет исправления алгоритма** — только наблюдение  
**Senior QA:** Sol 6.1 review на реальных логах (не синтетика)

---

### M232 — Пост-M231 fixes (#4, #6)

**Условие запуска:** M231 instrumentation показывает реальный failing case  
**Задачи:** post-select fallback (#4), t0/t1 boundary fix (#6)  
**Feature flags:** `fix_select_fallback=false` по умолчанию до M237 A/B

---

### M233 — Regression suite hardening

**Задача:** формализовать M229-M230 тесты в CI, добавить negative cases  
**CI gates:** тесты проходят на base_sha; ни один не обращается к owner-data

---

### M234–M235 — По результатам M231/M232

Вехи зависят от M231 observational data. Не планировать детально до M231 PASS.

---

### M236 — Итоговый QA и документация

**Задача:** обновить ARCHITECTURE.md, закрыть все FIX_NOW  
**Senior QA:** финальный Sol review перед производственным merge  
**Нет A/B рендера** — это M237 (отдельное разрешение)

---

### M237 — A/B рендер (требует отдельного разрешения)

**Не авторизован в текущем плане.** Требует:
- Явного owner approval на модельные записи/paid API
- Отдельного Sol gate
- Изолированных owner-данных

---

## 3. Нерешённые вопросы для owner/architect

| Вопрос | Влияние | Веха |
|--------|---------|------|
| Semantic: спасать ли clause как hook при `hook_clauses=true` (#3)? | Меняет количество hook-кандидатов | M230 |
| Repair semantics #8b: какой сосед разрешён для short-tail? | Определяет контракт build_passage | M230 |
| #9b: всегда ли добавлять answer после question-target? | Меняет semantics passage | M230 |
| Budget #10: измерить % clips без hook при 6 vs 8 — нужно? | Решение о `hook_judge_top` | M237+ |
| A/B рендер (#4, #6): когда и на каких данных? | Доказательство real playback | M237 |

---

## 4. Реестр рисков

| Риск | Статус | Минимальная инструментация |
|------|--------|--------------------------|
| #1: late rejection после select_global в реальном media | NOT_REPRODUCED | M231: post-select счётчик |
| #3: реальная потеря hook при `clauses=None` | NOT_REPRODUCED | M231: лог hook-кандидатов с/без clauses |
| #4: тихий финальный drop после select_global | NOT_REPRODUCED | M231: selected→accepted счётчик |
| #6: playback silence / misalignment у пользователя | NOT_REPRODUCED | M231: t0/t1 delta лог при alignment |
| #7: несвязный клип у пользователя | NOT_REPRODUCED | M230: refers validator |
| #8b: потеря repair-able clip | NOT_VERIFIED | M230: neighbor-contract proof |
| #9: seed пропущен без диагностики | HELPER | M229: build_passage reason log |
| #11: точный per-seed CLI spy | NOT_INSTRUMENTED | M231: JSON-line stage counters |
| teaser_misses discrepancy в CLI с alignment | NOT_REPRODUCED | M231: teaser_misses align |

---

## 5. Порядок зависимостей

```
Sol M228 PASS
  └─► M229 (FIX_NOW изолированные) ─► Sol M229 PASS
        └─► M230 (Arch review) ─► owner approval ─► Sol M230 PASS
              └─► M231 (Instrument) ─► Sol M231 PASS
                    └─► M232 (Post-instrument fixes, если нужно)
                          └─► M233 (Regression suite)
                                └─► M236 (Final QA)
                                      └─► M237 (A/B, отдельное разрешение)
```

Параллельно: M229 и M230 arch analysis могут вестись одновременно.
