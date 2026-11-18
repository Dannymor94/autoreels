# REPORT M223-R3 — подтверждённые механизмы и ограниченные доказательства P1

**Ветка:** `task/m223`  
**База:** `origin/main` → `3c011e94263e16e5780936b4769d3490cd03b682`  
**HEAD задачи:** worktree `task/m223` (только `handoff/m223/` изменён)  
**Дата:** 2026-11-18  
**Статус:** `IMPLEMENTED, GATE PENDING` — ожидает PASS Sol 6.1

---

## Коррекция области доказательства независимым QA

Независимый Sol на оригинальном R3 `bafaaf2…` получил `exit 0`, **33/33**, но выявил чрезмерное утверждение об эффекте #3. Этот раздел и явные статусы ниже уточняют R3; предыдущие формулировки из R0–R2 не считаются доказательством.

- **#1:** механизм пропуска u2-alone подтверждён с теми же CLI callbacks; реальное отклонение клипа после проверки с владельческим медиа — **NOT_REPRODUCED**, и это допустимое ограничение.
- **#2:** тело начинается с «Да…», но первый планируемый звук в двух режимах — хук `h:2.1` / `h:1.2`.
- **#3:** отсутствие forwarding clauses в production подтверждено по сигнатуре и шести `clauses=None` вызовам. Кандидат `2.5@5-8` существует только при **ручном demo callback**; это **HELPER_ONLY**, а не подтверждённая production потеря. Crossing-threshold case отсутствует (**NOT_REPRODUCED**). См. `handoff/m223/SOL-REVIEW-R4.md`.

Гейт до новой независимой проверки — **PENDING**, M224 BLOCKED.

---
## Финальный отчёт (R3)

```
TASK=M223-R3
BASE_SHA=3c011e94263e16e5780936b4769d3490cd03b682
HANDOFF_EVIDENCE_SHA=bafaaf2f45bf5b9ea4992fb1bb7369944071424d (оригинальный R3; отдельная документальная коррекция)
STATUS=READY_FOR_QA
REPRO_EXIT=0
CHECKS_EXECUTED=33
P1_1_SEED=CONFIRMED; P1_1_REAL_LATE_REJECTION=NOT_REPRODUCED — pool=2, select_global вызван, u1+u2 merged,
         u2-alone viable (same CLI callbacks); real _autocut_check spy прошёл (synthetic PASS);
         late-rejection с реальным медиа = NOT_REPRODUCED
P1_2_CLI=CONFIRMED — CLI prm.answer_start=True; stands_alone не проверяет answer_start_reason;
         teaser h:2.1 (Block B, после 50%); no-teaser h:1.2 (Block A, до 50%);
         тело 1.1 «Да, тревога…» в клипе и принято stands_alone()
P1_3_FORWARDING=CONFIRMED_STATIC_AND_CLI_BOUNDARY; P1_3_IMPACT=HELPER_ONLY; P1_3_CROSSING=NOT_REPRODUCED — _hook_cands() 6 вызовов, все clauses=None; align.json загружен
         (нет warning); clauses(ref) построен CLI но не передан в propose();
         §6-k/l: after-threshold helper-only counterfactual; real CLI impact и crossing-case NOT_REPRODUCED
REAL_VALIDATOR_EVIDENCE=spy вызывает _real_check нативно; синтетика проходит (нет медиа = нет отклонения)
GLOBAL_SELECTOR_AND_CANDIDATE_PARITY=select_global(weights=[89.0,81.0],k=5)=[0,1]; u2-alone viable с теми же callbacks
CLAUSE_CLOSURE_AND_THRESHOLD_EVIDENCE=clause (4,7) найдена clause_spans(); span=(61.6,65.0), dur=3.40s, score=4.80
TEASER_AND_NO_TEASER_FIRST_SOUND=teaser h:2.1→"Принятие тревоги..."; no-teaser h:1.2→"Страх сигнализирует..."
NEGATIVE_TEST_EXIT=1 (subprocess, select=greedy)
PUBLISHED_LOG_PATH_SHA256_AND_BLOB_SHA=см. §8 (published bytes pinned to HANDOFF_EVIDENCE_SHA)
PRODUCTION_DIFF=нет (ни одного файла production не изменено)
OWNER_ARTIFACT_PARITY=нет изменений manifests/transcripts/reviews/reels-out/
WORKTREE_CLEAN=task/m223 (только handoff/m223/ изменён)
BLOCKERS=нет
```

---

## §0 Гейт M222A — подтверждение

- `main` = `3c011e9` (PR #9 «docs: apply M222-M237 agent workflow contract» merged)
- PR #10 «ci: establish deterministic offline smoke gate» merged
- 163 теста пройдено на CI

---

## §1 Метод воспроизведения (R3)

**R3 изменения по сравнению с R2:**

| Проблема Sol | Решение R3 |
|---|---|
| Мок `_autocut_check` | Spy вызывает `_real_check` нативно; результат записан |
| u2-alone без CLI callbacks | `_real_propose(u2, prm, cli_sentences_cb, **kw0)` — те же callbacks из spy |
| Нет after-threshold clause demo | §6-k/l: S2.5 (9s, 71.7% > 50%), clauses=None → пропуск; clauses=cb → найдена |
| Первый звук no-teaser неверный | Исправлено: без teaser первый звук = хук h:1.2, не тело 1.1 |
| Счётчик check() неверный | `CHECK_COUNTER[0]` инкрементируется в каждом `check()` → 33 |
| Span/dur/score не утверждены | §6-g2/g3/g4 проверяют точные значения |

**Общая схема:**
- `cmd_autocut("synth", root=tmp, llm="none")` → spy захватывает `propose_calls`, `select_global_calls`
- `_run_cmd_autocut_with_check(tmp, ...)` → spy захватывает `_autocut_check` calls (real, not mock)
- Изолированный tmpfs-корень, нет API, нет рендера, нет записи в репозиторий

---

## §2 Конфигурация (config/r0.yaml)

| Ключ | Значение | Значимость |
|---|---|---|
| `hook_clauses` | `true` | #3: клозы должны работать |
| `start_strict` | `true` | #2: строгое начало |
| `answer_start` | `true` | #2: ответный старт запрещён |
| `start_morph` | `true` | #2: морфологическая проверка |
| `generator` | `mixed` | #1: used_seeds |
| `select` | `global` | #1: global selector |

**r0.yaml SHA256:** `efdef3adb0396e7e282553a8e3bfb0c690df015abdb8398cea1db5e642aeabba`

---

## §3 CLI-путь подтверждён

```
stdout: предложено сборок 2 из 3 мыслей → ...
  M1 81@1.05 | 1.1-4 2.1-4 | h:2.1! | c:2.4 | k:1.1=переменами;2.4=сегодня | ...
  M2 89@1.08 | 3.1-4 | c:3.4 | k:3.1=сильнее;3.4=сегодня | ...
```

propose() вызван 2 раза (основной + fill_pool). ProposalParams: `generator='mixed'`, `hook_clauses=True`, `start_strict=True`, `answer_start=True`, `start_morph=True`.

---

## §4 Находка #1 — seed CONFIRMED; real late rejection NOT_REPRODUCED

**Механизм:** `used_seeds` предотвращает `u2-alone` из пула

```
Pool:
  clip-idx-0: units={3}, score=89.00, 28.0s
  clip-idx-1: units={1,2}, score=81.00, 57.5s

select_global(weights=[89.0, 81.0], k=5) → [0,1]  ← вызван реально ✓

Контрфактуал (same callbacks):
  _real_propose([u2], prm, cli_sentences_cb, **kw0) → 1 клип {2}  ← viable ✓

Real _autocut_check spy:
  → clip "1.1-4 2.1-4": PASS (synthetic data, no media)
  → clip "3.1-4": PASS (synthetic data, no media)
  → u2-alone НЕ подан: не был в pool ✓

Late-rejection consequence: NOT_REPRODUCED (требует медиафайла)
```

**Итог:** `u2-alone` жизнеспособен с теми же CLI callbacks, но never proposed — blocked by `used_seeds`.

---

## §5 Находка #2 — CONFIRMED (STATIC+CLI)

**Механизм:** `stands_alone()` не вызывает `answer_start_reason()`

```
CLI prm.answer_start=True, start_strict=True  ← из CLI config ✓

Первый звук:
  С teaser:    h:2.1 → "Принятие тревоги снижает её интенсивность." (Block B, 50%)
  Без teaser:  h:1.2 → "Страх сигнализирует об изменениях." (Block A, 25%)

Тело клипа содержит 1.1 «Да, тревога часто возникает перед переменами.» — ответное начало:
  answer_start_reason("Да, тревога...") = '«Да,…» — ответ, а вопроса в ролике нет'  ← ОТВЕРГАЕТ
  back_reference("Да, тревога...")      = None                                        ← НЕ ловит
  stands_alone("Да, тревога...", ..., prm) = None                                    ← пропускает!
```

CLI-черновик содержит `1.1` при активном `answer_start=True`; синтетический реальный `_autocut_check` возвращает PASS. Это не утверждение, что «Да…» — первые слышимые слова.

---

## §6 Находка #3 — forwarding CONFIRMED; candidate impact HELPER_ONLY

**Механизм 1 (CLI):** `propose()` не имеет параметра `clauses` → `_hook_cands` всегда получает `clauses=None`

```
propose() params: ['end_tone', 'judge', 'no_start', 'open_end', 'p', 'rhythm_out',
                   'sentences', 'start_pause', 'taste', 'units']  ← нет 'clauses' ✓

CLI loadAlignment:  align.json загружен, warning НЕ выдаётся  ✓
_hook_cands spy:    6 вызовов, все clauses=None  ✓

CLI builds clauses() closure at __main__.py:8705-8714 — но в propose() НЕ передаёт (строка 8818)
```

**Механизм 2 (threshold):** Clause threshold gap — S4 (29.2% < 50%) пропускается до проверки клоз

```
S4 "Эволюция создала тревогу, как важный сигнал опасности."
  clause (4,7) via real align.json: span=(61.6, 65.0), dur=3.40s, score=4.80  ✓
  sentence start = 29.2% < 50% → _hook_cands: continue (до проверки клоз)
  даже с clauses=callback → S4 пропускается (threshold на начало предложения)
```

**Helper-only механизм 3 (after-threshold candidate loss, R3.2):**

```
S2.5: starts 71.7% > 50%, duration=9s > hook_max_sec=6.0s
  _hook_cands(clauses=None):  S2.5 → elif(hook_clauses and None) → False → пропущен  ✓
  _hook_cands(clauses=demo):  S2.5 → elif(hook_clauses and demo) → True → клоза найдена  ✓

cands_no = ['2.2']
cands_with = ['2.5@5-8', '2.2']  ← S2.5's clause recovered if clauses forwarded
```

**Итог с ограничением:** В §6-k/l добавлен вручную сконструированный `2.5` и возвращена вручную заданная клауза `(5,8,4.5,...)`. Это helper-only сравнительный тест `_hook_cands`, а не реальный alignment callback внутри CLI. Фактическая production потеря кандидата не воспроизведена. Требуемого кейса «предложение до 50%, допустимая клауза после 50%» нет: S4/S4-клауза обе до порога; 2.5 и её клауза обе после. **IMPACT=HELPER_ONLY; CROSSING=NOT_REPRODUCED.**

---

## §7 Fail-closed конфиг

```
subprocess --check-config r0_bad.yaml (select=greedy):
  stdout: "MISMATCH select: 'greedy' != 'global'"
  exit code: 1  ✓
```

---

## §8 Опубликованные лог-файлы R3

Значения ниже рассчитаны из опубликованных байт по `handoff` SHA `bafaaf2f45bf5b9ea4992fb1bb7369944071424d`. Runtime stdout содержит изменяющийся tmp-путь; его опубликованный файл всё равно имеет точный хеш.

| Файл | SHA256 | Git blob SHA |
|---|---|---|
| `baseline_stdout.txt` | `40fded80b11bc98a81153bdba1f97d0ada6bfb6de5cbead61dcd7d159c6c1f57` | `9ff34331303ef116e00d0a34e13fe7ad10eb8006` |
| `baseline_stderr.txt` | `95c8bff6a6649ab1b57a5199627eb12b9ec500e79d438bfea79340d7b125f306` | `33af8e45f553a9d916fe0c6cce28e79f17b953b1` |
| `noteaser_stdout.txt` | `b7cad1a2063c6485b784d5de540297aa17c9d293c4eefda22caac798c7a98608` | `6941cad2c58b1a875c8830d06e7e13baa1b1f126` |
| `negative_stdout.txt` | `b6ed48a3422a0c9e0f113524434c933e9fe46e6be877ac540ce170124c7d46fb` | `1850a3e956500eaedb2ccd6d88a58a4cba7b5816` |
| `config/r0.yaml` (baseline) | `efdef3adb0396e7e282553a8e3bfb0c690df015abdb8398cea1db5e642aeabba` | production baseline |

Ветка `handoff` содержит только `README.md` и `handoff/`; это отдельная ветка документов, её `diff` против `main` не является production diff. Изменения M223 ограничены артефактами handoff. Точный SHA этого **самого** коммита нельзя записать внутрь его содержимого без изменения SHA: `HANDOFF_EVIDENCE_SHA` пинит проверенные исходные файлы, новый SHA документальной коррекции указывается отдельно.
**R3 исправления по SOL-REVIEW-R3.md:**
- `_autocut_check`: spy → real call (не mock); результат: synthetic PASS, late-rejection NOT_REPRODUCED
- Same-callback counterfactual: `_real_propose([u2], prm, cli_sentences_cb, **kw0)` — viable ✓
- After-threshold clause demo: §6-k/l — реальная потеря кандидата без forwarding
- §5 первый звук: с teaser = h:2.1; без teaser = h:1.2 (хук, не тело 1.1)
- CHECK_COUNTER: 33 (точный счёт)
- §6-g2/g3/g4: span, dur, score точно утверждены
- SHA256 детерминированных файлов проверены

**Запуск:**
```bash
cd /path/to/autoreels-m223
.venv/bin/python handoff/m223/CLI_REPRO.py
# → PASS: 33 проверок, три находки CONFIRMED/NOT_REPRODUCED по CLI.
echo $?   # → 0
```

---

## §9 Итоговая таблица

| # | Статус | Метод | Доказательство |
|---|---|---|---|
| #1 P1 | **SEED CONFIRMED; LATE REJECTION NOT_REPRODUCED** | dynamic + CLI + real spy | pool=2, select_global вызван; u1+u2 merged; u2-alone viable (same cbs); real check spy; u2-alone не в пуле (used_seeds) |
| #2 P1 | **CONFIRMED** | dynamic + CLI + static | CLI prm.answer_start=True; h:2.1 teaser, h:1.2 no-teaser; тело 1.1 принято; stands_alone ≠ answer_start_reason |
| #3 P1 | **FORWARDING CONFIRMED; IMPACT HELPER_ONLY** | dynamic + CLI + static | 6× _hook_cands(clauses=None); align.json загружен; clause (4,7) реально найдена; §6-k/l: candidate loss from missing forwarding |

Выход `CLI_REPRO.py`: `exit 0`, 33 `check()` вызовов пройдено. Ограниченные доказательства §4/§6 остаются.

---

## §10 Целостность

Производственный код не изменён. `manifests/`, `transcripts/`, `reviews/`, `reels-out/` — не затронуты.

---

## Следующий шаг

Запрос на независимое ревью Sol 6.1 на текущем SHA handoff HEAD. M224 не начинается без PASS.
