# M229-PREP-R2 — Отчёт (R2 — исправлено после Sol R1)

**Дата:** 2026-11-19  
**Исполнитель:** Claude Code Sonnet 4.6  
**Задача:** `handoff/m229/TASK-M229-PREP-R2.md`  
**R1 review pin:** `9fcb8159a217f517c1e141b96ea4c9ebbdc5712d`  
**PRODUCTION_DIFF=NONE · M229_CODE_GO=NO**  
**BASE_SHA:** `3c011e94263e16e5780936b4769d3490cd03b682`  
**EVIDENCE_BASE (M228-R2):** `handoff/m228/REPORT.md` · M228 P1-A через P1-F = CLOSED

---

## 1. Изменённые пути

```
handoff/m229/REGRESSION_CONTRACTS.md   — 9 regression contracts (R2: TC-1,3,7,8a,8b,9a исправлены)
handoff/m229/FIXTURE_CATALOG.md        — синтетические fixture blueprints (R2: FX-1,3,7,8a,8b,9a исправлены)
handoff/m229/CALLGRAPH_AND_ARCH_QUESTIONS.md — граф вызовов + arch questions (R2: строки 625/657 исправлены)
handoff/m229/REPORT.md                 — этот документ (R2)
```

Никаких изменений в `src/`, `tests/`, `config/`, `manifests/`, `transcripts/`, `reels-out/`, `reviews/`, `CLAUDE.md`, или `main`.

---

## 2. Закрепление доказательств (неизменны с M223–M227)

| Символ | Файл:строка | Находка | Уровень |
|--------|------------|---------|---------|
| `used_seeds/taken` | `autocut.py:1172–1175` | #1 — seed suppression | CLI_CONFIRMED |
| `context_start → stands_alone` | `autocut.py:676+` | #2 — body opener | CLI_CONFIRMED (bounded) |
| `propose → _hook_cands` | `autocut.py:1281` | #3 — clauses not passed | CLI_HELPER_BOUNDARY + STATIC |
| `select_global` | `autocut.py:1368` | #4 — late rejection | HELPER_CONFIRMED |
| `context_start → t0 shift` | `autocut.py:699+` | #5 — no min_sec re-check | CLI_HELPER_BOUNDARY |
| `context_start → t0 offset` | `autocut.py:699+` | #6 — t0/t1 offset | CLI_HELPER_BOUNDARY |
| `fit_rhythm → refers removal` | `autocut.py:331` | #7 — refers unsatisfied | HELPER_CONFIRMED |
| `propose → fit_rhythm` | `autocut.py:1200; fit_rhythm:297–326` | #8a — late question appended | HELPER_CONFIRMED |
| `fix_open_end → final rhythm_why` | `autocut.py:625; propose:1239,1250` | #8b — trim 2.5s then rhythm_out reject | HELPER_CONFIRMED |
| `build_passage → overlong break` | `autocut.py:405` | #9a — overlong nxt break | HELPER_CONFIRMED |
| `build_passage → no answer visit` | `autocut.py:408–413` | #9b — answer not visited | HELPER_CONFIRMED |
| `teaser_misses` / `_hook_cands` | `autocut.py:1047` / `:1002` | #11 — param mismatch | CLI_OUTPUT_GAP + HELPER |

**Уровни не расширяются.** RENDER-уровень не достигнут ни одной находкой.

---

## 3. Девять тест-идентификаторов

| ID | Находка | Функция | Строка | Статус |
|----|---------|---------|--------|--------|
| TC-1 | #1 used_seeds | `propose` | `autocut.py:1175` | SPECIFIED — не запущен |
| TC-2 | #2 body opener | `context_start` | `autocut.py:699+` | SPECIFIED — не запущен |
| TC-3 | #3 clauses | `propose → _hook_cands` | `autocut.py:1281` | SPECIFIED — не запущен |
| TC-5 | #5 context_start shortens | `context_start` | `autocut.py:699+` | SPECIFIED — не запущен |
| TC-7 | #7 fit_rhythm refers | `fit_rhythm` | `autocut.py:331` | SPECIFIED — не запущен |
| TC-8a | #8a question-last | `fit_rhythm` | `autocut.py:297–326; propose:1200` | SPECIFIED — не запущен |
| TC-8b | #8b post-trim rejection | `fix_open_end → rhythm_why` | `autocut.py:625,273; propose:1239,1250` | SPECIFIED — не запущен |
| TC-9a | #9a overlong nxt | `build_passage` | `autocut.py:405` | SPECIFIED — не запущен |
| TC-9b | #9b answer not visited | `build_passage` | `autocut.py:408–413` | SPECIFIED — не запущен |

**Пропущен TC-4** (#4 select_global): INSTRUMENT_FIRST по M228 — counter only в M231.  
**Пропущен TC-6** (#6 t0/t1): INSTRUMENT_FIRST по M228 — delta-лог в M231.  
**Пропущен TC-10** (#10): NO_FIX_INTENTIONAL.  
**Пропущен TC-11** (#11): CLI_OUTPUT_GAP — поведенческий тест требует arch decision M230.  
**Пропущен TC-12** (#12): DEFER.

---

## 4. Матрица покрытия (FIX_NOW находки → TC)

| Находка | Диспозиция | TC | REGRESSION_CONTRACTS | FIXTURE_CATALOG | CALLGRAPH |
|---------|-----------|----|--------------------|-----------------|-----------|
| #1 | FIX_NOW | TC-1 | ✓ | FX-1 | Q1 |
| #2 | FIX_NOW | TC-2 | ✓ | FX-2 | Q2 |
| #3 | FIX_NOW | TC-3 | ✓ | FX-3 | Q3 |
| #5 | FIX_NOW | TC-5 | ✓ | FX-5 | Q4 |
| #7 | FIX_NOW | TC-7 | ✓ | FX-7 | Q5 |
| #8a | FIX_NOW | TC-8a | ✓ | FX-8a | — |
| #8b | FIX_NOW | TC-8b | ✓ | FX-8b | Q6 |
| #9a | FIX_NOW | TC-9a | ✓ | FX-9a | — |
| #9b | FIX_NOW | TC-9b | ✓ | FX-9b | Q7 |
| #4 | INSTRUMENT_FIRST | — | — | — | §5 |
| #6 | INSTRUMENT_FIRST | — | — | — | §5 |
| #11 | INSTRUMENT_FIRST | — | — | — | §5 |
| #10 | NO_FIX | — | — | — | — |
| #12 | DEFER | — | — | — | — |

---

## 5. Статус проверки

**Все девять TC = SPECIFIED — не запущены.**  

Причина: M229_CODE_GO=NO. Тесты не могут быть запущены в production test suite  
без изменений `tests/` (запрещено) или без production fixtures (недоступны в handoff  
без изменения `src/`).

**Fail-before ожидаемое поведение (из accepted Sol M223–M227):**

| TC | Ожидается при baseline `3c011e94` |
|----|----------------------------------|
| TC-1 | Второй seed пропускается при `seed["id"] in used_seeds` |
| TC-2 | Body opener проходит без блокировки |
| TC-3 | `_hook_cands` вызывается без `clauses=` → может вернуть подмножество кандидатов |
| TC-5 | После drop: dur может упасть ниже min_sec без отброса |
| TC-7 | Refers unit удаляется → clip содержит refers к отсутствующему id |
| TC-8a | fit_rhythm appends question after build_passage; proposal ends question-last (M225 helper) |
| TC-8b | fix_open_end trims to 2.5s; final rhythm_why rejects and records rhythm_out (M225 helper) |
| TC-9a | При overlong nxt: break без попытки prv |
| TC-9b | После pop question-last: answer не добавляется |

---

## 6. Arch questions для M230

8 вопросов задокументированы в `CALLGRAPH_AND_ARCH_QUESTIONS.md §4`:

| Q | Находка | Тип | Требует |
|---|---------|-----|---------|
| Q1 | #1 | REQUIRED | Arch design |
| Q2 | #2 | REQUIRED | Arch design |
| Q3 | #3 | REQUIRED | **Owner decision** |
| Q4 | #5 | REQUIRED | Arch design |
| Q5 | #7 | REQUIRED | Arch design |
| Q6 | #8b | REQUIRED | **Owner decision** |
| Q7 | #9b | REQUIRED | **Owner decision** |
| Q8 | #11 | REQUIRED | Arch decision |

Owner decisions (Q3, Q6, Q7) constrain prospective behavior fixes **only in separately gated M232+**, after M230 architecture review and M231 observability-only independent Sol PASS + coordinator GO. M231 contains no behavior implementation.

---

## 7. Инварианты M229 (сохранены)

- `PRODUCTION_DIFF=NONE` — нет изменений в `src/`, `tests/`, `config/`, `main`.
- `M229_CODE_GO=NO` — явно в каждом документе.
- Доказательные уровни не расширены сверх M223–M227 Sol accepted.
- Feature-off parity: каждый TC включает negative (feature-flag off → parity с baseline).
- Нет обращений к owner-видео, платным API, рендеру.
- Нет повторных диагностических прогонов M223–M227.

---

## 7. P1 закрытие (Sol R1 → R2)

| Блокер | Секция | Статус |
|--------|--------|--------|
| P1-A: TC-1/FX-1 — u2 не в accepted clip, invalid set assertion | REGRESSION_CONTRACTS TC-1; FIXTURE_CATALOG FX-1 | RESOLVED — u1+u2 одна тема, gap=10.5s<30 → merged; accepted M223 §4-c/§4-d/§4-g; `not any(pr.units == [2] for pr in pool)` |
| P1-B: TC-3/FX-3 — clause branch недоступна с hook_teaser=true + одна фраза | REGRESSION_CONTRACTS TC-3; FIXTURE_CATALOG FX-3 | RESOLVED — hook_teaser=false; clause branch reachable; HELPER vs STATIC уровни разделены явно |
| P1-C: TC-7/FX-7 — неверные timing и string refers | REGRESSION_CONTRACTS TC-7; FIXTURE_CATALOG FX-7 | RESOLVED — M225 Case A: u1[50,76], u2[90,95], u3[160,193]; refers=1 и refers=2 (integer) |
| P1-D: TC-8a/FX-8a — инвертированный механизм (build_passage vs fit_rhythm) | REGRESSION_CONTRACTS TC-8a; FIXTURE_CATALOG FX-8a | RESOLVED — fit_rhythm appends question u3 (не build_passage loop); M225 Case B: u1[50,76], u2[90,93], u3[94,119] |
| P1-E: TC-8b/FX-8b — неверная стадия (fit_rhythm middle-piece vs fix_open_end) | REGRESSION_CONTRACTS TC-8b; FIXTURE_CATALOG FX-8b | RESOLVED — fix_open_end:625 trim → rhythm_why:273 rejects; rhythm_out записывает; M225 Case C |
| P1-F: Строки fix_open_end ~1080, stands_alone ~800; STATIC/OBSERVED не различены; break→continue без bounded termination | CALLGRAPH_AND_ARCH_QUESTIONS §1,§2,§3; Q7 | RESOLVED — fix_open_end STATIC-verified:625; stands_alone STATIC-verified:657; STATIC/OBSERVED метки в графе; Q7 помечен ARCH_QUESTION с bounded termination requirement |

---

## READY_FOR_SOL_QA

```
TASK=M229-PREP-R2
BASE_SHA=3c011e94263e16e5780936b4769d3490cd03b682
EVIDENCE_BASE=handoff/m228/REPORT.md (M228-R2, все P1 CLOSED)
R1_PIN=9fcb8159a217f517c1e141b96ea4c9ebbdc5712d
PRODUCTION_DIFF=NONE
M229_CODE_GO=NO
CHANGED_PATHS=handoff/m229/REGRESSION_CONTRACTS.md,
              handoff/m229/FIXTURE_CATALOG.md,
              handoff/m229/CALLGRAPH_AND_ARCH_QUESTIONS.md,
              handoff/m229/REPORT.md
TEST_IDS=TC-1,TC-2,TC-3,TC-5,TC-7,TC-8a,TC-8b,TC-9a,TC-9b
TEST_STATUS=SPECIFIED_NOT_EXECUTED
ARCH_QUESTIONS=Q1–Q7-b (Q3,Q6,Q7-b owner decision; Q7-a ARCH_QUESTION bounded termination)
P1_A=RESOLVED
P1_B=RESOLVED
P1_C=RESOLVED
P1_D=RESOLVED
P1_E=RESOLVED
P1_F=RESOLVED
READY_FOR_SOL_QA=YES
```

---

## Coordinator post-R2 documentation alignment (after independent Sol CHANGES_REQUIRED)

This alignment corrects stale cross-references and proof claims only: TC-2 actual first planned sound is a hook, not the body opener; FX-2 baseline vs pending post-fix assertions are separate and strict flags explicit; TC-5 25→23 consistent with FX-5; TC-8a fit_rhythm question append; TC-8b fix_open_end trim → rhythm_why reject with rhythm_out; integer refers; Q6 posttrim recovery; no M231 semantic fixes. The QA verdict on the original R2 SHA remains CHANGES_REQUIRED. These editorial changes are **NOT** a Sol PASS or authorization of M230/M231/M232; require a narrow independent check of the post-alignment commit. Tests remain SPECIFIED_NOT_EXECUTED and production untouched.
