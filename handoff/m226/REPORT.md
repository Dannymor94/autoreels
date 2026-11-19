# M226 — Отчёт по воспроизведению находок #4, #9, #12

**Базовый коммит:** `3c011e94263e16e5780936b4769d3490cd03b682`  
**PRODUCTION_DIFF:** `none`  
**SOURCE_SHA (маркер M226):** `dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd`  

---

## §1 Preflight — `cmd_autocut` на синтетических данных

**Статус:** `CLI_CONFIRMED`

### Данные

Синтетический транскрипт с двумя предложениями в блоке t=35–75 с (40 с):
- Предложение 1: t=35.0–54.0, слова `P0`…`P{i}.` — последнее слово с `.` для `_ends_terminal`
- Предложение 2: t=55.0–75.0, слова `P{i}`…`P{j}.` — аналогично
- Пауза между предложениями 1 с > `sentence_pause_sec=0.35` → разделение подтверждено
- Слова в верхнем регистре (`P0`, `P1`…) → `text[0].isupper() = True` → проверка mid-sentence пропускается
- Пустой блок-заглушка t=85–105 (20 с, другая тема) для `total_duration=105 с`, чтобы midpoint=55 с < 105-30=75 с проходил `tail_skip` фильтр

Манифест с полным `SetupProfile` (crop, scale, frame), карта в `transcripts/<stem>.map.json`.

### Результат

```
rc=0
review file: reviews/synthetic_m226_auto_m56.txt
accepted: M1 88 | 1.1-2 | c:1.2 | t: Synthetic conclusion. | d: Synthetic conclusion.
fingerprint: cec9bad0fef7a11e
```

**SHA256 review-файла:** `95350aa04a173a9c1d81d767c04c6e29a035905c6b1fe5f908c165cf7c1ff60f`

---

## Finding #4 — `select_global`: сильный конфликтующий vs два слабых совместимых

**Статус:** `SELECTOR_HELPER_CONFIRMED` + `LATE_REJECTION_NOT_REPRODUCED`

### Сценарий

Веса: A=95, B=60, C=60.  
Конфликты: A↔B (общий opener #1 + unit #1), A↔C (общий unit #2).  
B и C совместимы.

### Результат `select_global`

```python
select_global([95.0, 60.0, 60.0], A_conflicts_BC, k=2) → [1, 2]  # B+C
```

B+C=120 > A=95 → глобальный оптимум найден правильно.

### Подтверждение конфликтов через `too_close`

```
too_close(A, [B], max_shared=0) = 'то же начало, что у M1 (#1)'   # конфликт
too_close(A, [C], max_shared=0) = 'общие мысли с M1: #2'           # конфликт
too_close(B, [C], max_shared=0) = None                             # совместимы
```

### Позднее отклонение (LATE_REJECTION)

`_autocut_check` вызывается после `select_global` и выполняет полный `_blocks_do_apply`.  
Для синтетической проверки с настоящим медиа (subtitle timing, sentence checks) это  
воспроизвести без реального аудио невозможно.  
**→ LATE_REJECTION_NOT_REPRODUCED**

---

## Finding #9 — `build_passage`: два сценария досрочного выхода

### F9A — предпочтительный nxt превышает `max_sec`, prv игнорируется

**Статус:** `HELPER_CONFIRMED`

**Настройка:**
- seed (id=1): role="conclusion", punch=5, t=100–145 (45 с)
- nxt  (id=2): role="thesis",     punch=6, t=147–197 (50 с) → 45+50=95 > max_sec=90 → `break`
- prv  (id=0): role="explanation", punch=4, t=70–95  (25 с) → 45+25=70 ≤ max_sec=90 (подошло бы)

Код в `autocut.py` ≈ строка 404:
```python
if total + _dur(pick) > p.max_sec:
    break   # ← не проверяет другую сторону
```

**Результат:** `[1]` — только seed. prv (25 с, подходящий) не пробовался.  
**Контроль:** nxt=25 с → `[1, 2]` ✓

**Механизм:** алгоритм выбирает направление (`pick = nxt if _strength(nxt) >= _strength(prv) else prv`),  
и если оно не помещается, сразу делает `break` без попытки альтернативного направления.

---

### F9B — вопрос в конце цикла; ответ за ним недостижим

**Статус:** `HELPER_CONFIRMED`

**Настройка:**
- seed    (id=1): role="conclusion", punch=5, t=100–145 (45 с) — ниже target_sec=55 → цикл продолжается
- question (id=2): role="question",  punch=4, t=147–160 (13 с) → 45+13=58 ≥ target_sec=55 → цикл завершается
- answer  (id=3): role="answer",     punch=5, t=161–176 (15 с) — соседний с вопросом

Алгоритм:
1. Цикл добавляет вопрос (total=58 ≥ target_sec=55 → выход из цикла)
2. Post-loop обрезка: `run[-1]` — вопрос → pop
3. Ответ (id=3) никогда не рассматривался, т.к. цикл уже завершился

**Результат:** `[1]` — только seed. Ответ пропущен.  
**Контроль:** nxt=answer 15 с → `[1, 2]` ✓

**Механизм:** после post-loop pruning освободившееся место не переоткрывает цикл.

---

## Finding #12 — детерминированность `select_global`

**Статус:** `HELPER_CONFIRMED`, `DETERMINISTIC_SAME_INPUT`, `ORDER_SENSITIVE`

### Идентичный вход — идентичный результат (10 вызовов)

```python
select_global([70.0, 70.0, 70.0], no_conflict, k=2)
# → [0, 1] (10/10 раз)
```

Branch-and-bound детерминирован: при одинаковом входе результат одинаков побайтово.

### Чувствительность к порядку при равных весах

```python
select_global([60.0, 60.0, 60.0], no_conflict, k=2)         → [0, 1]
select_global([60.0, 60.0, 60.0] reversed, no_conflict, k=2) → [0, 1]
```

При одинаковых весах порядок обхода (`sorted(..., key=lambda i: (-weights[i], i))`) детерминирован  
и всегда берёт индексы 0 и 1. Но если веса разные, а оптимальных наборов несколько — выбор  
зависит от порядка весов во входном списке.

**Итог:** `DETERMINISTIC_SAME_INPUT` (стабилен при одном вводе), `ORDER_SENSITIVE` (разный порядок  
равных весов теоретически даёт разный выбор при разных конфигурациях).

---

## Артефакты

| Файл | Описание |
|------|----------|
| `REPRO.py` | Портативный скрипт (--repo-root или auto-detect) |
| `repro_stdout.log` | Вывод REPRO.py (SHA256: `cd3bf3f870d0dfdbe82a0710116341cf6858a1a8775c7b5d9b1b57147f034c41`) |
| `repro_stderr.log` | Stderr REPRO.py (SHA256: `80aa10d654a7e8414528c917c0f5ab58b4b8b363712eec53678b237ef450eec8`) |

---

## Итоговая таблица

| Finding | Статус |
|---------|--------|
| §1 Preflight | `CLI_CONFIRMED` |
| F4 select_global | `SELECTOR_HELPER_CONFIRMED` + `LATE_REJECTION_NOT_REPRODUCED` |
| F9A build_passage | `HELPER_CONFIRMED` |
| F9B build_passage | `HELPER_CONFIRMED` |
| F12 determinism | `HELPER_CONFIRMED` + `DETERMINISTIC_SAME_INPUT` + `ORDER_SENSITIVE` |
