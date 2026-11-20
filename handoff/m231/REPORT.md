# M231 — Отчёт реализации

TASK=M231-OBSERVABILITY-IMPLEMENTATION  
BRANCH=task/m231-observability  
BASE_SHA=3c011e94263e16e5780936b4769d3490cd03b682  
FINAL_SHA=1f3c7a4  
DATE=2026-11-20

## Статус

IMPLEMENTED, GATE PENDING — **STOP_FOR_INDEPENDENT_SOL_CODE_QA**

## Diffstat

```
src/autoreels/__main__.py      |  78 +++++++-
src/autoreels/cloud/autocut.py | 198 +++++++++++++++++++-
tests/test_m231_trace.py       | 407 +++++++++++++++++++++++++++++++++++++++++
3 files changed, 681 insertions(+), 2 deletions(-)
```

Файлы вне разрешённого списка: **не тронуты**. Изменены только `src/autoreels/cloud/autocut.py`, `src/autoreels/__main__.py`, `tests/test_m231_trace.py`.

## Что реализовано

### autocut.py::propose

- Добавлен trailing параметр `trace: list | None = None`
- Инициализация `_tr` в начале каждой итерации цикла `for seed in seeds:` — только под `if trace is not None:`
- Snap-поля S0–S6 заполняются по факту прохождения стадий
- Девять выходов цикла — каждый под `if trace is not None:` с `trace.append(_tr)` и соответствующим `outcome`:
  - `skip_used` / `skip_taken` — строка 1175–1176
  - `build_none` — строка 1178–1179
  - `rhythm_fail` — строка 1201–1204
  - `start_fail` — строка 1228–1231
  - `open_end_fail` — строка 1241–1244
  - `final_rhythm_fail` — строка 1252–1255
  - `taken_after_context` — строка 1257–1258
  - `overlap_or_payoff` — строка 1259–1261
  - `pooled` — после `out.append` строка 1300
- Truncate-событие перед `return out[:p.clips]`
- Поля: `schema`, `event`, `seed`, `outcome`, `sup`, `snap`, `dep_broken`, `tail_question`, `secs`, `spans_final`, `proxy_q_after`, `proxy_overlong_side`

### __main__.py::cmd_autocut

- `ARL_AUTOCUT_TRACE` читается через `os.environ.get()`; при не заданном env — `_trace = None`, никакого кода не выполняется
- Обогащение timing (M231.3) — из `sent_by_ref` для span-ов с `spans_final`
- `select` события на каждый элемент пула
- `fate` события после полного цикла выбора
- JSONL запись: `json.dumps(..., sort_keys=True, ensure_ascii=False)` с `_rflt()` для округления float до 3 знаков

## Тесты (tests/test_m231_trace.py)

18 тестов, все прошли:

| Тест | Проверяет |
|---|---|
| `test_p1_trace_none_vs_empty_equal_proposals` | P1: trace не меняет Proposals |
| `test_p1_no_start_open_end_rhythm_out_unchanged` | P1: side-lists неизменны |
| `test_p3_seed_count_and_truncate` | P3: accounting identities |
| `test_p3_seed_order_matches_seeds` | P3: структура событий |
| `test_p4_deterministic_trace` | P4: byte-identical повторные прогоны |
| `test_p5_no_extra_callback_calls` | P5: taste spy равные вызовы |
| `test_p6_trace_file_in_tmp_path` | P6: файл не в репозитории |
| `test_p11_pooled` | P11: outcome=pooled |
| `test_p11_skip_used` | P11: skip_used |
| `test_p11_build_none_passage` | P11: build_none |
| `test_p11_start_fail` | P11: start_fail |
| `test_p11_overlap_or_payoff` | P11: overlap_or_payoff |
| `test_p11_all_basic_outcomes_present` | P11: S0 snap по типам |
| `test_p9_timing_deltas` | P9: d0=d1=0.4, err=0 |
| `test_p10_sparse_timing_no_sentence` | P10: no_sentence → null |
| `test_p10_sparse_timing_no_refs` | P10: no_refs |
| `test_p10_sparse_timing_no_words` | P10: no_words |
| `test_p10_secs_delta_null_when_incomplete` | P10: secs_delta=null при неполных |

## CI / полный прогон

**Baseline (3c011e9, до M231):** 2728 passed, 2 failed (test_snap.py — pydantic_core, pre-existing на 3c011e9)

**После M231 (1f3c7a4):** 2746 passed, 2 failed — те же 2 test_snap.py. Разница +18 — новые M231 тесты.

compare_failures.py выдаёт 2 "new" (test_snap) и 29 "disappeared" — последние были в baseline f92b4d2 (до CI-коммита de127df), на 3c011e9 они уже проходят, M231 их не трогал.

**Ни одного нового провала от M231.**

## OFF parity (ключевые проверки)

- `test_autocut.py` (72 теста) — все прошли до и после M231
- `test_auto.py` — все прошли
- `test_m202/m203/m205` — все прошли (эти тесты проверяют review SHA и stdout)
- Когда `ARL_AUTOCUT_TRACE` не задан: в propose() никаких веток не выполняется, `_trace=None`, stdout/stderr идентичны frozen path

## Стоп-условия (кодекс CODE-GO-M231-LIMITED.md)

- Allowlist: только 3 файла, не тронуто ничего вне списка ✅
- OFF байт-идентичен: trace None vs [] → равные Proposals ✅
- Callback-ами trace не пользуется ✅
- Нет network/paid models/owner media/render ✅
- Failure set не увеличился ✅

---

STOP_FOR_INDEPENDENT_SOL_CODE_QA — Issue #14
