# M228 — Реестр 12 находок (R2 — исправлено после Sol R1)

**База:** `main@3c011e94263e16e5780936b4769d3490cd03b682`  
**Независимые приёмки:** M223 Sol R5 · M224 Sol R2 · M225 Sol Stage-A · M226 Sol Stage-A · M227 Sol Stage-A  
**EVIDENCE_BASE_SHA (R1 delivery):** `44086710a04af83ccbef41b8c491096349003e5a`  
**PRODUCTION_DIFF=NONE**  
**Единицы:** 12 родительских находок, 14 подслучаев (#8a/8b, #9a/9b вынесены в отдельную таблицу ниже)

---

## Основная таблица (12 родительских строк)

| ID | Режим отказа / инвариант | Высший принятый уровень доказательства | Наблюдено / не воспроизведено | Ожидаемое поведение / политика | Пользовательский эффект | Действие | Веха | Контракт регрессионного теста | Закреплённые доказательства |
|----|--------------------------|----------------------------------------|-------------------------------|-------------------------------|------------------------|----------|------|-------------------------------|--------------------------|
| #1 | `used_seeds/taken` подавляет независимо жизнеспособную альтернативу | CLI_CONFIRMED (механизм в bounded CLI, `autocut.py:1175,1262–1264`) | Механизм подтверждён; поздний медиа-отказ NOT_REPRODUCED | Независимо eligible u2 должна достичь пула для рассмотрения; финальный overlap-dedup не убирается | INFERRED (потеря клипа возможна) | FIX_NOW | M230→impl (после arch review) | Fail-before: u2 не в пуле при текущем коде; pass-after: u2 в пуле, финальные клипы не пересекаются по units | M223 `9bb5667386b70ac93f041b8abb9f22359dbca286` |
| #2 | `propose` обходит `start_strict`/`answer_start`/`start_morph` при body opener | CLI_CONFIRMED (bounded, синтетика) | Первый планируемый звук — hook `2.1`/`1.2`, не body opener `Да…` — подтверждено | Body opener «Да…» не должен обходить start-морфологические проверки | PROVED (в границах синтетического CLI-пути) | FIX_NOW | M230→impl (после arch review) | Fail-before: body opener без hook → проходит; pass-after: body opener без hook → start_strict block | M223 `9bb5667386b70ac93f041b8abb9f22359dbca286` |
| #3 | `clauses` не передаётся из `propose` в `_hook_cands` | CLI_HELPER_BOUNDARY + STATIC | 6 вызовов `_hook_cands(clauses=None)` при production config; counterfactual HELPER_ONLY; production impact NOT_REPRODUCED | `propose` должен передавать clauses callback при `hook_clauses=true`; feature-off parity сохраняется | INFERRED (hook-кандидаты могут теряться) | FIX_NOW | M230→impl (после arch review) | Fail-before: с clauses callback → `_hook_cands` не находит clause-only hook; pass-after: находит | M223 `9bb5667386b70ac93f041b8abb9f22359dbca286` |
| #4 | `select_global` сравнение B+C=120 против A=95 — поздний отказ не воспроизведён | HELPER_CONFIRMED (selector comparison) | B+C=120 vs A=95 при реальных `too_close`/helper-функциях подтверждено; поздний финальный отказ NOT_REPRODUCED | После инструментации: post-select rejection должен возвращать следующего кандидата | INFERRED — не доказана потеря у пользователя | INSTRUMENT_FIRST | M231 | Тест добавляется после M231 наблюдения реального поведения | M226 `e1be1b74cb033a8575d3967eceb8b06c3800f790` |
| #5 | `context_start` укорачивает 25.0→23.0 с при `min_sec=25` | CLI_HELPER_BOUNDARY | t=25.0 → 23.0 наблюдено при реальном `cmd_autocut`, `generator=mixed`; итоговые `Proposal.seconds` / рендер NOT_VERIFIED | Clip после context_start должен проходить re-check min_sec | INFERRED (коротковатый клип возможен) | FIX_NOW | M230→impl (после arch review) | Fail-before: context_start возвращает dur < min_sec и не rejecting; pass-after: dur ≥ min_sec или reject | M224 `d18627fb0fff56c4735b3c0462b1796337989715` erratum `78511b42887b5be7070b8241d30e6d7556e20568` |
| #6 | t0/t1 смещение 0.4 с / 1.0 с после пауз | CLI_HELPER_BOUNDARY | t0 offset 0.4s, t1 offset 1.0s при синтетическом выравнивании; реальный playback mismatch NOT_REPRODUCED | Манифестные t0/t1 должны совпадать с первым/последним словом | INFERRED (молчание в начале/конце возможно) | INSTRUMENT_FIRST | M231 | Тест добавляется после M231 delta-лога на синтетике | M224 `d18627fb0fff56c4735b3c0462b1796337989715` |
| #7 | `fit_rhythm` удаляет unit с `refers`, зависимость не удовлетворена | HELPER_CONFIRMED | `propose` возвращает [1,3] при `#3.refers=2`; CLI synthetic validator не принимает клип | Удаление unit из `fit_rhythm` обязано проверить unsatisfied refs; validation contract pending arch review | INFERRED (несвязный клип возможен) | FIX_NOW | M230→impl (после arch review) | Fail-before: клип с несвязанным refers → не rejecting; pass-after: → reject с reason | M225 `af35a30b7e522d344dcac41ce9c2b9e4b32ea8af` |
| #8 | `propose`/trim оставляет вопрос как последний unit или отклоняет post-trim клип (#8a, #8b) | HELPER_CONFIRMED (#8a и #8b) | #8a: question-as-last подтверждён; #8b: reject после trim 2.5s < 4.09s подтверждён; ремонтируемый сосед NOT_VERIFIED | #8a: клип не должен заканчиваться вопросом. #8b: fail-closed с logged reason если нет доказанного соседа | INFERRED | FIX_NOW | M230→impl (#8a); M230 arch (сосед для #8b) | Подслучаи — см. ниже | M225 `af35a30b7e522d344dcac41ce9c2b9e4b32ea8af` |
| #9 | `build_passage` преждевременно прерывает рост (#9a, #9b) | HELPER_CONFIRMED (#9a и #9b) | #9a: break при overlong nxt без fallback prv — подтверждён; #9b: вопрос удалён post-loop, ответ не посещён — подтверждён; CLI-финал NOT_REPRODUCED | #9a: при overlong nxt → продолжить с prv eligible; #9b: answer extension после удаления question — гипотеза, требует arch review | INFERRED | FIX_NOW | M230→impl (#9a); M230 arch (#9b) | Подслучаи — см. ниже | M226 `e1be1b74cb033a8575d3967eceb8b06c3800f790` |
| #10 | `hook_judge_top=6` обрезает 7-й hook-кандидат | INTENTIONAL | Параметр намеренный: бюджет вызовов LLM | Бюджет 6 — сознательный компромисс скорость/полнота | UNKNOWN (не измерено у пользователя) | NO_FIX_INTENTIONAL | — до измеренного impact | Тест: не требуется; параметр контролируется owner'ом | M222 static analysis |
| #11 | Невидимые отказы до пула; `teaser_misses` возвращает «прошла» при `glued_start`-отклонении `_hook_cands` | CLI_OUTPUT_GAP (manual accounting) + HELPER_CONFIRMED (teaser) + STATIC (weak-seed) | Map B: 2 eligible seeds → 1 proposal (gap=1 невидим); teaser discrepancy HELPER с synthetic start_pause; actual CLI no alignment; weak-seed static | Каждый seed attempt должен считаться; `teaser_misses` должна иметь те же проверки что `_hook_cands` — гипотеза, ожидает arch review | INFERRED | INSTRUMENT_FIRST | M231 (счётчики только) | Тест: per-stage счётчики на синтетике; `teaser_misses` выравнивание — после arch review | M227 `929646319dc55b5d6dc62f6321582bf20622cc09` |
| #12 | Tie-break зависит от входного порядка — runtime-пермутации не доказаны | HELPER_CONFIRMED (same input) + STATIC_INFERRED (order sensitivity) | Одинаковый упорядоченный вход даёт тот же результат повторяемо; `reversed([60,60,60])` = тот же массив; реальная перестановка ID не проверена; не является недетерминизмом | Stable sort при идентичных score — гипотеза; не менять без реального failing case | NOT_RUNTIME_PROVEN | DEFER | — до owner-демонстрации реального failing case | Тест: только если owner показывает реальный case с другим результатом | M226 `e1be1b74cb033a8575d3967eceb8b06c3800f790` |

---

## Подслучаи #8 и #9

| Подслучай | Доказательство | Действие | Контракт теста |
|-----------|---------------|----------|----------------|
| #8a — `propose` возвращает клип с question как последним unit | HELPER_CONFIRMED | FIX_NOW (M230→impl) | Fail-before: question-as-last проходит; pass-after: trim или reject с reason |
| #8b — trim оставляет кусок 2.5 с < minRhythm 4.09 с и клип отклоняется; сосед NOT_VERIFIED | HELPER_CONFIRMED (trim→reject); NOT_VERIFIED (ремонт) | FIX_NOW (fail-closed с reason; arch review для repair semantics) | Fail-before: short piece → тихий drop; pass-after: → logged reason reject; repair только после arch approval |
| #9a — `build_passage` break при overlong nxt, не пробует prv | HELPER_CONFIRMED | FIX_NOW (M230→impl) | Fail-before: overlong nxt → None; pass-after: prv eligible → passage не None |
| #9b — `build_passage` достигает target на вопросе, удаляет post-loop, ответ не посещён | HELPER_CONFIRMED | FIX_NOW → гипотеза за arch review (M230) | Fail-before: answer не посещается; pass-after: answer unit included; pending arch design |

---

## Сводка действий

| Действие | Родительские находки | Подслучаев | Веха |
|----------|---------------------|-----------|------|
| FIX_NOW | #1, #2, #3, #5, #7, #8, #9 | 9 (#1,#2,#3,#5,#7,#8a,#8b,#9a,#9b) | M230→impl |
| INSTRUMENT_FIRST | #4, #6, #11 | 3 | M231 |
| NO_FIX_INTENTIONAL | #10 | 1 | — |
| DEFER | #12 | 1 | — до runtime proof |

**Итого:** 12 родительских находок, 14 подслучаев.  
**FIX_NOW:** 7 родительских / 9 подслучаев · **INSTRUMENT_FIRST:** 3 · **NO_FIX_INTENTIONAL:** 1 · **DEFER:** 1

---

## Доказательные ограничения (неизменны с M223–M227)

- Ни одна находка не подтверждена до уровня реального рендера или измеренного пользовательского эффекта.
- #3, #6, #7, #8b, #9b, #11 имеют helper-уровень или статический уровень; production impact INFERRED.
- #4, #9a-b поздний CLI-финал NOT_REPRODUCED.
- `repro.exit` из M227 evidence.json отсутствует в published tree (отмечено Sol M227).
- Не смешивать `exit 0` REPRO-скрипта с доказанным production-конечным результатом.
- #7/#8/#9: HELPER_CONFIRMED — не CLI_HELPER_BOUNDARY. Принятая Sol-область не расширяется.
- Веха реализации всех FIX_NOW зависит от M230 arch review и явного GO-решения координатора.
