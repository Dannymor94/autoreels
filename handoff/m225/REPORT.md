# M225 Stage A — Diagnostics Report

**Date:** 2026-11-19  
**Baseline:** `3c011e94263e16e5780936b4769d3490cd03b682` (main, production)  
**Gate precondition:** M224 `VERDICT=PASS_SCOPED`, `GATE_M225_STAGE_A_DIAGNOSTICS=OPEN`  
**Production config SHA256:** `efdef3adb0396e7e282553a8e3bfb0c690df015abdb8398cea1db5e642aeabba` (config/r0.yaml, unchanged)

---

## Метод

Все три кейса воспроизводятся через `propose()` из `src/autoreels/cloud/autocut.py` с `AutoParams`, загруженными из продакшен-конфига `config/r0.yaml` (не подменялись вручную).

Для Cases A и B дополнительно запускается `cmd_autocut("synth-a"/"synth-b", root=isolated_tmp, llm="none")` — он завершается с кодом 0 (пайплайн отработал), но proposals отклоняются на шаге блочной валидации `[ERROR] M1: block 1 is not in the review numbering` из-за отсутствия matching-блоков в синтетическом transcript. Это побочный эффект минимального transcript (1 слово), а не проявление исследуемых багов.

**REPRO.py SHA256:** `0295cc4fd44ad3ebb31f5c51df28468913ab47db79381183cd9269d9e3c04f30`  
**Проверок выполнено:** 16  
**PASS / FAIL:** 16 / 0

---

## Finding #7 — Потеря зависимости через fit_rhythm

**Verdict: HELPER_CONFIRMED**

### Суть

`fit_rhythm` удаляет промежуточный unit (#2, explanation), на который ссылается (#3, conclusion) через `refers=2`. В итоговом клипе `[#1, #3]` поле `#3.refers=2` не удовлетворено — зависимость потеряна.

### Синтетические данные

| ID | role        | t0  | t1  | dur  | refers | standalone |
|----|-------------|-----|-----|------|--------|------------|
| 1  | thesis      | 50  | 76  | 26 s | —      | True       |
| 2  | explanation | 90  | 95  |  5 s | 1      | False      |
| 3  | conclusion  | 160 | 193 | 33 s | 2      | False      |

### Путь исполнения

1. `build_passage(seed=#1)` → `[#1, #2]` (gap=14 s ≤ passage_gap=30; #3 at gap=65 s > 30 → не включается)
2. `add_payoff`: `#3.refers=2 ∈ ids={1,2}` → добавляет #3; clip = `[#1, #2, #3]`
3. `fit_rhythm` (keep={1,3}): piece1=[#2], dur=5 s < settle_need(14)×1.0=6.22 s → нет соседей (оба смежных уже в клипе) → **удаляет #2**
4. clip = `[#1, #3]`; `rhythm_why`: dur[1]=33 s ≥ settle_need(84)×0.5=5.02 s ✓ → proposal создан
5. В итоговом клипе `#3.refers=2` ∉ `{1, 3}` → зависимость не удовлетворена

### Корневая причина

`fit_rhythm` не проверяет, что удаляемый unit является прямым `refers`-зависимостью сохраняемого unit. `keep` содержит только `{seed.id, clip[-1].id}`, а `leans_on`-цепочка не используется для защиты промежуточных узлов.

---

## Finding #8a — fit_rhythm добавляет вопрос в конец клипа

**Verdict: HELPER_CONFIRMED**

### Суть

`fit_rhythm` расширяет короткий последний кусок `[#2]` ближайшим соседом `#3` (question). Итог: клип заканчивается на вопросе, что противоречит правилу `build_clip` (там есть проверка `clip[-1].role == "question" → None`), но в пути `generator="mixed"` / `propose()` эта проверка отсутствует.

### Синтетические данные

| ID | role       | t0 | t1  | dur  | standalone |
|----|------------|----|-----|------|------------|
| 1  | thesis     | 50 | 76  | 26 s | True       |
| 2  | conclusion | 90 | 93  |  3 s | True       |
| 3  | question   | 94 | 119 | 25 s | True       |

Примечание: `dur(#3)=25 s > loop_max_sec=20 s` → `_loop_question` пропускает #3 (нет prepend-а).

### Путь исполнения

1. `build_passage(seed=#1)` → `[#1, #2, #3]`; post-loop: #3 (question) срезается → `[#1, #2]`
2. `_loop_question`: `dur(#3)=25 > loop_max_sec=20` → None
3. `add_payoff`: clip[-1]=#2 (conclusion) ∈ PAYOFFS → no-op
4. `fit_rhythm` (keep={1,2}): piece1=[#2], dur=3 s < settle_need(14)×0.5=3.11 s → сосед #3 (gap=1 s ≤ jump=10, same topic, eligible, total 54 ≤ max 90) → **добавляет #3**
5. clip = `[#1, #2, #3]`; final rhythm_why: dur[1]=28 s ≥ 3.11 ✓ → proposal создан
6. `clip[-1].role == "question"` → клип оканчивается вопросом

### Корневая причина

`fit_rhythm` не проверяет роль добавляемого соседа. `eligible()` принимает любую роль кроме `None`/`aside`. После добавления вопроса в конец `propose()` не имеет post-check на `clip[-1].role == "question"` (в отличие от `build_clip`).

---

## Finding #8b — Позднее отклонение после trim fix_open_end

**Verdict: HELPER_CONFIRMED**

### Суть

`fix_open_end` укорачивает последний unit (срезает открытую фразу), после чего финальная проверка `rhythm_why` отклоняет клип. Второй вызов `fit_rhythm` НЕ делается — клип теряется целиком, хотя neighbor мог бы восстановить ритм.

### Синтетические данные

| ID | role       | t0  | t1  | dur  | refs    |
|----|------------|-----|-----|------|---------|
| 1  | thesis     | 50  | 76  | 26 s | 1.1     |
| 2  | conclusion | 126 | 157 | 31 s | 2.1-2   |

Предложения unit #2:
- S2.1: "Результат снижается." (1.5 s) → tone **final**
- S2.2: "Навсегда останется там." (28.5 s) → tone **open**

### Путь исполнения

1. `build_passage(seed=#1)` → `[#1]` (gap=50 s > passage_gap=30)
2. `add_payoff`: #2 standalone → добавляет; clip = `[#1, #2]`
3. `fit_rhythm`: dur[1]=31 s ≥ settle_need(50)×0.5=4.09 s ✓ → passes
4. `context_start`: "Мозг человека работает иначе." — не back-reference → passes
5. `fix_open_end`: S2.2 → "open" → trim; cut=28.5 s, new #2.t1=128.5, new dur=2.5 s
6. Final `rhythm_why` (line 1249–1255): dur[1]=2.5 s < need=4.09 s → **REJECT** (добавляется в `rhythm_out`)
7. Нет второго вызова `fit_rhythm` после trim → клип безвозвратно теряется

### Корневая причина

После `fix_open_end` в `propose()` вызывается только `rhythm_why` (проверка), но не `fit_rhythm` (ремонт). Это нарушает инвариант: клип, который прошёл ритм-проверку до трима, может не пройти после него, и у пайплайна нет возможности это починить.

---

## Итог

| Finding | Verdict           | Код подтверждения                      |
|---------|-------------------|----------------------------------------|
| #7      | HELPER_CONFIRMED  | `propose()` clip=[1,3], #3.refers=2 ∉ ids |
| #8a     | HELPER_CONFIRMED  | `propose()` clip=[1,2,3], clip[-1].role="question" |
| #8b     | HELPER_CONFIRMED  | `propose()` proposals=0, rhythm_out=[…50с…2.5с…] |

**Все три находки подтверждены в production-коде на базовом коммите `3c011e9`.**

Пайплайн не тронут. Данный отчёт — только диагностика; исправления ждут Sol 6.1 QA.
