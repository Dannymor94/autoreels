# M227 — Невидимые отказы до пула и ложная диагностика teaser_misses

**База:** `3c011e94263e16e5780936b4769d3490cd03b682`  
**PRODUCTION_DIFF:** none  
**SOURCE_SHA:** `dddd…` (64 × d, синтетический)  
**Инструмент:** `python3.11 handoff/m227/REPRO.py`  
**Статус:** PASS 27/27 assertions

---

## Часть 1 — Полная карта ворот до пула (STATIC_ONLY)

Перечислены 12 точек, где кандидат пропадает **до** попадания в пул; ни одна из них не выводит счётчик в CLI-отчёт:

| Место в коде             | Условие отказа                                      | Видит владелец          |
|--------------------------|-----------------------------------------------------|-------------------------|
| `eligible:164-169`       | punch < min_punch; aside; нет refs; filtered; роль  | мысль отсутствует       |
| seeds filter `:1168-1170`| punch < seed_punch                                  | отсутствует, нет счётч. |
| `build_clip/passage None`| слишком коротко; нет соседей той же темы; < min_sec | отсутствует             |
| propose loop `:1175-1179`| seed в used_seeds / taken                           | отсутствует             |
| `_loop_question:1101-109`| лучший вопрос слишком длинный                       | нет счётчика            |
| `add_payoff:350-355`     | payoff слабый / далеко / external lean              | нет payoff, нет счётч.  |
| overlap check `:1257-1261`| последний unit совпадает / слишком много общих      | отсутствует             |
| pool truncation `:1309-10`| кандидатов > clips×check_pool                      | "не дошла очередь: N"   |
| `fill_pool:1321-1322`    | weak-seed делит unit с пулом                        | только добавлено N      |
| `_hook_cands:1018-1038`  | weak/early/glued/no-clauses                         | нет индивидуальной прич.|
| `short_variant:1929-1934`| units не найдены; слишком короткий/длинный          | variant отсутствует     |

**Нормальная семантика None:** `build_clip`/`build_passage` возвращает None как корректный результат (попытка была, дисквалифицировано по правилу). Это невидимо в диагностике.

**Путь weak-seed (`fill_pool`, `__main__.py ~8821-8830`):**
- второй вызов `propose()` НЕ получает `no_start=`, `open_end=`
- `rhythm_out=[]` (новый список) → потери ритма не накапливаются

---

## Часть 2 — Точный учёт: два синтетических маршрута (CLI_CONFIRMED)

### Конфиг (из r0.yaml через load_r0_config)

| Параметр         | Значение |
|------------------|----------|
| seed_punch       | 4        |
| min_punch        | 3        |
| min_sec          | 25.0 с   |
| start_pause_min  | 0.15 с   |
| hook_teaser      | True     |
| hook_clauses     | True     |

### Map A — чистая (1 eligible seed → 1 clip)

```
total units       = 2
eligible seeds    = 1  (punch≥4, role in STORY)
pool accepted     = 1
gap               = 0
```

**Вывод CLI:** `предложено сборок 1 из 2 мыслей` — точно соответствует.

### Map B — с потерей (2 eligible seeds → 1 clip, 1 попытка исчезает)

Юнит 2 (id=2): punch=4 ≥ seed_punch=4 → является seed-попыткой.  
Длительность = 10 с < min_sec=25 с, topic="isolated" → нет соседей той же темы → `build_passage` возвращает None.  
Эта потеря **не попадает в CLI-отчёт**.

```
total units        = 3
eligible seeds     = 2  (ids [1, 2])
  id=1: 40 с → build_passage OK
  id=2: 10 с → build_passage None (too short)
pool accepted      = 1
gap                = 1  (> 0, невидим в CLI)
```

**CLI-строка:** `предложено сборок 1 из 3 мыслей` — не объясняет, почему 1 из 2 eligible seeds пропала.

### Слабые seeds (weak-seed fill, STATIC_ONLY)

Из исходного кода `__main__.py:8823` (excerpt):

```python
_extra = propose(the_map.get("units") or [],
                 _dc_replace(prm, clips=prm.clips * ac.check_pool, seed_punch=_fsp), sentences,
                 judge=judge, end_tone=end_tone, taste=_taste, rhythm_out=[], start_pause=start_pause)
```

Параметры `no_start=`, `open_end=` отсутствуют. `rhythm_out=[]` — потери ритма выброшены.

---

## Часть 3 — Ложная диагностика teaser_misses (HELPER_CONFIRMED + STATIC_ONLY)

### Суть расхождения

`teaser_misses` вызывается для clip-а, у которого нет hook. Функция показывает, **почему** каждое предложение второй половины не стало крючком. Если она говорит `"прошла"` — значит, по её логике, предложение годится.

Но `_hook_cands` имеет дополнительный параметр `start_pause` (callback от alignment) и `clauses`. Если `start_pause(ref) = 0.05 < start_pause_min=0.15`, то `glued_start` возвращает причину → `_hook_cands` отклоняет.  
`teaser_misses` не проверяет `glued_start` вообще.

### Демонстрация

Синтетическая фраза: `"Главная мысль теста здесь."` (ref="2.1", sec=4.0, nwords=6, complete=True, punch=5, не указательное слово)

| Функция                                    | Результат         |
|--------------------------------------------|-------------------|
| `teaser_misses(clip, sentences, p)`        | n=1, why=`{'прошла': 1}` |
| `_hook_cands(..., start_pause=0.05)`       | `[]` (отклонено: 0.05 < 0.15) |
| `_hook_cands(..., start_pause=None)`       | 1 кандидат (принято) |

**Вывод:** расхождение обусловлено именно `start_pause` callback — `teaser_misses` не передаёт его.

### Структурная подпись (STATIC_ONLY)

```
teaser_misses(clip, sentences, p)
_hook_cands(clip, sentences, p, start_pause=None, clauses=None)
```

В `teaser_misses` нет ни `start_pause`, ни `clauses`. Это означает, что диагностика структурно неполна для случаев, когда alignment-файл есть.

**Важная оговорка:** в CLI-прогоне без alignment-файла `start_pause` callback = None → `glued_start` не срабатывает → обе функции согласны. Расхождение возможно только при наличии `.alignment.json`.

### Callback/флаги, отсутствующие в teaser_misses

| Параметр      | Есть в `_hook_cands` | Есть в `teaser_misses` |
|---------------|----------------------|------------------------|
| start_pause   | ✓                    | ✗                      |
| clauses       | ✓                    | ✗                      |

**Вызов модели не нужен:** `glued_start` — детерминированное правило.

---

## Итоговый статус по секциям

| Секция      | Статус           | Детали                                              |
|-------------|------------------|-----------------------------------------------------|
| §0 Preflight | CLI_CONFIRMED   | rc=0, review написан (SHA d91605b9…)                |
| §1 Часть 1  | STATIC_ONLY      | 12 ворот до пула перечислены                        |
| §2 Часть 2  | CLI_CONFIRMED    | Map B gap=1 невидим в CLI-выводе                    |
|             | STATIC_ONLY      | weak-seed: нет no_start/open_end, rhythm_out=[]     |
| §3 Часть 3  | HELPER_CONFIRMED | teaser_misses → "прошла" vs _hook_cands → []        |
|             | STATIC_ONLY      | сигнатурный пробел: нет start_pause/clauses         |

**Всего assertions: 27/27 PASS.**
