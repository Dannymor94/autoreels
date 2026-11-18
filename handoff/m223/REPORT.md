# REPORT M223-R1 — CLI-доказательство трёх P1-находок в `cloud/autocut.py`

**Ветка:** `task/m223`  
**База:** `origin/main` → `3c011e94263e16e5780936b4769d3490cd03b682`  
**HEAD задачи:** `3c011e9` (код не менялся; только `handoff/m223/`)  
**Дата:** 2026-11-18  
**Инструмент:** Python 3.13, `.venv` в `autoreels-m223`  
**Статус:** `IMPLEMENTED, GATE PENDING` — ожидает PASS Sol 6.1

---

## Финальный отчёт (R1)

```
TASK=M223-R1
BASE_SHA=3c011e94263e16e5780936b4769d3490cd03b682
HANDOFF_HEAD_SHA=<будет после report.sh>
STATUS=READY_FOR_QA
CLI_ENTRY_COMMAND=cmd_autocut('synth', root=<tmp>, llm='none', check=False)
CLI_CONFIG_SHA256=790006cf123dd010a86db4c7fa2996b698236d25b3d28bb7d8553d76e2968b47
CONFIG_NEGATIVE_TEST=select=greedy → FAIL обнаружен (select≠global)
P1_1_CLI=CONFIRMED — used_seeds={1,2} после первого клипа; u2 пропущен как семя
P1_2_CLI=CONFIRMED — CLI prm.answer_start=True, stands_alone не проверяет answer_start_reason
P1_3_CLI=CONFIRMED — propose() нет параметра clauses; CLI предупреждает об align.json
TEASER_VARIANTS=block A s1 (ответ), block B s1 (не ответ); обе попадают в клип
CLAUSE_THRESHOLD_CASE=_hook_cands(clauses=None) не находит clause; _hook_cands(clauses=mock) находит
ASSERTIONS_PASSED=29 (23 check() + 6 config verify_config)
COMMAND_LOGS_AND_SHA256=см. §8 ниже
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

## §1 Метод воспроизведения (R1)

**Предыдущий метод (R0, отклонён Sol):** прямой вызов `propose()` — производственный CLI-путь не проходился.

**Текущий метод (R1):** `CLI_REPRO.py` вызывает `cmd_autocut()` из `autoreels/__main__.py` напрямую с:
- `root=<isolated temp dir>` — все файлы вне репозитория
- `llm="none"` — без сетевых вызовов
- `check=False` — без полного `--apply` check
- Spy-обёртка на `autoreels.cloud.autocut.propose` (через `unittest.mock.patch`) — фиксирует аргументы

**Путь CLI:** `cmd_autocut()` → `load_r0_config(root/config/r0.yaml)` → `AutoParams(...)` → `propose()`.

---

## §2 Конфигурация (config/r0.yaml — фактические значения)

| Ключ | Значение | Значимость |
|---|---|---|
| `hook_clauses` | `true` | #3: клозы должны работать |
| `start_strict` | `true` | #2: строгое начало включено |
| `answer_start` | `true` | #2: ответный старт запрещён |
| `start_morph` | `true` | #2: морфологическая проверка включена |
| `generator` | `mixed` | #1: смешанный генератор с `used_seeds` |
| `select` | `global` | подтверждён |

Все 6 ключей проверены через `load_r0_config(root/config/r0.yaml)`.

**Намеренные переопределения в тестах:** `--ac select=greedy` ТОЛЬКО в §7 (отрицательный тест). Во всех остальных разделах конфиг — производственный.

---

## §3 Доказательство CLI-пути

```
CLI stdout (baseline_stdout.txt, SHA256: 6bd070eb4931de2a9194d7d0dbe5026b734650dea6f4d59fc082c501c2f3bee1):
  сборок: до 5 (источник 3 мин ÷ 2)
  оценки владельца: примеры для начала −0/+0, для крючка −0/+0 (из 0 оценок)
  ведущий: карты говорящих нет (arl speakers synth) — реплики ведущего не различаются
  пул: 1 сборок < 15 — добавлено 0 вокруг мыслей силы 3
autocut synth: предложено сборок 1 из 2 мыслей → ...
  M1 81@1.05 | 1.1-4 2.1-4 | h:2.1! | c:2.4 | k:1.1=переменами;2.4=сегодня | ...

CLI stderr (baseline_stderr.txt, SHA256: ebd22ab9669bb52099fe6378f20b02b03be6efc2d88cbe47cb252c3d77e3a473):
  warning: нет карты речи и выравнивания для synth — правило паузы перед началом
           (start_pause_min) не работает
  warning: нет интонации transcripts/synth.prosody.json — ...
```

Выход: `0`. `propose()` вызван 2 раза (основной + fill_pool). AutoParams из первого вызова:
- `generator='mixed'`, `hook_clauses=True`, `start_strict=True`, `answer_start=True`, `start_morph=True`
- `passage_gap_sec=30.0`, `min_sec=25.0`, `target_sec=55.0`, `max_sec=90.0`

---

## §4 Находка #1 — CONFIRMED: `used_seeds` скрывает альтернативы (CLI-путь)

**Место:** `autocut.py:1174-1179` (проверка `used_seeds`), `:1262` (обновление `used_seeds`)

**Синтетические данные:**
- Block A (40.0–69.5s): "Да, тревога часто..." → S1-S4, refs="1.1-4"
- Block B (80.0–108.0s): "Принятие тревоги..." → S5-S8, refs="2.1-4"
- u1: id=1, thesis, punch=5, refs="1.1-4", topic="тревога"
- u2: id=2, thesis, punch=4, refs="2.1-4", topic="тревога"

**CLI stdout подтверждает:** `M1 81@1.05 | 1.1-4 2.1-4` → клип содержит обе мысли [u1, u2].

**Механизм через CLI AutoParams (generator='mixed', passage_gap_sec=30):**
1. Seeds отсортированы: [u1(★5), u2(★4)]
2. `build_passage(u1)`: u2 соседний (gap=10.5s < 30s), та же тема → клип [u1, u2] = 57.5s
3. Строка 1262: `used_seeds.update({1, 2})` (оба thesis — STORY роли)
4. При seed=u2: `seed["id"] in used_seeds` → True → `continue`
5. Альтернативный клип [u2] (28s, жизнеспособный) **никогда не строится**

**Доказательство:**
```
propose([u1,u2]): 1 клипов, составы: [{1, 2}]
propose([u2 only]): 1 клипов, составы: [{2}]
→ u2 жизнеспособен как самостоятельное семя, но blocked через used_seeds
```

**Последствие:** если клип [u1, u2] не проходит проверку монтажа, жизнеспособная замена [u2] не предлагается.

---

## §5 Находка #2 — CONFIRMED: `start_strict`/`answer_start`/`start_morph` обход в montage (CLI-путь)

**Места:**
- `autocut.py:657-673` — `stands_alone()` проверяет только `back_reference()`, НЕ `answer_start_reason()`
- `autocut.py:676-713` — `context_start()` вызывает `stands_alone(first_sent, ...)`
- `__main__.py:8632-8636` — `answer_start=True` попадает в `AutoParams`
- `__main__.py:6822` — строгая проверка явно пропускает `montage`-клипы (в другой команде)

**CLI-путь доказывает:**
- CLI AutoParams: `prm.answer_start=True`, `prm.start_strict=True` (из config)
- `cmd_autocut()` вызвал `propose()` с этими параметрами
- Клип с `u1` (первое предложение "Да, тревога часто возникает перед переменами.") принят
- CLI draft ссылается на `1.1-4` → `u1` с ответным началом принят

**Динамические проверки:**
```
answer_start_reason("Да, тревога...") = '«Да,…» — ответ, а вопроса в ролике нет'
back_reference("Да, тревога...")      = None   (stands_alone не поймает)
stands_alone("Да, тревога...", ..., prm) = None  → клип принят
```

**Первые слышимые слова:** "Да, тревога часто возникает перед переменами." (Block A, S1).  
**Вариант без teaser:** u1 первое предложение — ответ. Принят через propose().  
**Вариант с teaser:** hook `h:2.1!` — из Block B (после teaser_pos=0.5); ответное начало u1 остаётся в теле.

---

## §6 Находка #3 — CONFIRMED: `hook_clauses=true` не действует в `propose()` (CLI-путь)

**Места:**
- `autocut.py:1145-1150` — сигнатура `propose()` — параметра `clauses` **нет**
- `__main__.py:8674-8714` — CLI пытается построить `clauses()`, но требует `align.json`
- `__main__.py:8687-8688` — без align.json: предупреждение → `clauses` остаётся `None`
- `__main__.py:8818-8820` — `propose(..., start_pause=start_pause)` — `clauses=` **не передаётся**
- `autocut.py:1281` — `_hook_cands(clip, sentences, p, start_pause)` — без `clauses`
- `autocut.py:1027` — `if whole_bad and not (p.hook_clauses and clauses is not None): continue` → недостижимо

**CLI stderr подтверждает (SHA256: ebd22...473):**
```
warning: нет карты речи и выравнивания для synth — правило паузы перед началом
(start_pause_min) не работает
```
→ `clauses=None` для данного запуска. Даже если align.json присутствует, `propose()` всё равно не имеет параметра `clauses` и не может его принять.

**Порог teaser:**
- Клип [u1(40-69.5s), u2(80-108s)], teaser_pos=0.5, итог 57.5s
- Предложения до 50%: Block A s1-s4 (~29.5s / 57.5s = 51% → граница ≈ s3)
- `h:2.1!` — hook из Block B s1 (после порога) ✓

**Clause threshold case:**
```
_hook_cands(clauses=None): кандидаты=['20.6', '20.8'] — длинное предложение 20.7 (9s) пропущено
_hook_cands(clauses=mock): кандидаты=['20.7@1-6', '20.6', '20.8'] — clause-крючок найден
                            если бы propose() передавал clauses
```

**Статически:** `propose_params = ['end_tone', 'judge', 'no_start', 'open_end', 'p', 'rhythm_out', 'sentences', 'start_pause', 'taste', 'units']` — `clauses` отсутствует.

---

## §7 Fail-closed конфиг и отрицательный тест

**Отрицательный тест:** `--ac select=greedy`

CLI stdout для neg-теста (SHA256 neg_log: b69fa5dd82c60418a34a99e1a886f2bb4da9ee323ee8d8eeac5de297e0fb0f8f):
```
autocut для этого запуска: select=greedy
...
```

Харнесс обнаруживает: `ac_neg.select = 'greedy'` ≠ `'global'` → выводит `FAIL select` → добавляет в FAILURES.

Итог: при несоответствии конфига харнесс завершается с exit 1.

---

## §8 Лог-файлы и хэши

| Файл | SHA256 | Примечание |
|---|---|---|
| `cli_logs/baseline_stdout.txt` | `021225d41799af71d2dd84dd6297c462c0956ba1e1cf98b9582c243703bd9274` | содержит path tmpfs — не детерминирован между запусками |
| `cli_logs/baseline_stderr.txt` | `ebd22ab9669bb52099fe6378f20b02b03be6efc2d88cbe47cb252c3d77e3a473` | детерминирован |
| `cli_logs/negative_stdout.txt` | `ad8bafce2d398a161b80093fba1f0af53a09575da3b7da73fad4a1a9006e9860` | содержит path tmpfs |
| Черновик draft (контент)       | `8de872d4d6c7a0b8d1377a05eb0fc22c87ef6a8631077c8428d391c6d4444dfd` | детерминирован |
| `CLI_REPRO.py` (выход: 0)      | sha256 в отчёте из report.sh | |

**Детерминированные артефакты** (стабильны между запусками): `baseline_stderr.txt`, содержимое черновика.  
`baseline_stdout.txt` содержит `tmpfs`-путь (меняется при каждом запуске): ключевые строки `OK/FAIL` и SHA256 stderr/draft остаются постоянными.

**Запуск:**
```bash
cd /path/to/autoreels-m223
.venv/bin/python handoff/m223/CLI_REPRO.py
# → PASS: все проверки прошли, три находки CONFIRMED VIA CLI.
echo $?   # → 0
```

---

## §9 Итоговая таблица

| # | Статус | Метод | Доказательство |
|---|---|---|---|
| #1 P1 | **CONFIRMED VIA CLI** | dynamic + CLI | `cmd_autocut()` → spy → `propose([u1,u2])` → 1 клип `{1,2}`; `propose([u2])` → `{2}` |
| #2 P1 | **CONFIRMED VIA CLI** | dynamic + CLI + static | CLI `prm.answer_start=True`; клип с "Да,..." принят; `stands_alone` не проверяет `answer_start_reason` |
| #3 P1 | **CONFIRMED VIA CLI** | dynamic + CLI + static | `propose()` нет `clauses`; CLI stderr: "нет карты речи"; `_hook_cands(clauses=None)` ≠ `_hook_cands(clauses=mock)` |

Выход `CLI_REPRO.py`: `exit 0`, 29 проверок пройдено (23 check() + 6 config).

---

## §10 Целостность

```
$ git status --short  # в task/m223 worktree
 M handoff/m223/REPORT.md
?? handoff/m223/CLI_REPRO.py
?? handoff/m223/cli_logs/
```

Производственный код не изменён. `manifests/`, `transcripts/`, `reviews/`, `reels-out/` — не затронуты.

---

## Следующий шаг

Запрос на независимое ревью Sol 6.1. M223-R1 не мержится без PASS. Код алгоритма не менялся.
