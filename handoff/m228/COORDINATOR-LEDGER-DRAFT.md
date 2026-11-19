# M228 — предварительный реестр 12 находок (НЕ итоговая приёмка)

Дата: 2026-11-19. Обновлено после независимых приёмок M223–M227. **Это рабочий реестр, M228 не начат и не получил Sol PASS.** Не использовать как разрешение на исправление кода.

База production: `main 3c011e94263e16e5780936b4769d3490cd03b682`. Диагностический M223 принят ограниченным Sol PASS: `handoff/m223/SOL-REVIEW-R5.md` (evidence pinned `9bb5667386b70ac93f041b8abb9f22359dbca286`). M224 R2 закрыт независимым **PASS_SCOPED** (evidence `d18627fb0fff56c4735b3c0462b1796337989715`, erratum `78511b42887b5be7070b8241d30e6d7556e20568`, acceptance `handoff/m224/SOL-REVIEW-R2-ACCEPTANCE.md`): CLI original-helper boundary подтверждён, итоговый Proposal и рендер не проверены.

| # | Приоритет | Что исследуем | На сегодня | Основание и незакрытый вопрос |
|---|---|---|---|---|
| 1 | P1 | `used_seeds/taken` забирает альтернативы | **Механизм CLI CONFIRMED; поздний медиа-отказ NOT_REPRODUCED** | M223 R5: u2-alone viable при тех же callbacks, отсутствует в пуле. Нет реального late-rejection |
| 2 | P1 | обходит `start_strict/answer_start/start_morph` | **CLI CONFIRMED в узкой области** | M223 R5: неправильная проверка body opener; фактический первый планируемый звук — hook |
| 3 | P1 | `clauses` не передан в `propose` | **CLI boundary + STATIC CONFIRMED; production impact NOT_REPRODUCED** | M223 R5: 6 вызовов `_hook_cands(clauses=None)`, helper-only candidate counterfactual |
| 4 | P2 | `select_global` до финального отказа | **SELECTOR_HELPER_CONFIRMED; LATE_REJECTION_NOT_REPRODUCED** | M226 Sol PASS_SCOPED: `select_global` выбирает B+C=120 против A=95 при реальных helper-функциях; поздний финальный отказ не проверялся |
| 5 | P2 | `min_sec` после `context_start` | **CLI_HELPER_BOUNDARY_CONFIRMED; FINAL_PROPOSAL_NOT_VERIFIED** | M224 R2 PASS_SCOPED: настоящий `cmd_autocut` с `generator=mixed`, `context_start` меняет 25→23 при `min_sec=25`; итоговые `Proposal.seconds/pieces` не были asserted |
| 6 | P2 | `refs` vs `t0/t1` после пауз | **CLI_HELPER_BOUNDARY_CONFIRMED; PLAYBACK_NOT_REPRODUCED** | M224 R2 PASS_SCOPED: original CLI helpers — t0 offset 0.4s, t1 offset 1.0s на синтетических выравнивании/просодии; реальные playback intervals не проверялись |
| 7 | P2 | `fit_rhythm` удаляет зависимую опору | **HELPER_CONFIRMED; CLI_FINAL_NOT_REPRODUCED** | M225 Stage A Sol PASS_SCOPED: оригинальный `propose` выдаёт [1,3] при `#3.refers=2`; CLI синтетический валидатор не принимает клип |
| 8 | P2 | ремонт ритма/конца оставляет вопрос или отбрасывает ремонтируемое | **HELPER_CONFIRMED; CLI_FINAL_NOT_REPRODUCED** | M225 Stage A Sol PASS_SCOPED: #8a `propose` выдаёт вопрос последним; #8b synthetic endtone trim оставляет 2.5s<4.09s и отклоняет; существование соседа для ремонта NOT_VERIFIED |
| 9 | P2 | `build_passage` преждевременно прерывает рост | **HELPER_CONFIRMED (A+B), CLI_FINAL_NOT_REPRODUCED** | M226 Sol PASS_SCOPED: A — overlong nxt вызывает break без попытки подходящего prv; B — достигнут target на вопросе, вопрос удалён post-loop и ответ не посещён |
| 10 | P2 | 7-й hook при бюджете 6 | **INTENTIONAL (budget), impact NOT MEASURED** | `hook_judge_top:6` — не исправлять без пользовательского эффекта |
| 11 | P2 | невидимые отказы до пула | **CLI_OUTPUT_GAP + MANUAL_ACCOUNTING; HELPER_TEASER_MISMATCH; STATIC weak-seed; impact NOT_REPRODUCED** | M227 Sol PASS_SCOPED, evidence `929646319dc55b5d6dc62f6321582bf20622cc09`, review `handoff/m227/SOL-REVIEW-STAGE-A.md`: map A 1→1, B 2 reconstructed eligible seeds→1 review proposal; exact CLI refusal reason not instrumented. `teaser_misses={'прошла':1}` против `_hook_cands=[]` только при synthetic `start_pause=0.05`; actual CLI без alignment. Отсутствует `repro.exit` в evidence manifest |
| 12 | P3 | tie-break зависит от входного порядка | **DETERMINISTIC_SAME_INPUT HELPER_CONFIRMED; ORDER_SENSITIVE STATIC_INFERRED_ONLY** | M226 Sol PASS_SCOPED: одинаковый упорядоченный вход повторяем; `reversed([60,60,60])` — тот же числовой массив, реальные permutations ID не проверены; это не недетерминизм |

## План закрытия без кругов

- **M224:** завершён `PASS_SCOPED`; старый `handoff/m224/repro_stdout.txt` от R1 отозван для R2; финальные предложения и рендер — `NOT_VERIFIED`/`NOT_REPRODUCED`. R3 запрещён стоп-правилом.
- **M225:** Sol независимый `PASS_SCOPED` по helper-результатам #7/#8a/#8b (`handoff/m225/SOL-REVIEW-STAGE-A.md`); параметры end_tone/start_pause_min для helper фиксур изменены, эффект реального CLI-финального результата NOT_REPRODUCED, возможность повторного ремонта #8b NOT_VERIFIED. Больше не повторять репро ради расширения формулировок.
- **M226:** Sol независимый `PASS_SCOPED` (`handoff/m226/SOL-REVIEW-STAGE-A.md`): CLI preflight M1 подтверждён, #4/#9 helper-only, F12 same-input deterministic, order sensitivity STATIC/INFERRED. Late rejection НЕ воспроизведён. Не повторять M226 ради расширения доказательств.
- **M227:** Sol независимый `PASS_SCOPED` (`handoff/m227/SOL-REVIEW-STAGE-A.md`) после независимого Python 3.12.14 rerun: 27/27, exit0. #11 accounting gap в CLI-выводе/ручной реконструкции, `build_passage None` helper, `teaser_misses` расхождение helper-only при синтетическом start_pause, weak-seed static. `repro.exit` в published tree отсутствует. Больше не повторять M227 ради расширения доказательств.
- **M228:** задача `handoff/m228/TASK-M228-R1.md` — синтез 12 статусов с уровнями доказательств, решения `FIX_NOW / INSTRUMENT_FIRST / NO_FIX_INTENTIONAL / NOT_REPRODUCED / DEFER`, архитектура и GO/NO-GO перед M229; независимый Sol QA обязателен.
- **M229–M236:** только затем менять production код; M230 — архитектурное ревью сильной моделью перед изменением `propose`; M237 — A/B с отдельным разрешением на модельные записи.

Ни один статус здесь не является гарантийным `PASS` незавершённой задачи. Это реестр неизвестного и проверенного.
