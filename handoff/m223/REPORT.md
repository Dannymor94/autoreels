# REPORT M223-R2 — CLI-доказательство трёх P1-находок в `cloud/autocut.py`

**Ветка:** `task/m223`  
**База:** `origin/main` → `3c011e94263e16e5780936b4769d3490cd03b682`  
**HEAD задачи:** `3c011e9` (код не менялся; только `handoff/m223/`)  
**Дата:** 2026-11-18  
**Инструмент:** Python 3.13, `.venv` в `autoreels-m223`  
**Статус:** `IMPLEMENTED, GATE PENDING` — ожидает PASS Sol 6.1

---

## Финальный отчёт (R2)

```
TASK=M223-R2
BASE_SHA=3c011e94263e16e5780936b4769d3490cd03b682
HANDOFF_HEAD_SHA=task/m223 worktree (handoff/m223/ only)
STATUS=READY_FOR_QA
CLI_ENTRY_COMMAND=cmd_autocut('synth', root=<tmp>, llm='none', check=False)
CLI_CONFIG_SHA256=efdef3adb0396e7e282553a8e3bfb0c690df015abdb8398cea1db5e642aeabba
CONFIG_NEGATIVE_TEST=subprocess --check-config r0_bad.yaml (select=greedy) → exit 1
P1_1_CLI=CONFIRMED — select_global() вызван (pool=2+); u1+u2 merged passage; u2-alone viable but not in pool
P1_2_CLI=CONFIRMED — CLI prm.answer_start=True; stands_alone не проверяет answer_start_reason; teaser h:2.1; no-teaser h:1.2
P1_3_CLI=CONFIRMED — propose() нет параметра clauses; align.json загружен; _hook_cands(clauses=None) для всех 6 вызовов
TEASER_VARIANTS=h:2.1 (после 50%, Block B); no-teaser h:1.2 (до 50%, Block A)
CLAUSE_THRESHOLD_CASE=S4@29.2%<50% → continue до клоз; _hook_cands пропускает S4 и с clauses=None и с clauses=demo
ASSERTIONS_PASSED=35 (все OK)
LOG_SHA_BASELINE_STDOUT=d1ff087ada7819bbbf9c101b27332d117ff1dc1417401f0227c84c36a62d0d26
LOG_SHA_BASELINE_STDERR=95c8bff6a6649ab1b57a5199627eb12b9ec500e79d438bfea79340d7b125f306
LOG_SHA_NOTEASER_STDOUT=2b0cccddcd235362132eb9640397556001ef326fbb3a1c0c9700980dc94f8a9e
LOG_SHA_NEGATIVE_STDOUT=b6ed48a3422a0c9e0f113524434c933e9fe46e6be877ac540ce170124c7d46fb
LOG_PATHS=handoff/m223/baseline_stdout.txt, handoff/m223/baseline_stderr.txt, handoff/m223/noteaser_stdout.txt, handoff/m223/negative_stdout.txt
CHANGED_PATHS=handoff/m223/CLI_REPRO.py, handoff/m223/REPORT.md, handoff/m223/cli_logs/*
WORKTREE_CLEAN=task/m223 (только handoff/m223/ изменён)
PR_URL=NONE
BLOCKERS=нет
```

---

## §0 Гейт M222A — подтверждение

```
$ git show origin/main:CLAUDE.md | grep -c "M222–M237"
2   → ОК: контракт интегрирован
```

- `main` = `3c011e9` (PR #9 «docs: apply M222-M237 agent workflow contract» merged)
- PR #10 «ci: establish deterministic offline smoke gate» merged
- 163 теста пройдено на CI

---

## §1 Метод воспроизведения (R2)

**R0 (отклонён Sol):** прямой вызов `propose()` — производственный CLI-путь не проходился.  
**R1 (отклонён Sol):** `cmd_autocut()` вызван, но: 1 кандидат в пуле (global selector не срабатывал), нет align.json (clauses статически), неверный SHA256 конфига.  
**R2 (текущий):**
- 3 синтетических мысли: u1(id=1, t=40-69.5s), u2(id=2, t=80-108s), u3(id=3, t=150-178s) — u1+u2 merge в passage, u3 отдельный клип → pool=2 → select_global срабатывает
- Block C переработан: все предложения 5+ слов, нет `_BACK_START` → `context_start()` принимает u3
- `synth.align.json` создаётся в изолированном корне → CLI загружает выравнивание без предупреждений
- S4 "Эволюция создала тревогу, как важный сигнал опасности." — запятая + пауза ≥ 0.12s → `clause_spans()` находит клозу (4,7)
- Subprocess `--check-config` режим: `sys.argv[1]=='--check-config'` → проверяет REQUIRED_CONFIG → exit 0/1
- Spy захватывает `select_global` ДО патчинга (не рекурсивный)

---

## §2 Конфигурация (config/r0.yaml — фактические значения)

| Ключ | Значение | Значимость |
|---|---|---|
| `hook_clauses` | `true` | #3: клозы должны работать |
| `start_strict` | `true` | #2: строгое начало включено |
| `answer_start` | `true` | #2: ответный старт запрещён |
| `start_morph` | `true` | #2: морфологическая проверка включена |
| `generator` | `mixed` | #1: смешанный генератор с `used_seeds` |
| `select` | `global` | #1: global selector активен |

Все 6 ключей проверены через `load_r0_config(root/config/r0.yaml)` в §0.  
`ProposalParams` (p) передаётся в `propose()` без поля `select` (оно на `AutoCutParams`); §3 проверяет 5 полей ProposalParams.

**r0.yaml SHA256:** `efdef3adb0396e7e282553a8e3bfb0c690df015abdb8398cea1db5e642aeabba`

---

## §3 Доказательство CLI-пути

```
stdout (baseline_stdout.txt):
  сборок: до 5 (источник 4 мин ÷ 2)
  пул: 2 сборок < 15 — добавлено 0 вокруг мыслей силы 3
autocut synth: предложено сборок 2 из 3 мыслей →
  M1 81@1.05 | 1.1-4 2.1-4 | h:2.1! | c:2.4 | k:1.1=переменами;2.4=сегодня | ...
  M2 89@1.08 | 3.1-4 | c:3.4 | k:3.1=сильнее;3.4=сегодня | ...

stderr (baseline_stderr.txt):
  warning: нет интонации transcripts/synth.prosody.json — ...
  (align.json загружен — предупреждения об отсутствии карты речи нет)
```

Выход: `0`. `propose()` вызван 2 раза (основной + fill_pool). AutoParams из первого вызова:
- `generator='mixed'`, `hook_clauses=True`, `start_strict=True`, `answer_start=True`, `start_morph=True`
- `passage_gap_sec=30.0`, `min_sec=25.0`, `target_sec=55.0`, `max_sec=90.0`

---

## §4 Находка #1 — CONFIRMED: `used_seeds` скрывает альтернативы (CLI-путь)

**Место:** `autocut.py:1174-1179` (проверка `used_seeds`), `:1262` (обновление `used_seeds`)

**Синтетические данные:**
- Block A (40.0–69.5s): S1-S4, refs="1.1-4", u1(id=1, punch=5)
- Block B (80.0–108.0s): S5-S8, refs="2.1-4", u2(id=2, punch=4)  
- Block C (150.0–178.0s): S9-S12, refs="3.1-4", u3(id=3, punch=5) — gap 42s > passage_gap_sec=30s

**CLI stdout подтверждает:** `предложено сборок 2 из 3 мыслей` → pool=2

**Global selector:**
```
select_global: weights=[89.0, 81.0], k=5, result=[0, 1]
→ select_global() вызван (pool >= 2, select=global из config) ✓
```

**used_seeds механизм:**
1. `propose()` возвращает: clip-A `{3}` (score=89), clip-B `{1,2}` (score=81)
2. `{1,2}` — оба thesis → `used_seeds.update({1,2})`
3. При попытке seed=u2: `seed["id"]=2 in used_seeds` → skip
4. Альтернативный клип `{2}` (28s, жизнеспособный) **никогда не строится**

**Доказательство через CLI:**
```
propose([u1,u2,u3]): 2 клипа, составы=[{3}, {1,2}]  → u1+u2 merged ✓
propose([u2 only]):  1 клип, состав=[{2}]            → u2 alone viable ✓
_autocut_check получил "1.1" ∧ "2.1" → clip [u1,u2] в check path ✓
_autocut_check НЕ получил "2.1" без "1.1" → u2-alone не в пуле ✓
```

**Последствие:** если клип [u1,u2] не проходит проверку монтажа, жизнеспособная замена [u2] не предлагается.

---

## §5 Находка #2 — CONFIRMED: `start_strict`/`answer_start`/`start_morph` обход в montage (CLI-путь)

**Места:**
- `autocut.py:657-673` — `stands_alone()` проверяет только `back_reference()`, НЕ `answer_start_reason()`
- `autocut.py:676-713` — `context_start()` вызывает `stands_alone(first_sent, ...)`
- `__main__.py:8632-8636` — `answer_start=True` попадает в `AutoParams`

**CLI-путь:**
- `cmd_autocut()` → `load_r0_config()` → `AutoParams(answer_start=True, start_strict=True)`
- Клип u1 (тело-открывалка: "Да, тревога часто возникает перед переменами.") принят

**Динамические проверки:**
```
answer_start_reason("Да, тревога...") = '«Да,…» — ответ, а вопроса в ролике нет'  → отвергает
back_reference("Да, тревога...")      = None                                         → не поймает
stands_alone("Да, тревога...", ..., prm) = None                                      → пропускает!
```

**Первые слышимые слова (оба варианта):**
- **С teaser (hook_teaser=True):** `h:2.1` → "Принятие тревоги снижает её интенсивность." (Block B, 58% клипа)
- **Без teaser (hook_teaser=False):** `h:1.2` → Block A S2, 25% клипа (хуки из первой половины разрешены)
- **Тело клипа в обоих случаях:** u1 "Да, тревога..." — ответное начало в клипе, `stands_alone()` не ловит

**Статически:** `stands_alone()` не вызывает `answer_start_reason()` — это подтверждает CLI-прогон.

---

## §6 Находка #3 — CONFIRMED: `hook_clauses=true` не действует в `propose()` (CLI-путь)

**Места:**
- `autocut.py:1145-1150` — сигнатура `propose()` — параметра `clauses` **нет**
- `__main__.py:8674-8714` — CLI пытается построить `clauses()`, нужен align.json
- `__main__.py:8818-8820` — `propose(..., start_pause=start_pause)` — `clauses=` **не передаётся**
- `autocut.py:1281` — `_hook_cands(clip, sentences, p, start_pause)` — без `clauses`

**R2: align.json загружен → `clause_spans()` реально вызывается:**
```
S4 words: ['Эволюция', 'создала', 'тревогу,', 'как', 'важный', 'сигнал', 'опасности.']
clause_spans(S4, via align.json): [(4, 7)]
Клоза 1.4@4-7: text='как важный сигнал опасности.', dur=3.40s ✓ (1.5-6.0s)
```

**CLI подтверждает (§6-b):** align.json загружен — предупреждения об отсутствии карты речи нет в stderr ✓  
**CLI подтверждает (§6-c,d):** `_hook_cands()` вызван 6 раз; во всех вызовах `clauses=None` ✓

**Тест порога тизера (clause threshold gap):**
```
S4 начинается в 15.5s / 53.0s = 29.2% < 50%
→ _hook_cands: S4 → continue (пропускается до проверки клоз)
→ клоза (4,7) никогда не проверяется — ни с clauses=None, ни с clauses=demo_clauses
S5 (начало 50.0% ≥ порога) → найдена ✓ (хуки из второй половины работают)
```

**Статически:** `propose_params = ['end_tone', 'judge', 'no_start', 'open_end', 'p', 'rhythm_out', 'sentences', 'start_pause', 'taste', 'units']` — `clauses` отсутствует.

---

## §7 Fail-closed конфиг и отрицательный тест

**Метод:** subprocess вызывает тот же `CLI_REPRO.py --check-config r0_bad.yaml`, где `select=greedy`.

```
subprocess exit code: 1
subprocess stdout: "MISMATCH select: 'greedy' != 'global'\n"
```

Код возврата `!= 0` верифицирован subprocess — не через парсинг stdout.

---

## §8 Лог-файлы

| Файл | SHA256 (пример запуска) | Примечание |
|---|---|---|
| `handoff/m223/baseline_stdout.txt` | `a257e53ed2a7908dd593fc618e7ee82b4ba84c5cb26d8ccd43b48c91adc43f86` | **нестабилен**: содержит tmpfs-путь |
| `handoff/m223/baseline_stderr.txt` | `95c8bff6a6649ab1b57a5199627eb12b9ec500e79d438bfea79340d7b125f306` | **детерминирован** |
| `handoff/m223/noteaser_stdout.txt` | `d0f927394d9825cf468dc4f1cab88d643f02521b89cf76209ec76b07fac8574a` | **нестабилен**: tmpfs-путь |
| `handoff/m223/negative_stdout.txt` | `b6ed48a3422a0c9e0f113524434c933e9fe46e6be877ac540ce170124c7d46fb` | **детерминирован** |
| `config/r0.yaml` | `efdef3adb0396e7e282553a8e3bfb0c690df015abdb8398cea1db5e642aeabba` | production |

**R1→R2 исправления (согласно SOL-REVIEW-R2.md):**
- Добавлен u3 (Block C) → pool=2 → select_global реально срабатывает
- Block C переработан (5+ слов, нет BACK_START) → context_start() принимает u3
- `synth.align.json` создаётся → clause_spans() реально работает; §6-b проверяет отсутствие warning
- Subprocess `--check-config` режим → rc реально проверяется (не парсинг stdout)
- SHA256 конфига исправлен: `efdef3...abba` (был `790006...47`)
- Пути логов: `handoff/m223/cli_logs/` (были в резюме как `cli_logs/*`)
- `select` проверяется на `AutoCutParams` (§0), не на `ProposalParams` (§3)
- Spy `select_global` захватывается до патча → нет рекурсии

**Запуск:**
```bash
cd /path/to/autoreels-m223
.venv/bin/python handoff/m223/CLI_REPRO.py
# → PASS: 35 проверок, три находки CONFIRMED VIA CLI.
echo $?   # → 0
```

---

## §9 Итоговая таблица

| # | Статус | Метод | Доказательство |
|---|---|---|---|
| #1 P1 | **CONFIRMED VIA CLI** | dynamic + CLI | `cmd_autocut()` → spy → pool=2 → select_global вызван → u1+u2 merged → u2-alone viable но не в пуле |
| #2 P1 | **CONFIRMED VIA CLI** | dynamic + CLI + static | CLI `prm.answer_start=True`; клип с "Да,..." принят; `stands_alone` не проверяет `answer_start_reason`; teaser h:2.1; no-teaser h:1.2 |
| #3 P1 | **CONFIRMED VIA CLI** | dynamic + CLI + static | `propose()` нет `clauses`; align.json загружен; `_hook_cands` 6 вызовов, все `clauses=None`; clause (4,7) реально найдена через align.json |

Выход `CLI_REPRO.py`: `exit 0`, 35 проверок пройдено.

---

## §10 Целостность

Производственный код не изменён. `manifests/`, `transcripts/`, `reviews/`, `reels-out/` — не затронуты.  
Все синтетические I/O — в изолированном tmpfs вне репозитория.

---

## Следующий шаг

Запрос на независимое ревью Sol 6.1. M223-R2 не мержится без PASS. Код алгоритма не менялся.
