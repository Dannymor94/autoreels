# REPORT M223 — Воспроизведение трёх P1-находок в `cloud/autocut.py`

**Ветка:** `task/m223`  
**База:** `origin/main` → `3c011e94263e16e5780936b4769d3490cd03b682` (docs: apply M222-M237 agent workflow contract)  
**HEAD задачи:** `3c011e9` (кода не менялось, только `handoff/m223/`)  
**Дата:** 2026-11-18  
**Инструмент:** Python 3.13, `.venv` в `autoreels-m223`  
**Статус:** `IMPLEMENTED, GATE PENDING` — ожидает PASS Sol 6.1  

---

## Гейт M222A — подтверждение

```
$ git show origin/main:CLAUDE.md | grep -c "M222–M237"
2   → ОК: контракт интегрирован
```

- `main` = `3c011e9` (PR #9 «docs: apply M222-M237 agent workflow contract» merged)
- PR #10 «ci: establish deterministic offline smoke gate» merged
- 163 теста пройдено на CI

---

## Конфигурация (`config/r0.yaml` — фактические значения)

| Ключ | Значение | Значение для находок |
|---|---|---|
| `hook_clauses` | `true` | #3: клозы должны работать |
| `start_strict` | `true` | #2: строгое начало включено |
| `answer_start` | `true` | #2: ответный старт запрещён |
| `start_morph` | `true` | #2: морфологическая проверка включена |
| `generator` | `mixed` | #1: смешанный генератор с `used_seeds` |
| `select` | `global` | подтверждён |
| `auto_mode` | `scenario` | `arl auto` → сценарист; для монтажного пути нужен `arl autocut` |

Команда: `arl autocut <манифест>` (без `--scenario`) — производственный путь через `propose()`.

---

## Находка #1 — CONFIRMED: `used_seeds` скрывает альтернативы до глобального отбора

**Место:** `autocut.py:1174-1179` (проверка `used_seeds`), `:1262` (обновление `used_seeds`)

**Механизм:**
1. Семена сортируются по убыванию `punch`: `#1 (★5)`, `#2 (★4)`, `#3 (★4)`.
2. `build_passage(seed=#1)` строит клип `[#1, #2, #3]` (соседние мысли одной темы, 80.5 с).
3. Строка 1262: `used_seeds.update(i for i in ids if by_id[i].get("role") in STORY)` → `{1, 2, 3}`.
4. Дойдя до семени `#2`, строка 1175: `if seed["id"] in used_seeds` → `True` → `continue`.
5. Альтернативный клип `[#2, #3]` (50 с, жизнеспособный, проходит `min_sec=25..max_sec=90`) **никогда не строится**.

**Доказательство (`REPRO.py`):**
```
Полный набор ([#1,#2,#3]): 1 клипов, составы: [{1, 2, 3}]
Без #1 ([#2,#3]): 1 клипов, составы: [{2, 3}]
#1-f PASS: #2 попал в used_seeds → как семя пропускается
```

Команда воспроизведения:
```bash
cd /path/to/autoreels-m223
python handoff/m223/REPRO.py   # exit 0, все OK
```

**Последствие для владельца:** если клип `[#1, #2, #3]` позже проваливает проверку монтажа, жизнеспособная замена `[#2, #3]` не предлагается. Причины отсутствия альтернативы не видны ни в счётчиках, ни в черновике.

---

## Находка #2 — CONFIRMED: `start_strict`/`answer_start`/`start_morph` обходятся в montage

**Места:**
- `__main__.py:6822` — явный пропуск montage-клипов: `if r.id in _seen or "montage" in (r.flags or []) or not r.subtitles: continue`
- `autocut.py:657-673` — `stands_alone()` читает только `back_reference()` + `context_min_words`; не вызывает `strict_start_reason()`, `answer_start_reason()`
- `__main__.py:8632-8636` — поля `start_strict`, `answer_start`, `start_morph` копируются в `AutoParams.prm` — но `propose()` / `context_start()` / `stands_alone()` их **не используют**

**Механизм:**
1. `propose()` с `context_start=True` вызывает `context_start()` → `stands_alone()`.
2. `stands_alone()` вызывает `back_reference(text)` — проверяет лишь ссылки назад («как я говорил», «и…», «это…»). Не вызывает `answer_start_reason()`.
3. Текст «Да, тревога часто возникает перед переменами.» — `back_reference` возвращает `None` (нет ссылки назад), `stands_alone` → `None` (ок).
4. Строгая проверка в `__main__.py:6817-6839` — работает только после `propose()`, и явно пропускает `"montage"` клипы.

**Доказательство (`REPRO.py`):**
```
answer_start_reason("Да, тревога...") = '«Да,…» — ответ, а вопроса в ролике нет'
back_reference("Да, тревога...")     = None   (stands_alone не поймает)
propose() с answer_start=True: клип принят, notes=['начало: «Да, тревога часто...»']
```

**Последствие:** клип монтажа открывается на ответе без вопроса («Да, тревога возникает…») при включённом `answer_start: true`. Причины обхода правила в черновике нет.

---

## Находка #3 — CONFIRMED: `hook_clauses=true` не действует в `propose()`

**Места:**
- `__main__.py:8701-8714` — CLI строит `clauses()` при `hook_clauses=True`
- `__main__.py:8818-8820` — `propose(…, start_pause=start_pause)` — `clauses=` **не передаётся**
- `autocut.py:1145-1150` — сигнатура `propose()` — параметра `clauses` **нет**
- `autocut.py:1281` — `_hook_cands(clip, sentences, p, start_pause)` — без `clauses`
- `autocut.py:1027` — `if whole_bad and not (p.hook_clauses and clauses is not None): continue` — с `clauses=None` ветка клозов **никогда не выполняется**

**Механизм:**
1. CLI строит `clauses()` (строки 8701-8714): правильная функция, возвращает `(a, z, sec, text)`.
2. `propose()` принимает до 10 параметров — `clauses` среди них нет.
3. Вызов на строке 8818 не передаёт `clauses`.
4. Внутри `_hook_cands`: `clauses=None` → строка 1027 принудительно пропускает длинные предложения целиком; строка 1034 `elif p.hook_clauses and clauses is not None` → никогда не достигается.

**Доказательство (`REPRO.py`):**
```
# propose() без clauses: кандидаты ['B20.1.6', 'B20.1.8']
# _hook_cands напрямую с clauses=mock: [('B20.1.7@1-6', 6.2), ('B20.1.6', 5.7), ...]
# Первым идёт clause-крючок B20.1.7@1-6 — который propose() не видит вовсе
параметры propose()=['end_tone', 'judge', 'no_start', 'open_end', 'p', 'rhythm_out',
                     'sentences', 'start_pause', 'taste', 'units']  # нет clauses
```

**Последствие:** клипы остаются без крючка при включённом `hook_clauses: true`. Владелец видит «крючок не найден», хотя подходящая клауза длинного предложения существует.

---

## Итоговая таблица

| # | Статус | Метод | Доказательство |
|---|---|---|---|
| #1 P1 | **CONFIRMED** | динамический | `propose([u1,u2,u3])` → 1 клип `{1,2,3}`; без u1 → клип `{2,3}` строится |
| #2 P1 | **CONFIRMED** | динамический + статический | `propose()` принимает «Да, тревога…»; `answer_start_reason` отвергает; `__main__.py:6822` явно исключает montage |
| #3 P1 | **CONFIRMED** | динамический + статический | `propose()` не имеет `clauses` в сигнатуре; `_hook_cands(clauses=mock)` находит clause-крючок; `propose()` — нет |

Выход `REPRO.py`: `exit 0`, все 11 проверок пройдены.

---

## Артефакты

- `handoff/m223/REPRO.py` — детерминированный воспроизводитель (exit 0)
- `handoff/m223/REPORT.md` — этот файл
- Ветка: `task/m223` на базе `3c011e9`

---

## Следующий шаг

Запрос на независимое ревью Sol 6.1. M223 не мержится без PASS. Код алгоритма не менялся.
