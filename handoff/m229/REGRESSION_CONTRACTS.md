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
| **Функция** | `propose()` · `autocut.py:1175`; `used_seeds.update` на строке 1262 |
| **Уровень доказательства** | CLI_CONFIRMED (bounded, M223) · M223 Sol R5 `9bb5667386b70ac93f041b8abb9f22359dbca286` |
| **Отличие от user impact** | Поздний медиа-отказ NOT_REPRODUCED; доказан только механизм перечисления |
| **Config keys** | `generator=passage`, `passage_gap_sec=30`, `min_sec=25`, `target_sec=55` |
| **Синтетические единицы** | u1: id=1, t0=40.0, t1=69.5, role=thesis, topic=A, punch=5, refs="1.1-4"; u2: id=2, t0=80.0, t1=108.0, role=conclusion, topic=A, punch=4, refs="2.1-4". Оба — одна тема; gap=10.5s < passage_gap_sec=30 → build_passage объединяет в один clip [u1,u2]. После принятия clip=[u1,u2]: `used_seeds.update({1,2})` (оба STORY roles). При следующей итерации seeds: `seed["id"]=2 in used_seeds → continue`. Принято из M223 §4-c, §4-d, §4-g |
| **Fail-before** | u1+u2 объединяются в clip, принимаются; u2.id попадает в used_seeds (строка 1262); u2-alone (eligible, punch≥seed_punch, те же callbacks — доказано в M223 §4-d) НИКОГДА не попадает в пул. Наблюдено M223 §4-g |
| **Pass-after** | (Pending M230 design) u2 достигает пула как отдельный кандидат; финальные accepted clips НЕ содержат пересечений units (overlap-dedup сохранён при selection) |
| **Негативный тест** | Финальный accepted набор не содержит двух proposals с пересекающимися units: `assert not any(set(a.units) & set(b.units) for a, b in combinations(accepted, 2))` (список `Proposal.units` — `list[int]`) |
| **Feature-off parity** | `generator=clip` → `build_clip` вместо `build_passage`; `used_seeds` заполняется по той же логике; pass-after design — отдельный вопрос |
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
| **Config keys** | `context_start=true`, `min_punch=3`, `generator=mixed`, `start_strict=true`, `answer_start=true`, `start_morph=true`; M223 bounded CLI used this strict triplet |
| **Синтетические единицы** | FX-2 is a new NOT_EXECUTED blueprint: clip A u1.refs="1.1-3" → [("1.1",3.0,...,"Да, конечно."), ("1.2",11.0,...), ("1.3",11.0,...)]; negative clip B question-first. The *accepted M223 CLI witness* used body 1.1 "Да, тревога..." and a hook 2.1 (teaser on) or 1.2 (teaser off); do not equate the proposed FX-2 callback with the executed M223 witness. |
| **Fail-before** | M223 bounded CLI observed body 1.1 "Да, тревога..." retained despite strict flags and answer_start_reason rejecting it: stands_alone checks back_reference but not answer_start_reason. The FIRST planned audible item was hook 2.1 (teaser on) or hook 1.2 (teaser off), **not** the body opener. FX-2 replay remains SPECIFIED_NOT_EXECUTED. |
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
| **Уровень доказательства** | CLI_HELPER_BOUNDARY (propose→main) + STATIC (propose→_hook_cands) + HELPER (clause counterfactual reachable at _hook_cands) · M223 Sol R5 `9bb5667386b70ac93f041b8abb9f22359dbca286` |
| **Отличие от user impact** | Clause-rescue counterfactual HELPER_ONLY; production impact NOT_REPRODUCED |
| **Config keys** | `hook_clauses=true`, `hook_teaser=false` (teaser=false устраняет fraction-фильтр в _hook_cands:1020-1021 до clause-ветки), `hook_max_sec=6` |
| **Синтетические единицы** | clip=[u1(role=thesis, punch=5, t0=0, t1=60)]; sentences: u1.refs="1.1" → длинная фраза (sec=35.0 > hook_max_sec=6 → целиком не подходит как hook); clauses callback: ("1.1", 2, 3, 3.0, "Конкретная мысль тут.") — clause доступен через branch clauses≠None |
| **Fail-before (STATIC)** | `propose()` вызывает `_hook_cands(clip, sentences, p, start_pause)` на строке 1281 без `clauses=`. Clause branch в `_hook_cands` недостижим: `clauses=None` → clause not evaluated. STATIC: `__main__.py:8818-8820` не передаёт `clauses=` в `propose`; `clauses` callback (line 8701-8710) строится но не передаётся |
| **Fail-before (HELPER)** | Прямой вызов `_hook_cands(clip, sentences, p, start_pause=None, clauses=None)` возвращает 0 candidates; `_hook_cands(…, clauses=clauses_cb)` возвращает ≥1 — HELPER_ONLY (candidate-loss comparison) |
| **Pass-after** | (Pending M230 design + owner decision) `propose` принимает `clauses` parameter; передаёт в `_hook_cands`; clause-hook найден при `hook_clauses=true` |
| **Негативный тест** | `hook_clauses=false` → `_hook_cands(clauses=None)` → поведение идентично текущему |
| **Feature-off parity** | `hook_clauses=false` → no change; `hook_clauses=true, clauses=None` → graceful degradation |
| **Веха реализации** | M232 (после M230 arch approval); **изменяет `propose` signature** |
| **Semantic decision для M230** | Нужно ли спасать hook через clause? (Owner decision) Backward-compatible signature? |

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
| **Синтетические единицы** | FX-5 blueprint (NOT_EXECUTED): u1 [100,125] refs="1.1-2"; sentence 1.1 length=2.0s, context_drop_words=5, 1.2 length=23.0s; after dropping 1.1: t0=102, duration 25→23. Accepted M224 bounded CLI-helper observed 25→23; exact newly specified FX-5 has not been replayed. |
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
| **Уровень доказательства** | HELPER_CONFIRMED (M225 Stage-A Case A) · `af35a30b7e522d344dcac41ce9c2b9e4b32ea8af` |
| **Отличие от user impact** | `propose` helper выдаёт [1,3] при `#3.refers=2`; CLI synthetic validator не принимает клип (exit 0, zero proposals); реальный несвязный клип NOT_REPRODUCED |
| **Config keys** | Принятые production params из M225 (r0.yaml SHA `efdef3adb...`); `start_pause_min=0.0`, `end_tone=False` (как в M225 Case A fixture) |
| **Синтетические единицы** | u1: id=1, t0=50.0, t1=76.0, role=thesis, topic=A, punch=5, refs="1.1", standalone=True; u2: id=2, t0=90.0, t1=95.0, role=explanation, topic=A, punch=4, refs="1.1", standalone=False, **refers=1** (int); u3: id=3, t0=160.0, t1=193.0, role=conclusion, topic=A, punch=5, refs="1.1", standalone=False, **refers=2** (int). Gap(u1→u2)=14s; u2 dur=5s — short piece (settle_need(14)×1.0≈6.22 → 5<6.22 → fit_rhythm drops); add_payoff includes u3 (u3.refers=2 ∈ ids). Принято из M225 Case A |
| **Fail-before** | `add_payoff` добавляет u3 (refers=2 ∈ clip-ids); `fit_rhythm` удаляет u2 (5s < settle_need threshold, строка 331); clip=[u1,u3]; u3.refers=2 (u2) не удовлетворён — HELPER_CONFIRMED M225 Case A |
| **Pass-after** | (Pending M230) После `fit_rhythm`: check что все `refers` clip'а удовлетворены; если нет — REJECTED с reason `unsatisfied_refers=[2]` |
| **Негативный тест** | clip=[u1,u2,u3] без удалений → refers=2 удовлетворён → НЕ отклоняется |
| **Feature-off parity** | `rhythm=false` → fit_rhythm не вызывается; no change |
| **Веха реализации** | M232 (после M230 arch approval); требует refers-validator контракт |
| **Semantic decision для M230** | Где refers-check: в fit_rhythm или в финальном validators? |

---

## TC-8a — #8a: Последний unit `role=question` (добавлен `fit_rhythm`)

| Поле | Значение |
|------|---------|
| **Test ID** | TC-8a |
| **Frozen source SHA** | `3c011e94263e16e5780936b4769d3490cd03b682` |
| **Функция** | `fit_rhythm()` · `autocut.py:297` (растит короткий piece соседом-question); `propose:1200` |
| **Уровень доказательства** | HELPER_CONFIRMED (M225 Stage-A Case B) · `af35a30b7e522d344dcac41ce9c2b9e4b32ea8af` |
| **Отличие от user impact** | `propose` helper выдаёт proposal с question-last; CLI synthetic validator не принимает; реальный user clip NOT_REPRODUCED. **Question-first (loop-pattern) остаётся законным** — строки 1270, 1298 |
| **Config keys** | Принятые production params из M225; `start_pause_min=0.0`, `end_tone=False` |
| **Синтетические единицы** | u1: id=1, t0=50.0, t1=76.0, role=thesis, topic=A, punch=5; u2: id=2, t0=90.0, t1=93.0, role=conclusion, topic=A, punch=4 (dur=3s — short piece); u3: id=3, t0=94.0, t1=119.0, role=question, topic=A, punch=5 (dur=25s > loop_max_sec → loop_question пропускает; fit_rhythm растит piece1=[u2] соседом u3: gap=1s ≤ jump_sec, same topic). **Механизм: fit_rhythm appends question u3** (не build_passage loop). Принято из M225 Case B |
| **Fail-before** | build_passage возвращает [u1,u2]; `fit_rhythm` растит short piece u2 добавляя u3 (question) → clip=[u1,u2,u3] с question ПОСЛЕДНИМ; `propose` выдаёт proposal с question-last — HELPER_CONFIRMED M225 Case B |
| **Pass-after** | (Pending M230) Если last unit = question → trim до предыдущего valid unit или REJECTED; question-first (loop) НЕ затрагивается |
| **Негативный тест** | clip=[q(role=question), u(role=conclusion)] — question ПЕРВЫМ → НЕ отклоняется (loop-pattern законен) |
| **Feature-off parity** | `rhythm=false` → fit_rhythm не вызывается; вопрос о question-last detection в baseline остаётся отдельным |
| **Веха реализации** | M232 (после M230 arch approval) |
| **Semantic decision для M230** | Trim в fit_rhythm или в финальном validator после fit_rhythm? |

---

## TC-8b — #8b: `fix_open_end` обрезает → `rhythm_why` отклоняет

| Поле | Значение |
|------|---------|
| **Test ID** | TC-8b |
| **Frozen source SHA** | `3c011e94263e16e5780936b4769d3490cd03b682` |
| **Функция** | `fix_open_end()` · `autocut.py:625`; `rhythm_why` финальная проверка (`propose:1250`); нет повторного `fit_rhythm` после обрезки |
| **Уровень доказательства** | HELPER_CONFIRMED (fix_open_end trim → rhythm_why reject) + NOT_VERIFIED (ремонтируемый сосед) · M225 Stage-A Case C · `af35a30b7e522d344dcac41ce9c2b9e4b32ea8af` |
| **Отличие от user impact** | fix_open_end trim → rhythm reject подтверждён helper; repair neighbor NOT_VERIFIED; реальный playback impact NOT_REPRODUCED |
| **Config keys** | `end_tone=true`, `rhythm=true`, `start_pause_min=0.0`; production params из M225 |
| **Синтетические единицы** | u1: id=1, t0=50.0, t1=76.0, role=thesis, topic=A, punch=5, refs="1.1", standalone=True; u2: id=2, t0=126.0, t1=157.0, role=conclusion, topic=A, punch=5, refs="2.1-2", standalone=True. Sentences u2: ("2.1", 1.5s, final), ("2.2", 28.5s, open-tone) → fix_open_end обрезает open-tone: new u2.t1=128.5, dur=2.5s. Gap(u1→u2)=50s → settle_need×tail≈4.09s; dur=2.5 < 4.09 → rhythm_why REJECTS. Принято из M225 Case C |
| **Fail-before** | fix_open_end обрезает u2.t1 → 128.5; финальный rhythm_why (propose:1250) REJECTS clip; rejection записывается в `rhythm_out`; `open_end` пуст (fix_open_end trimmed, не gave up) — HELPER_CONFIRMED M225 Case C: `len(proposals)==0, bool(rhythm_out)==True, bool(open_end)==False` |
| **Pass-after** | (Pending M230 neighbor-contract decision) ARCH_QUESTION: возможен ли recovery-путь (re-attempt fit_rhythm или repair neighbor после trim)? Без одобрения arch — fail-closed |
| **Негативный тест** | Clip с заканчивающимся на final tone → fix_open_end НЕ обрезает → rhythm_why passes → proposal генерируется |
| **Feature-off parity** | `end_tone=false` → fix_open_end не вызывается; no change |
| **Веха реализации** | M232 (после M230 arch approval; neighbor-contract NOT_VERIFIED) |
| **Semantic decision для M230** | Нужен ли recovery path после fix_open_end trim? Какой сосед легален? |

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
| **Pass-after** | (ARCH_QUESTION — pending M230) `break→continue` небезопасен без спецификации bounded termination и альтернативной стратегии: при множестве overlong nxt может зациклиться. Дизайн pending M230 arch review |
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
| TC-8a | propose→fit_rhythm | 1200; fr:297–326 | HELPER | Наблюдено (M225) | Pending M230 | Да (question-last repair) |
| TC-8b | propose→fix_open_end→rhythm_why | 1239; fo:625; ry:273/1250 | HELPER | Наблюдено (M225, rhythm_out logged) | Pending M230 | Да (post-trim recovery) |
| TC-9a | build_passage | 405 | HELPER | Наблюдено (M226) | Pending M230 | Да (break vs continue) |
| TC-9b | build_passage | 408–413 | HELPER | Наблюдено (M226) | Pending M230 | Да (answer extension) |

---

## Контракты #4/#6/#11 (INSTRUMENT_FIRST — не FIX_NOW)

Эти три находки не имеют fail-before тест-строк в данном реестре — они observational:

- **#4** (`select_global`): добавить счётчик `selected→accepted` в M231; failing case NOT_REPRODUCED.
- **#6** (t0/t1 delta): добавить delta-лог в M231 на синтетике; playback impact NOT_REPRODUCED.
- **#11** (per-seed counters): добавить JSON-line stage counters в M231; `teaser_misses` выравнивание — pending M230.
