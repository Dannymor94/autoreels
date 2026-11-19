# M229-PREP — Каталог синтетических фикстур

**База:** `main@3c011e94263e16e5780936b4769d3490cd03b682`  
**PRODUCTION_DIFF=NONE · M229_CODE_GO=NO**  
Все фикстуры — синтетические, без owner-данных. Переиспользуют принятую M226 логику (SHA `e1be1b74...`) и M227 логику (SHA `929646319d...`).

---

## Принципы фикстур

1. **Только синтетика.** Никаких реальных медиа, alignment-файлов, просодии владельца.
2. **Детерминизм.** Фиксированные `t0/t1`, `punch`, `topic`, `refs` → результат воспроизводим.
3. **Изоляция.** Каждая фикстура в `TemporaryDirectory`; `root` не пересекается с production paths.
4. **Нет claim о production impact.** Fail-before — на baseline коде без изменений; не production media.
5. **Переиспользование M226/M227 scaffold.** `_build_synthetic_root()` из `handoff/m226/REPRO.py` и `handoff/m227/REPRO.py`.

---

## FX-1 — TC-1: `used_seeds` suppression

```python
# Два eligible seed-unit одной темы, без пересечения по времени
units = [
    {"id": 1, "t0": 0.0,  "t1": 30.0, "role": "conclusion", "punch": 5,
     "topic": "main", "refs": "1.1-2", "standalone": True, "similar": []},
    {"id": 2, "t0": 35.0, "t1": 65.0, "role": "conclusion", "punch": 5,
     "topic": "other",  # разная тема → build_passage не объединяет u1 и u2
     "refs": "2.1-2", "standalone": True, "similar": []},
    # Dummy для total_duration
    {"id": 3, "t0": 100.0, "t1": 160.0, "role": "thesis", "punch": 3,
     "topic": "ext", "refs": "3.1", "standalone": True, "similar": []},
]
# Config: seed_punch=4, min_punch=3, generator=passage, passage_gap_sec=30
# Expected fail-before: u1 попадает в pool; u2 (seed_id=2) пропускается,
#   т.к. id=2 ∈ used_seeds после u1 clip (u2 не включён в u1 passage но
#   NOTE: в baseline используется passage_gap_sec — проверить что u2 ≠ u1 passage member)
# Уточнение: u2 должен быть seed-eligible alone но подавляться через used_seeds
# После принятия M230: u2 должен быть в pool как отдельный candidate
```

**Assertions (fail-before):**
```python
assert len(pool_a) >= 1       # u1 clip accepted
assert 2 not in {u for p in pool_a for u in p.units}  # u2 NOT in pool as seed
```

**Assertions (pass-after, pending M230):**
```python
assert any(2 in pr.units for pr in pool_b)  # u2 clip in pool
assert not any(                              # overlap dedup preserved
    set(a.units) & set(b.units)
    for a, b in combinations(accepted, 2)
)
```

---

## FX-2 — TC-2: Body opener и question-loop различие

```python
# Clip A: body opener (не стоит самостоятельно)
units_A = [
    {"id": 1, "t0": 100.0, "t1": 125.0, "role": "thesis", "punch": 5,
     "topic": "main", "refs": "1.1-3", "standalone": True, "similar": []},
]
def sentences_body(refs):
    if refs == "1.1-3":
        return [
            ("1.1", 3.0, 3, True,  "Да, конечно."),        # body opener — не стоит alone
            ("1.2", 11.0, 8, True, "Главная мысль здесь."), # standalone
            ("1.3", 11.0, 8, True, "Завершение."),
        ]
    return []

# Clip B: question-led loop (должен быть разрешён)
units_B = [
    {"id": 10, "t0": 0.0,  "t1": 15.0, "role": "question", "punch": 3,
     "topic": "main", "refs": "10.1", "standalone": True, "similar": []},
    {"id": 11, "t0": 20.0, "t1": 50.0, "role": "conclusion", "punch": 5,
     "topic": "main", "refs": "11.1-2", "standalone": True, "similar": []},
]
def sentences_loop(refs):
    if refs == "10.1":
        return [("10.1", 15.0, 8, True, "Когда это происходит?")]
    if refs == "11.1-2":
        return [
            ("11.1", 15.0, 8, True, "Первый ответ."),
            ("11.2", 15.0, 8, True, "Завершение ответа."),
        ]
    return []
```

**Assertions (fail-before):**
```python
# Body opener: context_start может принять, несмотря на "не стоит alone" — наблюдено M223
# Pass-after (pending M230): context_start REJECTED with reason
assert clip_A_result is None or reason_A == "body_opener"
# Question-loop: НЕ блокируется
assert clip_B_result is not None  # question-first loop preserved
```

---

## FX-3 — TC-3: Clauses hook rescue

```python
units = [
    {"id": 1, "t0": 0.0, "t1": 60.0, "role": "conclusion", "punch": 5,
     "topic": "main", "refs": "1.1", "standalone": True, "similar": []},
]
def sentences_long(refs):
    if refs == "1.1":
        # Длинная фраза (sec=35.0 > hook_max_sec=6) — не подходит целиком как hook
        return [("1.1", 35.0, 20, True, "Это очень длинная фраза про важную тему.")]
    return []
def clauses_cb(ref):
    if ref == "1.1":
        # Clause i=2..3 — короткая standalone часть
        return [(2, 3, 3.0, "важную тему")]
    return []
# Config: hook_clauses=true, hook_teaser=true, hook_teaser_pos=0.5
# hook_min_sec=1.5, hook_max_sec=6.0
```

**Assertions (fail-before — STATIC):**
```python
# propose() вызывает _hook_cands без clauses= → clause-hook не найден
from autoreels.cloud.autocut import _hook_cands
cands_no_clauses = _hook_cands(clip, sentences_long, p, start_pause=None, clauses=None)
cands_with_clauses = _hook_cands(clip, sentences_long, p, start_pause=None, clauses=clauses_cb)
assert len(cands_no_clauses) == 0   # без clauses — нет hook
assert len(cands_with_clauses) >= 1  # с clauses — есть clause-hook
```

**Assertions (pass-after, pending M230):**
```python
# После fix: propose передаёт clauses → proposal имеет hook
assert proposal.hook is not None and "@" in proposal.hook  # clause ref формат h:B.N@i-j
```

---

## FX-5 — TC-5: `context_start` → dur < min_sec

```python
# Clip с двумя фразами: первая "не стоит alone" (context_start удалит)
# После удаления dur = 25.0 - 2.0 = 23.0 < min_sec=25
units = [
    {"id": 1, "t0": 100.0, "t1": 125.0, "role": "conclusion", "punch": 5,
     "topic": "main", "refs": "1.1-2", "standalone": True, "similar": []},
]
def sentences_short(refs):
    if refs == "1.1-2":
        return [
            ("1.1", 2.0, 3, True, "Поэтому главное."),  # не стоит alone (context_drop)
            ("1.2", 23.0, 10, True, "Это главная мысль."),
        ]
    return []
# Config: context_start=true, min_sec=25, context_drop_words=5
# context_start: удаляет "1.1" (2.0s) → t0+=2.0 → dur = 23.0s
```

**Assertions (fail-before):**
```python
clip2, notes, why = context_start(clip, by_id, p, sentences_short)
assert clip2 is not None             # текущий код: принимает 23.0s без re-check
assert sum(_dur(u) for u in clip2) < p.min_sec  # 23.0 < 25.0
```

**Assertions (pass-after, pending M230):**
```python
# После fix: re-check → REJECTED
assert clip2 is None
assert why is not None and "min_sec" in why
```

---

## FX-7 — TC-7: `fit_rhythm` removes refers dependency

```python
units = [
    {"id": 1, "t0": 0.0,  "t1": 30.0, "role": "thesis",     "punch": 5,
     "topic": "main", "refs": "1.1", "standalone": True, "similar": []},
    {"id": 2, "t0": 35.0, "t1": 60.0, "role": "conclusion",  "punch": 4,
     "topic": "main", "refs": "2.1", "standalone": True, "similar": []},
    {"id": 3, "t0": 65.0, "t1": 95.0, "role": "conclusion",  "punch": 4,
     "topic": "main", "refs": "3.1", "refers": "2",   # зависит от u2
     "standalone": False, "similar": []},
]
# u2 — короткий isolated piece, fit_rhythm удаляет его
# после удаления: clip=[u1,u3]; u3.refers=2 — u2 уже не в clip
```

**Assertions (fail-before):**
```python
clip_r, _ = fit_rhythm([u1, u2, u3], by_id, p, keep={u1["id"], u3["id"]})
assert clip_r is not None           # текущий код принимает [u1,u3]
assert any(u["id"] == 3 for u in clip_r)  # u3 (refers=2) остаётся
# refers=2 (u2) не в clip → unsatisfied
```

**Assertions (pass-after, pending M230):**
```python
result = validate_refers(clip_r)    # новая проверка
assert result is None  # REJECTED: unsatisfied refers
```

---

## FX-8a — TC-8a: Question-last clip

```python
units = [
    {"id": 1, "t0": 0.0,  "t1": 30.0, "role": "thesis",    "punch": 5, "topic": "main",
     "refs": "1.1", "standalone": True, "similar": []},
    {"id": 2, "t0": 30.0, "t1": 55.0, "role": "conclusion", "punch": 4, "topic": "main",
     "refs": "2.1", "standalone": True, "similar": []},
    {"id": 3, "t0": 55.0, "t1": 85.0, "role": "question",   "punch": 3, "topic": "main",
     "refs": "3.1", "standalone": True, "similar": []},
]
# seed=u1; build_passage grows: [u1,u2] total=55s=target_sec=55 → next iteration tries nxt=u3(question)
# строка 396: nxt not None и prv None → pick=nxt; total+30=85 ≤ max_sec=90 → adds u3
# строка 408: while run[-1] is not seed and (not eligible(run[-1]) or role==question):
#   u3.role==question AND u3 is not seed → pop → run=[u1,u2]
# WAIT: это уже делает pop... но наблюдено в M225 что question остаётся последним
```

**Примечание:** build_passage действительно выполняет pop на строке 408 для non-seed question. Fail-before наблюдён в M225 через `propose` helper с другой конфигурацией units/timing. Точная фикстура требует синтетических units, где u3 является seed-eligible question (может быть seed) или trim не срабатывает.

```python
# Альтернатива: seed = u3 (question как seed)
# build_passage с seed=question → возвращает None (строка 412 else: seed is question)
# Или: более короткий run где u3 входит и pop не срабатывает (u3 is seed)
```

**Assertions (fail-before):**
```python
# Как наблюдено в M225: propose выдаёт proposal с question-last unit
assert proposals[0].units[-1] == question_id
```

**Assertions (pass-after, pending M230):**
```python
# Trim или reject при question-last
assert proposals[0].units[-1] != question_id  # trimmed
```

---

## FX-8b — TC-8b: Post-trim short piece

```python
# Три unit, средний — short isolated piece
units = [
    {"id": 1, "t0": 0.0,  "t1": 30.0, "role": "thesis",    "punch": 5, "topic": "main",
     "refs": "1.1", "standalone": True, "similar": []},
    {"id": 2, "t0": 35.0, "t1": 37.5, "role": "thesis",    "punch": 3, "topic": "main",
     "refs": "2.1", "standalone": True, "similar": []},  # 2.5s piece
    {"id": 3, "t0": 42.0, "t1": 72.0, "role": "conclusion","punch": 5, "topic": "main",
     "refs": "3.1", "standalone": True, "similar": []},
]
# Config: rhythm=true, jump_sec=4.0, min_sec=25, seed=u1
# fit_rhythm: u2 is piece of 2.5s < jump_sec; grow: id=1 in ids, id=3 in ids, prev(id=1) in ids
# fit_rhythm удаляет u2 (not in keep={u1.id, u3.id})
# dur([u1,u3]) = 60.5 ≥ min_sec → NOT None — но short piece наблюдался в другом контексте
```

**Assertions (fail-before):**
```python
clip_r, _ = fit_rhythm([u1, u2, u3], by_id, p, keep={u1["id"], u3["id"]})
# Текущий код: может вернуть clip без u2 (silent drop) OR None если dur < min_sec
# Fail: нет logged reason при silent drop
```

**Assertions (pass-after, pending M230):**
```python
# После fix: fail-closed с reason если нет доказанного соседа
assert clip_r is None  # rejected
assert "no_repair_neighbor" in reason
```

---

## FX-9a — TC-9a: `build_passage` overlong nxt

```python
units = [
    {"id": 4, "t0": 25.0, "t1": 50.0, "role": "thesis",    "punch": 4, "topic": "main",
     "refs": "4.1", "standalone": True, "similar": []},
    {"id": 5, "t0": 50.0, "t1": 70.0, "role": "conclusion", "punch": 5, "topic": "main",
     "refs": "5.1", "standalone": True, "similar": []},  # seed
    {"id": 6, "t0": 70.0, "t1": 130.0,"role": "thesis",    "punch": 4, "topic": "main",
     "refs": "6.1", "standalone": True, "similar": []},  # nxt overlong: total+60=80 > max_sec=60
]
# Config: min_sec=25, max_sec=60, target_sec=55, passage_gap_sec=30
# seed=u5: total=20s < target=55; nxt=u6: usable=True (topic match, refs OK, not filtered)
# строка 404: total + _dur(u6) = 80 > max_sec=60 → break (не пробует prv=u4!)
# run=[u5]; dur=20 < min_sec=25 → None
```

**Assertions (fail-before):**
```python
result = build_passage(u5, by_id, p)
assert result is None  # overlong nxt → break → too short → None
```

**Assertions (pass-after, pending M230):**
```python
# После fix: continue вместо break → prv=u4 добавляется
result = build_passage(u5, by_id, p_fixed)
assert result is not None
assert 4 in [u["id"] for u in result]  # u4 (prv) включён
```

---

## FX-9b — TC-9b: Answer после question post-loop trim

```python
units = [
    {"id": 1, "t0": 0.0,  "t1": 30.0, "role": "thesis",    "punch": 5, "topic": "main",
     "refs": "1.1", "standalone": True, "similar": []},  # seed
    {"id": 2, "t0": 30.0, "t1": 55.0, "role": "question",  "punch": 3, "topic": "main",
     "refs": "2.1", "standalone": True, "similar": []},  # nxt; total=55=target
    {"id": 3, "t0": 55.0, "t1": 85.0, "role": "conclusion","punch": 5, "topic": "main",
     "refs": "3.1", "standalone": True, "similar": []},  # answer (нет дополнительно)
]
# Config: target_sec=55, max_sec=90, min_sec=25
# build_passage: seed=u1; total=30 < 55; iter1: pick nxt=u2(question) (loop exit after: role==question)
# wait: строка 396 — nxt is not None и (prv is None OR last is question)
# → pick=nxt=u2; total=55=target → loop exits
# строка 408: run[-1]=u2 is question AND u2 is not seed → pop; run=[u1]; dur=30 ≥ min_sec=25 → OK
# u3 (answer) не посещается — наблюдено M226
```

**Assertions (fail-before):**
```python
result = build_passage(u1, by_id, p)
assert result is not None
assert 2 not in [u["id"] for u in result]  # u2 (question) trimmed
assert 3 not in [u["id"] for u in result]  # u3 (answer) NOT visited
```

**Assertions (pass-after, pending M230 arch approval):**
```python
# ГИПОТЕЗА — не mandated; pending arch design
# result = build_passage(u1, by_id, p_fixed)
# assert 3 in [u["id"] for u in result]  # u3 (answer) included
```

---

## Общие требования к будущим тестам

```python
# 1. Существующий baseline suite PASS (нет регрессий)
pytest tests/ --sha 3c011e94...  # → все тесты зелёные

# 2. Новые defect regression: fail-before
@pytest.mark.xfail(strict=True, reason="defect #N — fixed in M232")
def test_TC_N_fail_before():
    ...

# 3. Pass-after (только после code fix в M232)
def test_TC_N_pass_after():
    ...  # исполняется только на fix SHA

# 4. Negative/fail-closed cases PASS
def test_TC_N_negative():
    result = function_with_correct_rejection(...)
    assert result is None  # или reason != None
    assert logged_reason in expected_reasons

# 5. Детерминированные seed при randomness
import random; random.seed(0)
import random; random.seed(42)
import random; random.seed(1337)
# Idempotency: одинаковый вход → одинаковый выход при последовательных вызовах

# 6. Feature-flag off parity
def test_feature_flag_off_parity():
    p_off = replace(p, hook_clauses=False)
    result_off = propose(units, p_off, sentences)
    result_baseline = propose_baseline(units, p_off, sentences)
    assert result_off == result_baseline  # no change when flag off

# 7. No nonempty-input/zero-output false success
def test_no_empty_success():
    rc = cmd_autocut(stem, root=temp_root, llm="none")
    assert rc == 0 implies len(accepted_proposals) >= 1  # or rc != 0

# 8. Manual selection preserved
def test_manual_preserved():
    # manual-маркер не перезаписывается
    assert any(p.score == MANUAL_SCORE for p in result if p.manual)
```
