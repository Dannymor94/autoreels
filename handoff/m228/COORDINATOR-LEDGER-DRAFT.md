# M228 — предварительный реестр 12 находок (НЕ итоговая приёмка)

Дата: 2026-11-18. Подготовлено координатором до M224–M227. **Это рабочий реестр, M228 не начат и не получил Sol PASS.** Не использовать как разрешение на исправление кода.

База production: `main 3c011e94263e16e5780936b4769d3490cd03b682`. Диагностический M223 принят ограниченным Sol PASS: `handoff/m223/SOL-REVIEW-R5.md` (evidence pinned `9bb5667386b70ac93f041b8abb9f22359dbca286`). M224 опубликован как R1 на `727364e`, но координатор вернул CHANGES_REQUIRED за helper-only репро; M224-R2 ожидается.

| # | Приоритет | Что исследуем | На сегодня | Основание и незакрытый вопрос |
|---|---|---|---|---|
| 1 | P1 | `used_seeds/taken` забирает альтернативы | **Механизм CLI CONFIRMED; поздний медиа-отказ NOT_REPRODUCED** | M223 R5: u2-alone viable при тех же callbacks, отсутствует в пуле. Нет реального late-rejection |
| 2 | P1 | обходит `start_strict/answer_start/start_morph` | **CLI CONFIRMED в узкой области** | M223 R5: неправильная проверка body opener; фактический первый планируемый звук — hook |
| 3 | P1 | `clauses` не передан в `propose` | **CLI boundary + STATIC CONFIRMED; production impact NOT_REPRODUCED** | M223 R5: 6 вызовов `_hook_cands(clauses=None)`, helper-only candidate counterfactual |
| 4 | P2 | `select_global` до финального отказа | **PENDING / NOT TESTED** | M226: A/B/C и реальный acceptance path |
| 5 | P2 | `min_sec` после `context_start` | **HELPER CONFIRMED; CLI NOT_REPRODUCED** | M224 R1: `propose` с `generator=passage` даёт 23<25, настоящий CLI ещё не пройден |
| 6 | P2 | `refs` vs `t0/t1` после пауз | **HELPER CONFIRMED; CLI NOT_REPRODUCED** | M224 R1: 4s drift при ручных `sentences/end_tone`, без реального aligned CLI path |
| 7 | P2 | `fit_rhythm` удаляет зависимую опору | **STATIC HYPOTHESIS / NOT TESTED** | M225: `fit_rhythm` не проверяет сохранение `leans_on` после удаления, но CLI-достижимость не доказана |
| 8 | P2 | ремонт ритма/конца оставляет вопрос или отбрасывает ремонтируемое | **STATIC HYPOTHESIS / NOT TESTED** | M225: нет явного role guard при grow; финальный `rhythm_why` после `fix_open_end` без repair |
| 9 | P2 | `build_passage` преждевременно прерывает рост | **STATIC HYPOTHESIS / NOT TESTED** | M226: альтернативный сосед после неудачного pick, вопрос/ответ |
| 10 | P2 | 7-й hook при бюджете 6 | **INTENTIONAL (budget), impact NOT MEASURED** | `hook_judge_top:6` — не исправлять без пользовательского эффекта |
| 11 | P2 | невидимые отказы до пула | **PENDING / NOT TESTED** | M227: accounting и `teaser_misses` |
| 12 | P3 | tie-break зависит от входного порядка | **PENDING / NOT TESTED** | M226: тот же упорядоченный вход обязан совпадать; отличия при перестановке не означают недетерминизм |

## План закрытия без кругов

- **Sonnet M224-R2:** один точечный настоящий CLI-проход (либо честный `NOT_REPRODUCED` с доказанным блокером); no production fixes.
- **Sol:** независимый gate только для M224 с точной областью PASS; при невозможности перейти к эскалации по `QA-STOP-RULES.md`, а не к бесконечному R3.
- **M225–M227:** последовательно собрать доказательства и отмечать уровень; префлайт M225 уже подготовлен в `handoff/m225/COORDINATOR-PREFLIGHT.md`.
- **M228:** заменить этот черновик точными 12 статусами после Sol-гейтов и принять GO/NO-GO перед M229.
- **M229–M236:** только затем менять production код; M230 — архитектурное ревью сильной моделью перед изменением `propose`; M237 — A/B с отдельным разрешением на модельные записи.

Ни один статус здесь не является гарантийным `PASS` незавершённой задачи. Это реестр неизвестного и проверенного.
