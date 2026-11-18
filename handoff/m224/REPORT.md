# REPORT M224 Stage A — Доказательство находок #5 и #6

**Ветка:** `task/m224`  
**База:** `origin/main` → `3c011e94263e16e5780936b4769d3490cd03b682`  
**Дата:** 2026-11-18  
**Статус:** `IMPLEMENTED, GATE PENDING` — ожидает PASS Sol 6.1

---

## Финальный отчёт

```
TASK=M224-STAGE-A
BASE_SHA=3c011e94263e16e5780936b4769d3490cd03b682
STATUS=READY_FOR_QA
REPRO_EXIT=0
CHECKS_EXECUTED=44

FINDING_5_CLI=CONFIRMED
  — context_start short-drop (autocut.py:718): t0 += rows[0][1] = длительность только предложения
  — ветка context_later (строки 749) имеет проверку min_sec; short-drop — нет
  — propose() испускает клип с seconds=23.0 при min_sec=25.0 (нет повторной проверки)
  — прямой вызов context_start() с production AutoParams через load_r0_config

FINDING_6_END_CLI=CONFIRMED
  — fix_open_end (autocut.py:640): cut += rows[k][1] = только длительность предложения
  — пауза 24–28s не включена в cut: new_last.t1 = 31.0 - 3.0 = 28.0
  — фактический конец последнего слова: 24.0s; дрейф = 4.0s тишины в t1
  — total - cut = 28.0 ≥ min_sec=25.0 → guard min_sec проходит, дрейф не фильтруется

FINDING_6_START_CLI=CONFIRMED
  — context_start short-drop (autocut.py:718): t0 += rows[0][1] = только 2.0s (длительность 1.1)
  — пауза 2–6s не включена: t0 = 2.0, а фактически 1.2 начинается в 6.0s
  — дрейф = 4.0s тишины атрибутируется началу клипа

PRODUCTION_DIFF=нет (ни одного файла production не изменено)
OWNER_ARTIFACT_PARITY=нет изменений manifests/transcripts/reviews/reels-out/
CONFIG_SHA=config/r0.yaml: efdef3adb0396e7e282553a8e3bfb0c690df015abdb8398cea1db5e642aeabba
BLOCKERS=нет
```

---

## §0 Гейт M223

M223 прошёл независимое ревью Sol 6.1 (PASS) с SHA `9bb5667386b70ac93f041b8abb9f22359dbca286`.  
Текущий main: `3c011e94263e16e5780936b4769d3490cd03b682`.

---

## §1 Метод

**Путь CLI-конфига:**
- `load_r0_config(ROOT / "config/r0.yaml")` → `r0_cfg.autocut`
- `AutoParams(...)` собран зеркально `cmd_autocut` (`__main__.py:8609–8634`)
- Вызовы `context_start()` и `fix_open_end()` из `cloud/autocut.py` напрямую с этим `prm`
- `propose()` вызван для подтверждения end-to-end испускания

**Изолированная синтетика:**
- Нет API, нет рендера, нет записи в owner-артефакты
- Временный корень не используется (только in-memory данные)

---

## §2 Конфигурация из config/r0.yaml

| Ключ | Значение | Значимость |
|---|---|---|
| `autocut.min_sec` | 25 | граница допустимой длительности клипа |
| `autocut.context_start` | true | активирует short-drop ветку |
| `autocut.context_drop_words` | 5 | ≤5 слов → кандидат на short-drop |
| `autocut.context_min_words` | 4 | <4 слов → `stands_alone` → "обрывок" |
| `autocut.context_later` | false | ветка с проверкой min_sec ВЫКЛЮЧЕНА |
| `autocut.end_tone` | true | активирует `fix_open_end` |

**r0.yaml SHA256:** `efdef3adb0396e7e282553a8e3bfb0c690df015abdb8398cea1db5e642aeabba`

---

## §3 Находка #5 — CONFIRMED

**Механизм:** `context_start` short-drop (autocut.py строка 718) не проверяет min_sec.

```
context_later (строки 749):
  if left < p.context_later_min_sec or sum(_dur(c) for c in clip) - (total - left) < p.min_sec:
      break  ← есть проверка min_sec

short-drop (строка 718):
  clip = [{**u, "refs": refs, "t0": float(u["t0"]) + float(rows[0][1])}] + clip[1:]
           ↑ нет проверки нового _dur против min_sec
```

**Синтетический сценарий:**
```
Мысль: id=1, t0=0.0, t1=25.0, _dur=25.0 = min_sec (проходит initial gate)
  1.1: sec=2.0, 1 слово "Уйти." → stands_alone → "обрывок (1 сл.)"
       nwords=1 ≤ context_drop_words=5 → short-drop применяется
  1.2: sec=23.0, 6 слов → stands_alone → None (проходит)

После short-drop:
  clip[0].t0 = 0.0 + 2.0 = 2.0
  clip[0].t1 = 25.0 (не изменился)
  _dur(clip[0]) = 23.0 < min_sec=25.0 — no check!

propose(): secs = 23.0 → Proposal(seconds=23.0) испущен
  "M1 88 | 1.2 | t: ... | seconds=23.0"
```

**Ключевые параметры:**
- `refs` до: `"1.1-2"` → после: `"1.2"` (_drop_first_ref)
- `seconds` в предложении: **23.0** при `min_sec=25.0`
- `no_start` список: **пуст** (клип не отброшен)

---

## §4 Находка #6 (конец) — CONFIRMED

**Механизм:** `fix_open_end` вычитает только длительность предложения из `t1`, не включая паузу перед ним.

```python
# autocut.py строки 639-647:
for k in range(len(rows) - 1, 0, -1):
    cut += float(rows[k][1] or 0.0)   # ← только sec предложения
    if total - cut < p.min_sec:
        break
    ...
    new_last = {**last, "refs": refs, "t1": float(last["t1"]) - cut}
```

**Синтетический сценарий:**
```
Мысль: id=1, t0=0.0, t1=31.0
  1.1: sec=24.0, аудио 0–24s → end_tone "final"
  [пауза 4s: 24–28s — не отражена в sec]
  1.2: sec=3.0, аудио 28–31s → end_tone "open" («→»)

fix_open_end:
  total = 31.0, cut += 3.0 = 3.0
  total - cut = 28.0 ≥ min_sec=25.0 → guard проходит
  new_last.t1 = 31.0 - 3.0 = 28.0

Фактическое последнее слово 1.1: 24.0s
Дрейф: 28.0 - 24.0 = 4.0s тишины включено в t1
```

**Итог:** Манифест заявляет `t1=28.0`, но слышимое аудио заканчивается в `24.0s`. Клип включает 4s пост-речевой тишины (пауза перед отброшенным 1.2).

---

## §5 Находка #6 (начало) — CONFIRMED

**Механизм:** `context_start` short-drop прибавляет только `rows[0][1]` (длительность первого предложения) к `t0`, не учитывая паузу до следующего.

**Синтетический сценарий:**
```
Мысль: id=1, t0=0.0, t1=29.0
  1.1: sec=2.0, аудио 0–2s → stands_alone → "обрывок"
  [пауза 4s: 2–6s — не отражена в sec]
  1.2: sec=23.0, аудио 6–29s → stands_alone → None

Строка 718:
  clip[0].t0 = 0.0 + rows[0][1] = 0.0 + 2.0 = 2.0

Фактическое начало 1.2: 6.0s
Дрейф: 6.0 - 2.0 = 4.0s — первые 4s клипа содержат только тишину
```

---

## §6 Комбинированный сценарий (#5 + #6 вместе)

При достаточно длинной паузе оба дефекта проявляются одновременно:

```
Мысль: t0=0.0, t1=26.0 (только что ≥ min_sec=25.0)
  1.1: sec=2.0 (аудио 0–2s)
  [пауза 4s: 2–6s]
  1.2: sec=20.0 (аудио 6–26s)

После short-drop:
  t0=2.0 (дрейф 4s, аудио с 6s)       ← FINDING #6 start
  _dur = 24.0 < min_sec=25.0           ← FINDING #5 (no recheck)

propose(): seconds=24.0 при min_sec=25.0 → испущен
```

---

## §7 Запуск

```bash
cd /path/to/autoreels-m223
.venv/bin/python handoff/m224/REPRO.py
# → PASS: 44 проверок, 0 сбоев
echo $?  # → 0
```

---

## §8 Таблица

| Находка | Статус | Метод | Доказательство |
|---|---|---|---|
| #5 min_sec no-recheck | **CONFIRMED** | CLI-config + direct call + propose() | §1: seconds=23.0 при min_sec=25.0; no_start=[]; propose emits |
| #6 end (fix_open_end) | **CONFIRMED** | CLI-config + direct call | §2: t1=28.0, last_word=24.0, drift=4.0s |
| #6 start (context_start) | **CONFIRMED** | CLI-config + direct call | §3: t0=2.0, audio_start=6.0, drift=4.0s |

---

## §9 Целостность

Производственный код не изменён. `manifests/`, `transcripts/`, `reviews/`, `reels-out/` — не затронуты.  
Тесты не изменены.

---

## Следующий шаг

Запрос на независимое ревью Sol 6.1 на текущем SHA handoff HEAD. Правка кода не начинается без PASS.
