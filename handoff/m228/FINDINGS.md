# M228 — Реестр 12 находок (финальный синтез)

**База:** `main@3c011e94263e16e5780936b4769d3490cd03b682`  
**Независимые приёмки:** M223 Sol R5 · M224 Sol R2 · M225 Sol Stage-A · M226 Sol Stage-A · M227 Sol Stage-A  
**PRODUCTION_DIFF=NONE**

---

## Таблица находок

| ID | Режим отказа / инвариант | Высший принятый уровень доказательства | Наблюдено / не воспроизведено | Ожидаемое поведение / политика | Пользовательский эффект | Действие | Веха | Контракт регрессионного теста | Закреплённые доказательства |
|----|--------------------------|----------------------------------------|-------------------------------|-------------------------------|------------------------|----------|------|-------------------------------|--------------------------|
| #1 | `used_seeds/taken` подавляет независимо жизнеспособную альтернативу | CLI_CONFIRMED (механизм) | Механизм CLI подтверждён; поздний медиа-отказ NOT_REPRODUCED | Если u2 проходит все проверки independently, он должен попасть в пул | INFERRED (потеря клипа возможна при перекрытиях) | FIX_NOW | M229 | Синтетический тест: u2 eligible alone → появляется в пуле, когда u1 уже занят | M223 `9bb5667386b70ac93f041b8abb9f22359dbca286` |
| #2 | `propose` обходит `start_strict`/`answer_start`/`start_morph` при body opener | CLI_CONFIRMED (bounded, синтетика) | Первый планируемый звук — hook `2.1`/`1.2`, не body opener `Да…` — подтверждено | Body opener «Да…» не должен обходить start-морфологические проверки | PROVED (в границах синтетического CLI-пути) | FIX_NOW | M229 | Тест: body opener без hook → start_strict block | M223 `9bb5667386b70ac93f041b8abb9f22359dbca286` |
| #3 | `clauses` не передаётся из `propose` в `_hook_cands` | CLI_HELPER_BOUNDARY + STATIC | 6 вызовов `_hook_cands(clauses=None)` при production config; counterfactual HELPER_ONLY; real impact NOT_REPRODUCED | `propose` должен передавать clauses callback, если конфиг `hook_clauses=true` | INFERRED (hook-кандидаты могут теряться) | FIX_NOW + сохранить feature_off parity | M230 (после arch review) | Тест: с clauses callback → `_hook_cands` находит clause-only hook; без callback → нет | M223 `9bb5667386b70ac93f041b8abb9f22359dbca286` |
| #4 | `select_global` принимает B+C=120 до финального отказа, A=95 подавлен | HELPER_CONFIRMED (selector) | B+C=120 vs A=95 при реальных `too_close`/helper-функциях подтверждено; поздний отказ NOT_REPRODUCED | Итоговый отказ после select_global должен возвращать следующего кандидата, а не молча терять | INFERRED (возможная потеря у пользователя — не доказана) | INSTRUMENT_FIRST | M231 | Тест: проверить что post-select rejection вызывает fallback, а не тихое отсутствие | M226 `e1be1b74cb033a8575d3967eceb8b06c3800f790` |
| #5 | `context_start` укорачивает 25.0→23.0 с при `min_sec=25` | CLI_HELPER_BOUNDARY | t=25.0 → 23.0 наблюдено при реальном `cmd_autocut`, `generator=mixed`; итоговые `Proposal.seconds` / рендер NOT_VERIFIED | Clip после context_start должен проходить min_sec повторно | INFERRED (коротковатый клип возможен) | FIX_NOW | M229 | Тест: context_start не должен давать dur < min_sec | M224 `d18627fb0fff56c4735b3c0462b1796337989715` erratum `78511b42887b5be7070b8241d30e6d7556e20568` |
| #6 | t0/t1 смещение 0.4 с / 1.0 с после пауз | CLI_HELPER_BOUNDARY | t0 offset 0.4s, t1 offset 1.0s при синтетическом выравнивании; реальный playback mismatch NOT_REPRODUCED | Манифестные t0/t1 должны совпадать с первым/последним словом clip-а | INFERRED (молчание в начале/конце возможно) | INSTRUMENT_FIRST | M231 | Тест: t0 == first word start, t1 == last word end (с реальным alignment) | M224 `d18627fb0fff56c4735b3c0462b1796337989715` |
| #7 | `fit_rhythm` удаляет unit с `refers`, зависимость не удовлетворена | HELPER_CONFIRMED | `propose` возвращает [1,3] при `#3.refers=2`; CLI synthetic validator не принимает клип | Удаление unit из `fit_rhythm` обязано проверить unsatisfied refs или пересобрать | INFERRED (несвязный клип возможен) | FIX_NOW | M230 (после arch review) | Тест: клип с несвязанным refers → валидатор отклоняет или ремонтирует | M225 `af35a30b7e522d344dcac41ce9c2b9e4b32ea8af` |
| #8a | `propose` возвращает клип, заканчивающийся `role=question` | HELPER_CONFIRMED | `propose` выдаёт [1,2,3] с question последним; поздний CLI-отклик NOT_REPRODUCED | Клип не должен заканчиваться на вопрос | INFERRED (незаконченный клип у пользователя) | FIX_NOW | M229 | Тест: финальный unit question → обрезать до предыдущего valid unit | M225 `af35a30b7e522d344dcac41ce9c2b9e4b32ea8af` |
| #8b | Trim оставляет кусок 2.5 с при minRhythm 4.09 с и клип отклоняется | HELPER_CONFIRMED | Trim → 2.5s < 4.09s min-rhythm → reject confirmed; ремонтируемый сосед NOT_VERIFIED | После trim короткий хвост должен быть исправим (merge или новый сосед) | INFERRED (потеря клипа при ремонте) | FIX_NOW | M230 (после arch review repair semantics) | Тест: post-trim short piece → repair-neighbor lookup; контрактно: не бросать клип без поиска | M225 `af35a30b7e522d344dcac41ce9c2b9e4b32ea8af` |
| #9a | `build_passage` прерывается при overlong `nxt`, не пробует `prv` | HELPER_CONFIRMED | Break при overlong nxt без fallback prv — подтверждено; CLI-финал NOT_REPRODUCED | `build_passage` должен продолжать искать prv, если nxt не подходит | INFERRED (seed пропускается без причины) | FIX_NOW | M229 | Тест: overlong nxt → passage использует prv eligible unit | M226 `e1be1b74cb033a8575d3967eceb8b06c3800f790` |
| #9b | `build_passage` достигает target на вопросе, удаляет вопрос post-loop, ответ не посещён | HELPER_CONFIRMED | Вопрос удалён после loop, ответ не рассмотрен — подтверждено; CLI-финал NOT_REPRODUCED | После удаления question unit passage должен доисследовать доступный answer | INFERRED (обрезанная история) | FIX_NOW | M230 | Тест: target-на-вопросе → ответный unit добавлен к passage | M226 `e1be1b74cb033a8575d3967eceb8b06c3800f790` |
| #10 | `hook_judge_top=6` обрезает 7-й hook-кандидат | INTENTIONAL | Параметр намеренный: бюджет вызовов LLM | Бюджет 6 — сознательное компромисс скорость/полнота | UNKNOWN (не измерено у пользователя) | NO_FIX_INTENTIONAL | — до измеренного impact | Тест: не требуется; параметр контролируется owner'ом | M222 static analysis |
| #11 | Невидимые отказы до пула; `teaser_misses` возвращает «прошла» при `glued_start`-отклонении `_hook_cands` | CLI_OUTPUT_GAP (manual accounting) + HELPER_CONFIRMED (teaser) + STATIC (weak-seed) | Map B: 2 eligible seeds → 1 proposal (gap=1 невидим); teaser discrepancy HELPER с synthetic start_pause; actual CLI no alignment; weak-seed static | Каждый seed attempt должен считаться; `teaser_misses` должна иметь те же проверки что `_hook_cands` | INFERRED (нет per-seed инструментации; реальный пользовательский эффект неизвестен) | INSTRUMENT_FIRST | M231 | Тест: per-stage счётчики (eligible/attempted/None/pool/selected); `teaser_misses` выдаёт ту же причину что `_hook_cands` при одинаковых callback | M227 `929646319dc55b5d6dc62f6321582bf20622cc09` |
| #12 | Tie-break зависит от входного порядка | HELPER_CONFIRMED (same input) + STATIC_INFERRED (order sensitivity) | Одинаковый упорядоченный вход даёт тот же результат повторяемо; `reversed([60,60,60])` = тот же массив; реальная перестановка ID не проверена | Tie-break при одинаковом счёте должен быть детерминирован через stable_id | NOT_RUNTIME_PROVEN как недетерминизм | NO_FIX_INTENTIONAL до подтверждённой перестановки | — | Тест: только если owner демонстрирует реальный case с другим результатом | M226 `e1be1b74cb033a8575d3967eceb8b06c3800f790` |

---

## Сводка действий

| Действие | Находки | Веха |
|----------|---------|------|
| FIX_NOW | #1, #2, #5, #8a, #9a | M229 |
| FIX_NOW (после arch gate M230) | #3, #7, #8b, #9b | M230 |
| INSTRUMENT_FIRST | #4, #6, #11 | M231 |
| NO_FIX_INTENTIONAL | #10, #12 | — |

**FIX_NOW:** 7 находок · **INSTRUMENT_FIRST:** 3 · **NO_FIX_INTENTIONAL:** 2

---

## Ограничения корпуса доказательств

- Ни одна находка не подтверждена до уровня реального рендера или измеренного пользовательского эффекта.
- #3, #6, #7, #8b, #9b, #11 имеют helper-уровень или статический уровень; production impact INFERRED.
- #4, #9a-b поздний CLI-финал NOT_REPRODUCED.
- `repro.exit` из M227 evidence.json отсутствует в published tree (отмечено Sol).
- Не смешивать `exit 0` REPRO-скрипта с доказанным production-конечным результатом.
