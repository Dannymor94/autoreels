# M229-PREP — Детерминированные регрессионные контракты (9 подслучаев)

**База:** `main@3c011e94263e16e5780936b4769d3490cd03b682`  
**Источник:** принятые Sol-reviews M223–M227; синтез M228 `1207bda6ada5fd207abf93730c669816737169f7`  
**PRODUCTION_DIFF=NONE · M229_CODE_GO=NO**  
**Статус тестов:** SPECIFIED — не выполнены; fail-before/pass-after не могут быть утверждены до реализации.

---

## Соглашения

- **Fail-before:** поведение на baseline `3c011e94...` без изменений кода; где указано «наблюдено» — из принятых Sol-reviews.
- **Pass-after:** ожидаемый результат ТОЛЬКО после реализации, одобренной M230 arch review. Не является проверенным результатом.
- **NOT_YET_REPRODUCED:** принятых доказательств недостаточно для утверждения конкретного fail-before в коде.
- Все тесты используют только синтетические фикстуры; owner-данные запрещены.
- Существующий тест-сьют должен проходить на baseline без изменений.

---

## TC-1 — #1: `used_seeds/taken` подавляет независимо eligible альтернативу

| Поле | Значение |
|------|---------|
| **Test ID** | TC-1 |
| **Frozen source SHA** | `3c011e94263e16e5780936b4769d3490cd03b682` |
| **Функция** | `propose()` · `autocut.py:1175` |
| **Уровень доказательства** | CLI_CONFIRMED (bounded, M223) · M223 Sol R5 `9bb5667386b70ac93f041b8abb9f22359dbca286` |
| **Отличие от user impact** | Поздний медиа-отказ NOT_REPRODUCED; доказан только механизм перечисления |
| **Config keys** | `seed_punch=4`, `min_punch=3`, `generator=passage`, `passage_gap_sec=30` |
| **Синтетические единицы** | u1: id=1, t0=35, t1=75, role=conclusion, punch=5, topic=main, refs="1.1-2"; u2: id=2, t0=0, t1=30, role=conclusion, punch=5, topic=main, refs="2.1" (нет пересечения units с u1 clip) |
| **Fail-before** | При u1 уже в `used_seeds`, u2 (eligible alone, punch≥seed_punch) пропускается по условию `seed["id"] in used_seeds` на строке 1175; u2 не достигает пула |
| **Pass-after** | (Pending M230 design) u2 достигает пула как кандидат; финальный selected набор НЕ содержит обе сборки с пересечением units; overlap-dedup сохранён при selection |
| **Негативный тест** | Две сборки с пересекающимися units НЕ должны быть оба accepted; тест: `len({u for p in selected_clips for u in p.units} & overlap_units) == overlap_units` → reject |
| **Feature-off parity** | Без изменения в `generator=clip` режиме (не passage) — поведение идентично текущему |
| **Веха реализации** | M232 (после M230 arch approval); зависит от arch decision: N попыток и стоп-условие |
| **Semantic decision для M230** | Какое максимальное N bounded reattempt? Как dedup при selection? |

---

## TC-2 — #2: Body opener обходит `start_strict`/`answer_start`/`start_morph`

| Поле | Значение |
|------|---------|
| **Test ID** | TC-2 |
| **Frozen source SHA** | `3c011e94263e16e5780936b4769d3490cd03b682` |
| **Функция** | `propose()` → `context_start()` · `autocut.py:1208–1231`; `context_start:676` |
| **Уровень доказательства** | CLI_CONFIRMED (bounded synthetic CLI, M223) · M223 Sol R5 `9bb5667386b70ac93f041b8abb9f22359dbca286` |
| **Отличие от user impact** | Доказан в synthetic CLI-пути; реальный audio impact NOT_REPRODUCED |
| **Config keys** | `context_start=true`, `min_punch=3`, `generator=mixed` |
| **Синтетические единицы** | clip=[u1(role=thesis), u2(role=conclusion)]; sentences: u1.refs="1.1" → [("1.1", 25.0, 10, True, "Да, конечно.")]  (body opener — не стоит самостоятельно); u2.refs="2.1" → [("2.1", 4.0, 6, True, "Главная мысль здесь.")] |
| **Fail-before** | context_start возвращает clip с body opener «Да, конечно.»; stands_alone не блокирует — наблюдено как первый планируемый звук body opener в принятом M223 |
| **Pass-after** | (Pending M230) context_start отклоняет body opener; clip начинается с независимой фразы или отклонён |
| **Негативный тест** | Supported question-led loop НЕ должен блокироваться: clip=[q(role=question), u(role=conclusion)], q.refs→question sentence → passes context_start |
| **Feature-off parity** | `context_start=false` → no change |
| **Веха реализации** | M232 (после M230 arch approval) |
| **Semantic decision для M230** | Как различать body opener и question-loop opener? |

---

## TC-3 — #3: `clauses` не передан в `_hook_cands` из `propose`

| Поле | Значение |
|------|---------|
| **Test ID** | TC-3 |
| **Frozen source SHA** | `3c011e94263e16e5780936b4769d3490cd03b682` |
| **Функция** | `propose()` → `_hook_cands()` · `autocut.py:1281`; `__main__.py:8818-8820` (propose call без `clauses=`) |
| **Уровень доказательства** | CLI_HELPER_BOUNDARY + STATIC (M223) · M223 Sol R5 `9bb5667386b70ac93f041b8abb9f22359dbca286` |
| **Отличие от user impact** | Clause-rescue counterfactual HELPER_ONLY; production impact NOT_REPRODUCED |
| **Config keys** | `hook_clauses=true`, `hook_teaser=true` |
| **Синтетические единицы** | clip=[u1(role=thesis, punch=5)]; sentences: u1.refs="1.1" → длинная фраза (sec>6, whole_bad=False, complete=True); clauses callback: ("1.1", 1, 3, 2.5, "Конкретная мысль тут.") |
| **Fail-before (STATIC)** | `propose()` вызывает `_hook_cands(clip, sentences, p, start_pause)` на строке 1281 без `clauses=`. С `hook_clauses=true` и наличием clauses callback — clause-hook не найден. Статически подтверждено: `__main__.py:8818-8820` не передаёт `clauses=` в `propose` |
| **Pass-after** | (Pending M230 design) `propose` принимает `clauses` parameter; передаёт в `_hook_cands`; clause-hook найден при `hook_clauses=true` |
| **Негативный тест** | `hook_clauses=false` → `_hook_cands(clauses=None)` → поведение идентично текущему |
| **Feature-off parity** | `hook_clauses=false` → no change; `hook_clauses=true, clauses=None` → graceful degradation |
| **Веха реализации** | M232 (после M230 arch approval); **изменяет `propose` signature** |
| **Semantic decision для M230** | Нужно ли спасать hook через clause? Backward-compatible signature? |

---

## TC-5 — #5: `context_start` укорачивает 25.0→23.0 с при `min_sec=25`

| Поле | Значение |
|------|---------|
| **Test ID** | TC-5 |
| **Frozen source SHA** | `3c011e94263e16e5780936b4769d3490cd03b682` |
| **Функция** | `context_start()` · `autocut.py:676`; вызов из `propose:1209` |
| **Уровень доказательства** | CLI_HELPER_BOUNDARY (M224 R2) · `d18627fb0fff56c4735b3c0462b1796337989715`, erratum `78511b42887b5be7070b8241d30e6d7556e20568` |
| **Отличие от user impact** | 25→23 s наблюдено при реальном `cmd_autocut, generator=mixed`; итоговые `Proposal.seconds` и рендер NOT_VERIFIED |
| **Config keys** | `min_sec=25`, `context_start=true`, `generator=mixed` |
| **Синтетические единицы** | clip=[u1(t0=100, t1=125, refs="1.1-5")]; sentences: "1.1"→(sec=10, complete, standalone=False), "1.2"→(sec=15, complete, standalone=True); context_start drops sentence 1.1 → clip.t0=100+10=110 → dur=25-10=15 < 25; или более точная фикстура из M224 |
| **Fail-before** | context_start возвращает clip с dur=23.0 < min_sec=25.0; check после context_start отсутствует; наблюдено в M224 CLI-helper boundary |
| **Pass-after** | (Pending M230) После context_start: re-check `dur >= min_sec`; если нет — REJECTED с reason `dur_below_min_sec` |
| **Негативный тест** | Если context_start удаляет фразу и dur ≥ min_sec → NOT rejected (правильно пропускает) |
| **Feature-off parity** | `context_start=false` → no change |
| **Веха реализации** | M232 (после M230 arch approval); затрагивает `propose:1232` или `context_start` return |
| **Semantic decision для M230** | Где располагать re-check: внутри context_start или в propose после вызова? |

---

## TC-7 — #7: `fit_rhythm` удаляет unit, `refers` не удовлетворены

| Поле | Значение |
|------|---------|
| **Test ID** | TC-7 |
| **Frozen source SHA** | `3c011e94263e16e5780936b4769d3490cd03b682` |
| **Функция** | `fit_rhythm()` · `autocut.py:297`; вызов из `propose:1200`; финальный контракт Proposal |
| **Уровень доказательства** | HELPER_CONFIRMED (M225 Stage-A) · `af35a30b7e522d344dcac41ce9c2b9e4b32ea8af` |
| **Отличие от user impact** | `propose` helper выдаёт [1,3] при `#3.refers=2`; CLI synthetic validator не принимает клип; реальный несвязный клип NOT_REPRODUCED |
| **Config keys** | `rhythm=true`, `min_sec=25`, `passage=true` |
| **Синтетические единицы** | u1: id=1, t0=0, t1=30, refs="1.1-2"; u2: id=2, t0=30, t1=60, refs="2.1" (refers=1); u3: id=3, t0=65, t1=95, refs="3.1-2" (refers=2 → зависит от u2); fit_rhythm удаляет u2 по ритму → clip=[u1,u3]; u3.refers=2 не удовлетворён |
| **Fail-before** | `fit_rhythm` удаляет u2 (строка 331); clip=[u1,u3] с unsatisfied refers=2; финальный Proposal не содержит все refers — наблюдено в M225 |
| **Pass-after** | (Pending M230) После `fit_rhythm`: check что все `refers` clip'а удовлетворены; если нет — REJECTED с reason `unsatisfied_refers=[2]` |
| **Негативный тест** | clip с удалённым u2 → validator REJECTED; clip без удалений → validator passes |
| **Feature-off parity** | `rhythm=false` → fit_rhythm не вызывается; no change |
| **Веха реализации** | M232 (после M230 arch approval); требует refers-validator контракт |
| **Semantic decision для M230** | Где refers-check: в fit_rhythm или в финальном validators? |

---

## TC-8a — #8a: Последний unit `role=question`

| Поле | Значение |
|------|---------|
| **Test ID** | TC-8a |
| **Frozen source SHA** | `3c011e94263e16e5780936b4769d3490cd03b682` |
| **Функция** | `build_passage()` · `autocut.py:408`; `propose:1177` |
| **Уровень доказательства** | HELPER_CONFIRMED (M225 Stage-A) · `af35a30b7e522d344dcac41ce9c2b9e4b32ea8af` |
| **Отличие от user impact** | `propose` helper выдаёт [1,2,3] с question последним; CLI synthetic validator не принимает; реальный user clip NOT_REPRODUCED |
| **Config keys** | `generator=passage`, `min_sec=25`, `max_sec=90` |
| **Синтетические единицы** | u1: id=1, t0=0, t1=30, role=thesis, topic=main; u2: id=2, t0=30, t1=55, role=conclusion, topic=main; u3: id=3, t0=55, t1=85, role=question, topic=main; seed=u1; build_passage grows to [u1,u2,u3] since total < target_sec |
| **Fail-before** | `build_passage` возвращает [u1,u2,u3] с question последним; проверка на строке 408 не срабатывает когда question не является последним в промежуточном run; наблюдено в M225 |
| **Pass-after** | (Pending M230) `build_passage` или финальный validator: если last unit = question → trim до предыдущего valid unit или REJECTED; question-led loop (question ПЕРВЫМ) сохраняется |
| **Негативный тест** | clip с question ПЕРВЫМ (loop) → НЕ отклоняется |
| **Feature-off parity** | `loop=false` → question-loop path не используется; no change to question-last check |
| **Веха реализации** | M232 (после M230 arch approval) |
| **Semantic decision для M230** | Trim в build_passage или reject в финальном validator? |

---

## TC-8b — #8b: Post-trim short piece `< minRhythm`

| Поле | Значение |
|------|---------|
| **Test ID** | TC-8b |
| **Frozen source SHA** | `3c011e94263e16e5780936b4769d3490cd03b682` |
| **Функция** | `fit_rhythm()` · `autocut.py:333–334`; вызов из `propose:1200` |
| **Уровень доказательства** | HELPER_CONFIRMED (trim→reject) + NOT_VERIFIED (ремонтируемый сосед) · M225 `af35a30b7e522d344dcac41ce9c2b9e4b32ea8af` |
| **Отличие от user impact** | 2.5s piece < 4.09s min-rhythm — trim→reject подтверждён helper; repair neighbor NOT_VERIFIED |
| **Config keys** | `rhythm=true`, `jump_sec=4.0`, `min_sec=25` |
| **Синтетические единицы** | clip=[u1(t0=0,t1=30), u2(t0=35,t1=37.5), u3(t0=42,t1=72)]; u2 — piece длиной 2.5s < jump_sec; fit_rhythm пробует grow u2: нет eligible соседа; u2 не в keep={seed,payoff} → удаляет u2; dur([u1,u3])=62.5s ≥ min_sec → НЕ None; затем final rhythm_why check → 2.5s piece was removed but final clip passed (no short piece remaining) |
| **Fail-before** | При наличии short piece и отсутствии eligible соседа: fit_rhythm удаляет кусок (строка 331); clip продолжается; или отклоняет если dur < min_sec (строка 334); тихий drop без причины в логе — наблюдено M225 |
| **Pass-after** | (Pending M230 neighbor-contract) Если нет доказанного legal repair-соседа → REJECTED с logged reason `no_repair_neighbor`; не обещать recovery |
| **Негативный тест** | Если short piece может быть grown eligible соседом → НЕ отклоняется; logged reason = repair |
| **Feature-off parity** | `rhythm=false` → fit_rhythm не вызывается; no change |
| **Веха реализации** | M232 (после M230 arch approval; neighbor-contract NOT_VERIFIED) |
| **Semantic decision для M230** | Какой сосед легален? Контракт fail-closed vs repair? |

---

## TC-9a — #9a: `build_passage` break при overlong `nxt`, не пробует `prv`

| Поле | Значение |
|------|---------|
| **Test ID** | TC-9a |
| **Frozen source SHA** | `3c011e94263e16e5780936b4769d3490cd03b682` |
| **Функция** | `build_passage()` · `autocut.py:396–405` |
| **Уровень доказательства** | HELPER_CONFIRMED (M226 Stage-A) · `e1be1b74cb033a8575d3967eceb8b06c3800f790` |
| **Отличие от user impact** | Helper-confirmed; CLI final NOT_REPRODUCED |
| **Config keys** | `generator=passage`, `min_sec=25`, `max_sec=60`, `passage_gap_sec=30` |
| **Синтетические единицы** | seed: id=5, t0=50, t1=70, topic=main; nxt(id=6): t0=70, t1=140 (dur=70 > max_sec=60) → usable=False (dur overlong? no, usable checks topic/refs, not dur directly); **проблема**: nxt usable=True но `total + _dur(nxt) > max_sec` → break без попытки prv; prv(id=4): t0=25, t1=50 (dur=25) → total+25=45 ≤ 60 → usable, fit |
| **Fail-before** | При `total + _dur(nxt) > p.max_sec` → строка 405 `break`; prv не пробуется если nxt был предпочтён; run = [seed] → dur=20 < min_sec=25 → None; seed пропущен — наблюдено M226 |
| **Pass-after** | (Pending M230) При overlong nxt → continue loop (не break); prv пробуется; passage использует prv eligible unit; build_passage не None |
| **Негативный тест** | Если и nxt и prv overlong → build_passage None (правильно) |
| **Feature-off parity** | `generator=clip` → `build_clip` вызывается вместо `build_passage`; no change |
| **Веха реализации** | M232 (после M230 arch approval) |
| **Semantic decision для M230** | `break` vs `continue` при overlong — ожидаемое поведение? |

---

## TC-9b — #9b: Answer не посещён после удаления question post-loop

| Поле | Значение |
|------|---------|
| **Test ID** | TC-9b |
| **Frozen source SHA** | `3c011e94263e16e5780936b4769d3490cd03b682` |
| **Функция** | `build_passage()` · `autocut.py:384–413` |
| **Уровень доказательства** | HELPER_CONFIRMED (M226 Stage-A) · `e1be1b74cb033a8575d3967eceb8b06c3800f790` |
| **Отличие от user impact** | Helper-confirmed; answer extension — ГИПОТЕЗА, не mandated; CLI final NOT_REPRODUCED |
| **Config keys** | `generator=passage`, `target_sec=55`, `max_sec=90` |
| **Синтетические единицы** | seed=u1(role=thesis,t0=0,t1=30); nxt=u2(role=question,t0=30,t1=55) → total=55=target → loop exits; run[-1]=question → строка 408 pop → run=[u1]; dur=30 < min_sec=25? нет, 30 ≥ 25; nxt_answer=u3(role=conclusion,t0=55,t1=85) — не посещён |
| **Fail-before** | После post-loop trim question (строки 408-409): available answer unit u3 не посещается; run=[u1]; наблюдено M226 |
| **Pass-after** | (Pending M230 arch design) **ГИПОТЕЗА**: после удаления question — рассмотреть доступный answer; контракт pending arch approval «всегда ли?» |
| **Негативный тест** | Если нет available answer → build_passage возвращает run без попытки |
| **Feature-off parity** | Нет флага для #9b сейчас; флаг `passage_extend_after_q` — гипотеза |
| **Веха реализации** | M232 (после M230 arch approval; answer extension — semantic decision) |
| **Semantic decision для M230** | Всегда ли добавлять answer? Только certain roles? Это mandated repair или optional? |

---

## Матрица покрытия

| Test ID | Функция | Строки | Уровень | Fail-before | Pass-after | Semantic decision? |
|---------|---------|--------|---------|-------------|------------|-------------------|
| TC-1 | propose | 1175 | CLI_CONFIRMED | Наблюдено (M223) | Pending M230 | Да (bounded N) |
| TC-2 | propose→context_start | 1208 | CLI_CONFIRMED | Наблюдено (M223) | Pending M230 | Да (opener detection) |
| TC-3 | propose→_hook_cands | 1281; main:8818 | CLI_HB+STATIC | STATIC (sig) | Pending M230 | Да (clause rescue) |
| TC-5 | propose→context_start | 1209; cs:699+ | CLI_HB | Наблюдено (M224) | Pending M230 | Да (re-check location) |
| TC-7 | propose→fit_rhythm | 1200; fr:331 | HELPER | Наблюдено (M225) | Pending M230 | Да (refers validator) |
| TC-8a | build_passage/propose | 408; p:1177 | HELPER | Наблюдено (M225) | Pending M230 | Да (trim vs reject) |
| TC-8b | propose→fit_rhythm | 1200; fr:333 | HELPER | Наблюдено (M225) | Pending M230 | Да (neighbor contract) |
| TC-9a | build_passage | 405 | HELPER | Наблюдено (M226) | Pending M230 | Да (break vs continue) |
| TC-9b | build_passage | 408–413 | HELPER | Наблюдено (M226) | Pending M230 | Да (answer extension) |

---

## Контракты #4/#6/#11 (INSTRUMENT_FIRST — не FIX_NOW)

Эти три находки не имеют fail-before тест-строк в данном реестре — они observational:

- **#4** (`select_global`): добавить счётчик `selected→accepted` в M231; failing case NOT_REPRODUCED.
- **#6** (t0/t1 delta): добавить delta-лог в M231 на синтетике; playback impact NOT_REPRODUCED.
- **#11** (per-seed counters): добавить JSON-line stage counters в M231; `teaser_misses` выравнивание — pending M230.
