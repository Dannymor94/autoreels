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
# u1 и u2 — одна тема, gap=10.5s < passage_gap_sec=30 → build_passage объединяет
# в один clip [u1,u2]. После принятия: used_seeds.update({1,2}). u2-alone никогда
# не пробуется. Принято из M223 §4-c, §4-d, §4-g.
units = [
    {"id": 1, "t0": 40.0, "t1": 69.5, "role": "thesis",     "punch": 5,
     "topic": "A", "refs": "1.1-4", "standalone": True, "similar": []},
    {"id": 2, "t0": 80.0, "t1": 108.0,"role": "conclusion",  "punch": 4,
     "topic": "A", "refs": "2.1-4", "standalone": True, "similar": []},
]
# Config: generator=passage, passage_gap_sec=30, min_sec=25, target_sec=55
# build_passage(seed=u1): total=29.5 < target=55; nxt=u2 (gap=10.5 < 30, same topic)
#   → adds u2; total=57.5 ≈ target → loop exits; run=[u1,u2]
# После принятия clip=[u1,u2]:
#   used_seeds.update(i for i in [1,2] if role in STORY)
#   → both thesis and conclusion ∈ STORY → used_seeds={1,2}
# При следующей итерации seeds: seed=u2 → seed["id"]=2 ∈ used_seeds → continue
# u2-alone viable (доказано в M223 §4-d с теми же callbacks)
```

**Assertions (fail-before):**
```python
pool = propose(units, params, sentences)
# u1+u2 объединены в один accepted clip
assert any(1 in pr.units and 2 in pr.units for pr in pool)   # merged clip
# u2-alone proposal НИКОГДА не в pool (подавлён через used_seeds)
assert not any(pr.units == [2] for pr in pool)
```

**Assertions (pass-after, pending M230):**
```python
# Proposal.units — list[int]
assert any(2 in pr.units and 1 not in pr.units for pr in pool_b)  # u2 clip standalone
assert not any(                              # overlap dedup preserved
    set(a.units) & set(b.units)
    for a, b in combinations(accepted_b, 2)
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
# hook_teaser=False устраняет fraction-фильтр в _hook_cands:1020-1021 до clause-ветки,
# делая clause-eligible кандидата доступным для прямого сравнения.
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
# Config: hook_clauses=true, hook_teaser=false, hook_min_sec=1.5, hook_max_sec=6.0
# hook_teaser=False: fraction-фильтр (:1020-1021) не применяется → clause branch reachable
```

**Assertions (fail-before — STATIC + HELPER):**
```python
# STATIC: source autocut.py:1281 — propose() вызывает _hook_cands без clauses=
# (подтверждено чтением production source; __main__.py:8818-8820 также не передаёт)

# HELPER: прямое сравнение _hook_cands с/без clauses (clause branch reachable с hook_teaser=False)
from autoreels.cloud.autocut import _hook_cands
clip = [units[0]]
cands_no_clauses   = _hook_cands(clip, sentences_long, p_no_teaser, start_pause=None, clauses=None)
cands_with_clauses = _hook_cands(clip, sentences_long, p_no_teaser, start_pause=None, clauses=clauses_cb)
# Fail-before HELPER: без clauses= clause-hook недостижим
assert len(cands_no_clauses) == 0    # без clauses — нет hook (HELPER_ONLY)
assert len(cands_with_clauses) >= 1  # с clauses — есть clause-hook (HELPER_ONLY)
# NB: это HELPER-уровень; full CLI impact NOT_REPRODUCED
```

**Assertions (pass-after, pending M230 + owner decision):**
```python
# После fix (если owner approves clause rescue): propose передаёт clauses → proposal имеет hook
assert proposal.hook is not None  # clause ref формат h:B.N@i-j
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
# M225 Case A: точные timing и integer refers. Принято как HELPER_CONFIRMED.
units = [
    {"id": 1, "t0": 50.0,  "t1": 76.0,  "role": "thesis",      "punch": 5,
     "topic": "A", "refs": "1.1",  "standalone": True, "similar": []},
    {"id": 2, "t0": 90.0,  "t1": 95.0,  "role": "explanation",  "punch": 4,
     "topic": "A", "refs": "1.1",  "standalone": False,
     "refers": 1,  # INTEGER — зависит от u1 (добавлен add_payoff, т.к. seed=u1)
     "similar": []},
    {"id": 3, "t0": 160.0, "t1": 193.0, "role": "conclusion",   "punch": 5,
     "topic": "A", "refs": "1.1",  "standalone": False,
     "refers": 2,  # INTEGER — зависит от u2 (add_payoff: u3.refers=2 ∈ ids ∋ u2)
     "similar": []},
]
# Config: production params (r0.yaml SHA efdef3adb...); start_pause_min=0.0, end_tone=False
# Механизм:
#   build_passage(seed=u1): grows to [u1,u2] (gap=14s usable, topic match)
#   add_payoff: u3.refers=2 ∈ clip-ids → appends u3 → [u1,u2,u3]
#   fit_rhythm: u2 dur=5s, gap(u1→u2)=14s → settle_need(14)×1.0≈6.22; 5<6.22 → drops u2
#   result: clip=[u1,u3]; u3.refers=2 (u2) unsatisfied
# HELPER_CONFIRMED M225 Case A: propose([u1,u2,u3]) → proposals with units=[1,3]
```

**Assertions (fail-before — HELPER_CONFIRMED M225):**
```python
proposals = propose(units, prm_m225, sentences=None, start_pause_min=0.0, end_tone=False)
# Proposal.units — list[int]
assert len(proposals) >= 1
accepted_units = proposals[0].units  # expected: [1, 3]
assert 1 in accepted_units and 3 in accepted_units
assert 2 not in accepted_units       # u2 (refers depended-on) dropped by fit_rhythm
# u3.refers=2 not satisfied — HELPER_CONFIRMED
```

**Assertions (pass-after, pending M230):**
```python
# После fix: refers-validator отклоняет clip с unsatisfied refers
assert len(proposals_fixed) == 0   # REJECTED: refers=2 unsatisfied
```

---

## FX-8a — TC-8a: Question-last (добавлен `fit_rhythm`)

```python
# M225 Case B: fit_rhythm растит short piece u2 добавляя question u3 как сосед.
# build_passage возвращает [u1,u2]; fit_rhythm → clip=[u1,u2,u3] (question-last).
# НЕ build_passage loop — fit_rhythm-механизм. Question-first (loop-pattern) законен.
units = [
    {"id": 1, "t0": 50.0, "t1": 76.0,  "role": "thesis",     "punch": 5, "topic": "A",
     "refs": "1.1", "standalone": True, "similar": []},
    {"id": 2, "t0": 90.0, "t1": 93.0,  "role": "conclusion",  "punch": 4, "topic": "A",
     "refs": "2.1", "standalone": True, "similar": []},  # dur=3s — short piece
    {"id": 3, "t0": 94.0, "t1": 119.0, "role": "question",    "punch": 5, "topic": "A",
     "refs": "3.1", "standalone": True, "similar": []},  # dur=25s > loop_max_sec → loop skips
]
# Config: production params из M225; start_pause_min=0.0, end_tone=False
# Механизм:
#   build_passage(seed=u1): [u1]; grow: adds u2 (gap=14s, topic=A, dur=3s usable)
#     → [u1,u2]; u3.dur=25 > loop_max_sec → loop_question skips u3 → returns [u1,u2]
#   fit_rhythm([u1,u2]): piece1=[u2] dur=3s < settle_need threshold → grow by neighbor
#     u3 at gap=1s ≤ jump_sec, same topic → appends u3 → clip=[u1,u2,u3]
#   clip[-1].role == "question" → question-last defect
# HELPER_CONFIRMED M225 Case B
```

**Assertions (fail-before — HELPER_CONFIRMED M225):**
```python
proposals = propose(units, prm_m225, sentences=None, start_pause_min=0.0, end_tone=False)
assert len(proposals) >= 1
# Proposal.units — list[int]; last unit is question
assert proposals[0].units[-1] == 3   # u3 (question) is last
```

**Assertions (pass-after, pending M230):**
```python
# После fix: question-last rejected or trimmed
assert len(proposals_fixed) == 0 or proposals_fixed[0].units[-1] != 3
```

**Negatives (не блокировать question-first loop):**
```python
# clip=[q(role=question), u(role=conclusion)] — question ПЕРВЫМ — законен
units_loop = [
    {"id": 10, "t0": 0.0,  "t1": 25.0, "role": "question",   "punch": 3, "topic": "A", ...},
    {"id": 11, "t0": 30.0, "t1": 60.0, "role": "conclusion",  "punch": 5, "topic": "A", ...},
]
proposals_loop = propose(units_loop, prm_m225, ...)
assert len(proposals_loop) >= 1  # question-first loop НЕ блокируется
```

---

## FX-8b — TC-8b: `fix_open_end` обрезает → `rhythm_why` отклоняет

```python
# M225 Case C: fix_open_end обрезает open-tone sentence → dur=2.5s → rhythm_why rejects.
# НЕ fit_rhythm middle-piece deletion — это отдельный механизм.
units = [
    {"id": 1, "t0": 50.0, "t1": 76.0,  "role": "thesis",     "punch": 5,
     "topic": "A", "refs": "1.1",  "standalone": True, "similar": []},
    {"id": 2, "t0": 126.0,"t1": 157.0, "role": "conclusion",  "punch": 5,
     "topic": "A", "refs": "2.1-2", "standalone": True, "similar": []},
]
# Sentences u2:
#   ("2.1", 1.5s, final-tone)  — fix_open_end сохраняет
#   ("2.2", 28.5s, open-tone)  — fix_open_end обрезает
# После fix_open_end: u2.t1 → 128.5; dur=2.5s
# Gap(u1→u2)=50s → settle_need(50)×tail ≈ 4.09s; dur=2.5 < 4.09 → rhythm_why REJECTS
# Rejection записывается в rhythm_out (не в open_end)
# HELPER_CONFIRMED M225 Case C
def sentences_8b(refs):
    _SENTS = {
        "1.1":  ("1.1",  26.0, 5, True,  "Мозг человека работает иначе."),
        "2.1":  ("2.1",   1.5, 2, True,  "Результат снижается."),   # final tone
        "2.2":  ("2.2",  28.5, 3, True,  "Навсегда останется там."),# open tone → trimmed
    }
    # parse "2.1-2" → ["2.1", "2.2"]
    out = []
    for piece in refs.split():
        blk, _, rng = piece.partition(".")
        a, _, z = rng.partition("-")
        for k in range(int(a), int(z or a) + 1):
            row = _SENTS.get(f"{blk}.{k}")
            if row: out.append(row)
    return out

_TONE_8b = {"2.1": "final", "2.2": "open"}
def end_tone_8b(ref): return _TONE_8b.get(ref)
# Config: end_tone=true, rhythm=true, start_pause_min=0.0; production params из M225
```

**Assertions (fail-before — HELPER_CONFIRMED M225 Case C):**
```python
open_end_c, rhythm_out_c = [], []
proposals_c = propose(units, prm_m225_end_tone,
                      sentences=sentences_8b, end_tone=end_tone_8b,
                      open_end=open_end_c, rhythm_out=rhythm_out_c)
assert len(proposals_c) == 0           # clip отклонён после fix_open_end+rhythm
assert bool(rhythm_out_c)              # rejection в rhythm_out (после fix_open_end)
assert not bool(open_end_c)            # fix_open_end trimmed (не gave up)
```

**Assertions (pass-after, pending M230 arch decision):**
```python
# ARCH_QUESTION: нужен ли recovery path (re-attempt или repair neighbor) после trim?
# Без M230 arch approval — fail-closed; fail-before остаётся наблюдаемым поведением
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

**Assertions (pass-after — ARCH_QUESTION, pending M230):**
```python
# break→continue НЕБЕЗОПАСЕН без bounded termination и альтернативной стратегии:
# при множестве overlong nxt может зациклиться.
# pass-after design — ARCH_QUESTION для M230. До arch approval — не реализовывать.
# result = build_passage(u5, by_id, p_arch_approved)
# assert result is not None
# assert 4 in [u["id"] for u in result]  # u4 (prv) включён — pending arch spec
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
