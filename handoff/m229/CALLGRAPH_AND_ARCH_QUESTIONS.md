# M229-PREP — Граф вызовов и вопросы для M230 arch review

**База:** `main@3c011e94263e16e5780936b4769d3490cd03b682`  
**PRODUCTION_DIFF=NONE · M229_CODE_GO=NO**  
Все symbol-ссылки — read-only статическое чтение production source.

---

## 1. Граф вызовов CLI-пути

Легенда: `→` наблюдённый вызов (OBSERVED из M223–M227); `⇢` статически подтверждённый вызов (STATIC).

```
cmd_autocut(stem, root, llm)                             [__main__.py:~8600]
  ⇢ load_r0_config(root/"config/r0.yaml")               [__main__.py:8609]
  ⇢ AutoParams (из AutocutConfig)                        [__main__.py:8630]
  ⇢ build clauses callback (если hook_clauses)           [__main__.py:8673–8710]
  ⇢ build start_pause callback (если start_pause_min)   [__main__.py:8672–8710]
  ⇢ propose(units, params, sentences, ...)               [__main__.py:8818]  ← ФАЗА 1
      ⇢ eligible(u, p)                                   [autocut.py:164]
      ⇢ build_passage(seed, by_id, p, taken)            [autocut.py:365]  ← #1 #9
          ⇢ usable(u)                                    [autocut.py:375]
          ⇢ rhythm checks (jump_sec, max_jumps)          [autocut.py:390–395]
          → ВОЗВРАЩАЕТ: list[unit] | None
      ⇢ build_clip(seed, units, by_id, p)               [autocut.py:213]
      ⇢ add_payoff(clip, seed, units, p, taken)         [autocut.py:338]
      ⇢ fit_rhythm(clip, by_id, p, keep, taken)         [autocut.py:297]  ← #7 #8b
          → ВОЗВРАЩАЕТ: (list[unit] | None, notes)
      ⇢ context_start(clip, by_id, p, sentences, ...)   [autocut.py:676]  ← #2 #5
          ⇢ glued_start(ref, p, start_pause)            [autocut.py:990]
          ⇢ stands_alone(text, nxt, p, judge, core)     [autocut.py:~800]
          → ВОЗВРАЩАЕТ: (list[unit] | None, notes, why)
      ⇢ fix_open_end(clip, sentences, end_tone, p)      [autocut.py:~1080]
      ⇢ rhythm_why(spans, p, is_loop)                   [autocut.py:~270]
      ⇢ _hook_cands(clip, sentences, p, start_pause)    [autocut.py:1281]  ← #3
          # NOTE: clauses=None здесь (не передаётся) — статически подтверждено
          → ВОЗВРАЩАЕТ: [(ref, score, text)]
      ⇢ teaser_misses(clip, sentences, p)               [autocut.py:1292]  ← #11
      → ВОЗВРАЩАЕТ: Proposal(units, hook, score, ...)
  ⇢ fill_pool / weak-seed propose                        [__main__.py:8821–8831]  ← #11
      # NOTE: без no_start, open_end, clauses — статически подтверждено
  ⇢ select_global(weights, conflict, k, ...)            [autocut.py:1368]  ← #4
  → review writer                                        [__main__.py:~9100]
```

---

## 2. Затронутые символы и scope изменений

Все изменения **за M230 arch gate**. Текущие коды — read-only.

| Символ | Файл:строка | Находки | Permitted изменение (pending arch) |
|--------|------------|---------|-----------------------------------|
| `propose()` | `autocut.py:1145` | #1, #2, #3, #5 | Signature: добавить `clauses=None`; body: bounded reattempt #1, check dur #5 |
| `build_passage()` | `autocut.py:365` | #9a, #9b | `break→continue` при overlong nxt; answer extension (arch decision) |
| `context_start()` | `autocut.py:676` | #2, #5 | Re-check min_sec после drop; body opener detection |
| `fit_rhythm()` | `autocut.py:297` | #7, #8b | Refers-check после removal; fail-closed neighbor-contract |
| `_hook_cands()` | `autocut.py:1002` | #3 | Принимает `clauses=` (уже принимает); propose должен передавать |
| `teaser_misses()` | `autocut.py:1047` | #11 | (observability — arch decision M230) |
| `used_seeds/taken` | `autocut.py:1172–1264` | #1 | Bounded enumeration design |
| `select_global()` | `autocut.py:1368` | #4 | (observational counter M231) |
| `fill_pool() / weak propose` | `__main__.py:8821` | #11 | (observational M231) |

---

## 3. Точные call sites

### `propose` → `_hook_cands` без `clauses=` (TC-3)
```python
# autocut.py:1281
cands = _hook_cands(clip, sentences, p, start_pause) if sentences else []
# → clauses не передаётся; _hook_cands имеет signature(clauses=None)
```

### `__main__.py:8818` → `propose` без `clauses=`
```python
pool = propose(the_map.get("units") or [],
               _dc_replace(prm, clips=prm.clips * ac.check_pool), sentences,
               no_start=no_start, judge=judge, end_tone=end_tone,
               open_end=open_end, rhythm_out=rhythm_out,
               taste=_taste, start_pause=start_pause)
# → clauses callback (8673–8710) НЕ передаётся в propose
```

### `used_seeds` / `taken` gate (TC-1)
```python
# autocut.py:1172–1175
used_seeds: set[int] = set()
taken: set[int] = set()
for seed in seeds:
    if seed["id"] in used_seeds or seed["id"] in taken:
        continue  # ← seed пропускается без счётчика
```

### `build_passage` overlong nxt (TC-9a)
```python
# autocut.py:396–405
if nxt is not None and (prv is None or run[-1].get("role") == "question"):
    pick = nxt
elif prv is not None and (nxt is None or not run[0].get("standalone", True)):
    pick = prv
elif prv is None:
    break           # ← прv тоже None → break (OK)
else:
    pick = nxt if _strength(nxt) >= _strength(prv) else prv

if total + _dur(pick) > p.max_sec:
    break           # ← ПРОБЛЕМА: break при overlong nxt; prv не пробуется
```

### `context_start` drop без re-check min_sec (TC-5)
```python
# autocut.py:716–720 (упрощённо)
if rows[0] drop condition:
    clip = [{**u, "refs": refs, "t0": float(u["t0"]) + float(rows[0][1])}] + clip[1:]
    # t0 смещается → dur уменьшается → нет re-check min_sec
```

---

## 4. Вопросы для M230 arch review

### Q1 — #1: Bounded reattempt для `used_seeds` (REQUIRED)

**Вопрос:** Какое максимальное N bounded reattempt attempts для eligible seeds, чей id уже в `used_seeds`?  
**Контекст:** `used_seeds` заполняется ids из принятого clip'а (строка 1262); `taken` — все units из passage clip'ов (строка 1264). Идентичные units в двух финальных clips запрещены (`taken`-barrier). Seeds, попавшие в чужой passage, всё равно eligible alone.  
**Варианты:**
1. Второй `propose` pass после основного: только seeds с высоким punch, не в `taken`.
2. Флаг `allow_seed_reattempt=True` при `generator=passage` и `seed_punch` ≥ N.
3. Отдельная функция `enumerate_suppressed_seeds()`.

**Инвариант:** финальные принятые clips не содержат пересекающихся units (сохраняется через `taken`-barrier или post-select dedup).

---

### Q2 — #2: Body opener detection (REQUIRED)

**Вопрос:** Как различать body opener (не стоит самостоятельно, но не question-loop) и поддерживаемую question-led loop конструкцию?  
**Контекст:** `context_start` вызывает `stands_alone` (строка 707) и `glued_start` (строка 706). Question-loop: clip[0].role == "question" с clip[-1].role in PAYOFFS (строка 1270) — intentionally legal.  
**Граница:** Тест TC-2 должен блокировать «Да, конечно.» body opener, но НЕ блокировать «Когда это происходит?» question-led loop.  
**Вопрос:** `context_start` уже использует `stands_alone` — достаточно ли это блокирует body opener? Или нужен отдельный check?

---

### Q3 — #3: Clause rescue semantic (REQUIRED — owner decision)

**Вопрос:** Нужно ли спасать hook через clause длинной фразы при `hook_clauses=true`?  
**Контекст:** `_hook_cands` уже принимает `clauses=` (строка 1002). `propose` вызывает `_hook_cands` без `clauses=` (строка 1281). `clauses` callback строится в `__main__.py:8701-8710` при `hook_clauses=true`. Callback НЕ передаётся в `propose`.  
**Вопрос:** Semantic — выдавать clause как hook? Backward-compatible signature `propose(clauses=None)`?

---

### Q4 — #5: Min_sec re-check location (REQUIRED)

**Вопрос:** Где располагать re-check `dur >= min_sec` после `context_start`?  
**Варианты:**
1. В конце `context_start`: перед return проверять `sum(_dur(u) for u in clip) >= p.min_sec`.
2. В `propose` после `clip = clip2` (строка 1232): `if sum(_dur(u) for u in clip) < p.min_sec: continue`.
3. В финальном validator перед Proposal.

---

### Q5 — #7: Refers validator location (REQUIRED)

**Вопрос:** Где проверять что все `refers` clip'а удовлетворены?  
**Контекст:** `fit_rhythm` может удалить unit с which другие units refers. Поле `u["refers"]` = строка типа "2" = зависимость от unit id=2.  
**Варианты:**
1. В `fit_rhythm` перед removal: проверять dependents.
2. В `propose` после `fit_rhythm`: post-check refers.
3. В финальном Proposal validator.

---

### Q6 — #8b: Legal repair neighbor для short piece (REQUIRED — owner decision)

**Вопрос:** Какой сосед является легальным для repair short piece?  
**Контекст:** `fit_rhythm` пробует grow piece соседом (строки 312-326). Если нет eligible соседа — silent removal (строка 331). NOT_VERIFIED: есть ли cases, где законный сосед доступен и мог бы repair.  
**Вопрос:** Fail-closed всегда? Или repair с конкретным neighbor-contract? Owner decision required.

---

### Q7 — #9b: Answer extension после question (REQUIRED — owner decision)

**Вопрос:** Всегда ли добавлять answer unit после удаления question post-loop trim?  
**Контекст:** `build_passage` строки 408-413: после post-loop pop question-last, run[-1] проверяется. Answer unit (следующий в source) может быть доступен.  
**Варианты:**
1. Всегда добавлять answer (если usable, topic match, dur ≤ max_sec).
2. Только если answer.role in PAYOFFS.
3. Не добавлять — trim и возвращать run без question.  
**Owner decision required.**

---

### Q8 — #11: `teaser_misses` выравнивание (REQUIRED — arch decision)

**Вопрос:** Выравнивать ли `teaser_misses` с `_hook_cands` по параметрам `start_pause` и `clauses`?  
**Контекст:** `teaser_misses` (строка 1047) не принимает `start_pause`/`clauses`; `_hook_cands` принимает. При наличии alignment callback: расхождение в диагностике (HELPER_CONFIRMED M227).  
**Варианты:**
1. Добавить `start_pause`/`clauses` в `teaser_misses` signature.
2. Рефакторить через shared helper.
3. Оставить как есть, добавить warning в diagnostic output.  
**Это изменение signature — за M230 arch gate.**

---

## 5. M231 observability: что измерять (без изменения алгоритма)

| Счётчик | Где добавить | Тип |
|---------|-------------|-----|
| `eligible` | `propose` после seeds filter | int |
| `attempted` (прошли eligible+seed_punch) | `propose` перед build_passage | int |
| `none_reasons` | `propose` когда clip is None | dict[str, int] |
| `pool_added` | `propose` когда pool.append | int |
| `fill_added` (weak-seed) | после fill_pool | int |
| `selected` | в selection loop | int |
| `rejected_validator` | в `_autocut_check` | int |
| `accepted` | в accepted clips | int |
| `t0_delta` / `t1_delta` | propose при alignment | float (observational) |

Вывод: `{"stage": "propose", "eligible": N, ...}` в stderr как JSON-line.  
**Только additive counters — не менять selection/acceptance logic.**  
**Только synthetic/consent-free фикстуры — не требовать owner-данные.**

---

## 6. M231 → M232 граница

| Компонент | M231 (observability) | M232 (behavior fix, после M230 arch) |
|-----------|---------------------|--------------------------------------|
| Seed counters | ✓ | — |
| build_passage None reason | ✓ (logging) | #9a fix (break→continue) |
| teaser_misses параметры | — | После arch decision Q8 |
| weak-seed no_start/open_end | — | После arch decision |
| post-select fallback #4 | counter only | fix после M231 observation |
| t0/t1 boundary enforcement | delta-log only | fix после M231 observation |
