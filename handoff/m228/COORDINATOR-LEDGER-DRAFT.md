# M228 — предварительный реестр 12 находок (НЕ итоговая приёмка)

Дата: 2026-11-18. Подготовлено координатором до M224–M227. **Это рабочий реестр, M228 не начат и не получил Sol PASS.** Не использовать как разрешение на исправление кода.

База production: `main 3c011e94263e16e5780936b4769d3490cd03b682`. Диагностический M223 принят ограниченным Sol PASS: `handoff/m223/SOL-REVIEW-R5.md` (evidence pinned `9bb5667386b70ac93f041b8abb9f22359dbca286`). M224 R2 закрыт независимым **PASS_SCOPED** (evidence `d18627fb0fff56c4735b3c0462b1796337989715`, erratum `78511b42887b5be7070b8241d30e6d7556e20568`, acceptance `handoff/m224/SOL-REVIEW-R2-ACCEPTANCE.md`): CLI original-helper boundary подтверждён, итоговый Proposal и рендер не проверены.

| # | Приоритет | Что исследуем | На сегодня | Основание и незакрытый вопрос |
|---|---|---|---|---|
| 1 | P1 | `used_seeds/taken` забирает альтернативы | **Механизм CLI CONFIRMED; поздний медиа-отказ NOT_REPRODUCED** | M223 R5: u2-alone viable при тех же callbacks, отсутствует в пуле. Нет реального late-rejection |
| 2 | P1 | обходит `start_strict/answer_start/start_morph` | **CLI CONFIRMED в узкой области** | M223 R5: неправильная проверка body opener; фактический первый планируемый звук — hook |
| 3 | P1 | `clauses` не передан в `propose` | **CLI boundary + STATIC CONFIRMED; production impact NOT_REPRODUCED** | M223 R5: 6 вызовов `_hook_cands(clauses=None)`, helper-only candidate counterfactual |
| 4 | P2 | `select_global` до финального отказа | **PENDING / NOT TESTED** | M226: A/B/C и реальный acceptance path |
| 5 | P2 | `min_sec` после `context_start` | **CLI_HELPER_BOUNDARY_CONFIRMED; FINAL_PROPOSAL_NOT_VERIFIED** | M224 R2 PASS_SCOPED: настоящий `cmd_autocut` с `generator=mixed`, `context_start` меняет 25→23 при `min_sec=25`; итоговые `Proposal.seconds/pieces` не были asserted |
| 6 | P2 | `refs` vs `t0/t1` после пауз | **CLI_HELPER_BOUNDARY_CONFIRMED; PLAYBACK_NOT_REPRODUCED** | M224 R2 PASS_SCOPED: original CLI helpers — t0 offset 0.4s, t1 offset 1.0s на синтетических выравнивании/просодии; реальные playback intervals не проверялись |
| 7 | P2 | `fit_rhythm` удаляет зависимую опору | **HELPER_CONFIRMED; CLI_FINAL_NOT_REPRODUCED** | M225 Stage A Sol PASS_SCOPED: оригинальный `propose` выдаёт [1,3] при `#3.refers=2`; CLI синтетический валидатор не принимает клип |
| 8 | P2 | ремонт ритма/конца оставляет вопрос или отбрасывает ремонтируемое | **HELPER_CONFIRMED; CLI_FINAL_NOT_REPRODUCED** | M225 Stage A Sol PASS_SCOPED: #8a `propose` выдаёт вопрос последним; #8b synthetic endtone trim оставляет 2.5s<4.09s и отклоняет; существование соседа для ремонта NOT_VERIFIED |
| 9 | P2 | `build_passage` преждевременно прерывает рост | **STATIC HYPOTHESIS / NOT TESTED** | M226: альтернативный сосед после неудачного pick, вопрос/ответ |
| 10 | P2 | 7-й hook при бюджете 6 | **INTENTIONAL (budget), impact NOT MEASURED** | `hook_judge_top:6` — не исправлять без пользовательского эффекта |
| 11 | P2 | невидимые отказы до пула | **PENDING / NOT TESTED** | M227: accounting и `teaser_misses` |
| 12 | P3 | tie-break зависит от входного порядка | **PENDING / NOT TESTED** | M226: тот же упорядоченный вход обязан совпадать; отличия при перестановке не означают недетерминизм |

## План закрытия без кругов

- **M224:** завершён `PASS_SCOPED`; старый `handoff/m224/repro_stdout.txt` от R1 отозван для R2; финальные предложения и рендер — `NOT_VERIFIED`/`NOT_REPRODUCED`. R3 запрещён стоп-правилом.
- **Sonnet M225 Stage A:** задача подготовлена в `handoff/m225/TASK-M225-R1.md`; после PASS можно собирать новый диагностический CLI-пакет без production fixes.
- **M225:** Sol независимый `PASS_SCOPED` по helper-результатам #7/#8a/#8b (`handoff/m225/SOL-REVIEW-STAGE-A.md`); параметры end_tone/start_pause_min для helper фиксур изменены, эффект реального CLI-финального результата NOT_REPRODUCED, возможность повторного ремонта #8b NOT_VERIFIED. Больше не повторять репро ради расширения формулировок.
- **M226–M227:** последовательно собрать новые доказательства с заранее установленной границей CLI/HELPER/NOT_REPRODUCED.
- **M228:** заменить этот черновик точными 12 статусами после Sol-гейтов и принять GO/NO-GO перед M229.
- **M229–M236:** только затем менять production код; M230 — архитектурное ревью сильной моделью перед изменением `propose`; M237 — A/B с отдельным разрешением на модельные записи.

Ни один статус здесь не является гарантийным `PASS` незавершённой задачи. Это реестр неизвестного и проверенного.
