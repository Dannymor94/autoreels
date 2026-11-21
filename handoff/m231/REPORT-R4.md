# M231-R4 — отчёт (исправление находки P1-R3-1)

**TASK** = M231-R4-LOOP-ORACLE-FIX · **ROLE** = IMPLEMENTER
**BRANCH** = `task/m231-r4` · **PR (draft)** = #22 (база `task/m231-r3-codex`)
**R3_SHA** = `07b24d30917cc45f5b1be32b9c2647b0835abc1c`
**R4_SHA** = `9f09cbd823583fe0266164b50ebe03135b8c0f5c`
**PRODUCTION_SHA (frozen)** = `3c011e94263e16e5780936b4769d3490cd03b682`
**Issue #21** (Sol R3 QA) · **Issue #17** (архитектурное решение A/B/C)

Статус: **IMPLEMENTED, GATE PENDING — STOP_FOR_INDEPENDENT_SOL_R4_QA.** Не мержить, M232 не трогал.

---

## Что было не так (находка P1-R3-1)

Кейс покрытия `loop_question` в R3 передавал в настоящий `build_clip` юниты
`[1(тезис), 2(вопрос)]`. Реальный `build_clip` возвращает клип **с вопросом
впереди — `[2, 1]`**. Защита петли в `propose` (`clip[0].role != "question"`)
тогда не срабатывает, и пропатченный `_loop_question` **не вызывается ни разу**:
`S0 == S1 == [2, 1]`, call count = 0, `expected = None`.

Итог: фикстура доказывала «билдер дал вопрос-первым», а не путь **введения
вопроса-петли**, который требует покрыть раздел C архитектурного решения.

## Исправление (строго: тесты, фикстуры, голден, документация)

Кейс закреплён на реальном prepend:

- `build_clip` → `[1]` (не-вопросный опенер) ⇒ защита петли срабатывает;
- `_loop_question` → вопрос (id 2, `punch 3 < seed_punch` ⇒ сам он **не** сид) ⇒
  `propose` его подставляет в начало.
- Результат: **S0=`[1]`, S1=`[2, 1]`, `_loop_question` вызван ровно один раз,
  терминальный исход `pooled`.**

Файлы (diff R3 → R4, **4 файла, +54/−9**, `src/` не затронут):

| Файл | Что |
|---|---|
| `tests/fixtures/m231/compare_off_golden.py` | кейс `loop_question`: патч `build_clip→[1]` + сохранён `_loop_question`; `expected = {"pooled"}` |
| `tests/test_m231_trace.py` | новый `test_loop_question_is_reached_and_prepends` — проверяет call count == 1 и точный переход S0→S1 (не-вакуумно) |
| `tests/fixtures/m231/frozen_production_off_golden.json` | `expected.coverage.loop_question.proposals_sha256` перегенерирован из чистого detached `3c011e9`; обновлены blob-SHA двух изменённых файлов; база голдена и `cli_expected` без изменений |
| `tests/fixtures/m231/README.md` | описание исправления |

Единственная сдвинувшаяся строка голдена —
`loop_question.proposals_sha256`: `2d68b128…` → `5c78e3c7…`. Финальный клип тот
же `[2, 1]`, но его Proposal теперь несёт заметку вопроса-петли.

## Доказательства (локально, офлайн, синтетика; Python 3.12.14, pydantic 2.14.4)

1. **Голден перегенерирован независимо из чистого detached `3c011e9`.**
   Production OFF = candidate OFF = candidate ON — **байт-в-байт идентичны** под
   `PYTHONHASHSEED=0/42/1337`, и для proposal-генератора, и для CLI-генератора
   (9 из 9 прогонов на каждый генератор → один SHA).
   - `compare_off_golden.py` OFF/ON/frozen × 0/42/1337 → единый SHA `462c25c0…`.
   - `compare_cli_off_golden.py` × 9 → единый SHA; `cli_expected` не изменился
     (`review f8a64444…`, `stdout 017b7f75…`, `stderr 24bc2345…`, rc 0).
   - Preflight `--frozen-only` печатал `HEAD=3c011e9… CLEAN=True`, источник из
     `prod/src`.
2. **Фокусные тесты** `tests/test_m231_trace.py`: **46 passed** на каждом
   hashseed 0/42/1337 (в R3 было 45; +1 — новый loop-тест).
3. **Offline-smoke** (5 файлов CI): **163 passed**.
4. **Полный прогон, одна среда, exact failed-node parity** (PATH=/usr/bin:/bin,
   ключи пусты, прокси на localhost):
   - R4: **43 failed / 2697 passed / 56 skipped / 9 deselected**.
   - R3: **43 failed / 2696 passed / 56 skipped / 9 deselected**.
   - Множества падающих нод **идентичны**, `new=0`, `disappeared=0`; дельта
     `+1 passed` — это новый loop-тест. Ни одной m231-ноды среди падений.
   - Это среды́нные baseline-падения (нет ffmpeg/медиа-зависимостей), не
     all-green; абсолютное число зависит от среды и сравнивается только R4↔R3 в
     одной среде (Sol воспроизводит против своего baseline).
5. **OFF-паритет** сохранён структурно: `git diff 07b24d3 -- src/` пуст — runtime
   не менялся.

Вейвер (дословно, как в README и голдене):
`EVIDENCE=REPRODUCIBLE_FROZEN_GOLDEN — chronological pre-patch capture was NOT achieved; replaced by independent regeneration from immutable 3c011e9. No retroactive claim.`

## Границы

Изменены только `tests/**` и `tests/fixtures/m231/**` (пункт 3 allowlist) +
этот отчёт (пункт 4). Production-код, конфиг, схема манифеста, `build_passage`,
M232, медиа и провайдеры — не тронуты. Merge не делал.

```
TASK=M231-R4-LOOP-ORACLE-FIX
R3_SHA=07b24d30917cc45f5b1be32b9c2647b0835abc1c
R4_SHA=9f09cbd823583fe0266164b50ebe03135b8c0f5c
PRODUCTION_SHA=3c011e94263e16e5780936b4769d3490cd03b682
PR=https://github.com/Dannymor94/autoreels/pull/22  (draft, base task/m231-r3-codex)
DIFFSTAT=4 файла, +54/−9; src/ не затронут
GOLDEN_DELTA=только loop_question.proposals_sha256: 2d68b128… → 5c78e3c7…
PARITY=production OFF = candidate OFF = candidate ON, байт-в-байт, seeds 0/42/1337 (proposal и CLI)
LOOP_ORACLE=S0=[1], S1=[2,1], _loop_question вызван 1 раз, outcome pooled
TESTS=test_m231_trace 46 passed ×(0/42/1337); offline-smoke 163 passed
FULL_SUITE=R4 43 failed/2697 passed; R3 43 failed/2696 passed; failed-node set идентичен, new=0
OFF_PARITY=структурно (src/ без изменений)
STOP_FOR_INDEPENDENT_SOL_R4_QA
```
