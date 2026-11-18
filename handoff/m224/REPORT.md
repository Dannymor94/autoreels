# REPORT M224 Stage A R2 — CLI-доказательство находок #5 и #6

**Ветка:** `task/m224`  
**База:** `origin/main` → `3c011e94263e16e5780936b4769d3490cd03b682`  
**Дата:** 2026-11-19  
**Статус:** `IMPLEMENTED, GATE PENDING` — ожидает PASS Sol 6.1

---

## Финальный отчёт (R2)

```
TASK=M224-STAGE-A-R2
BASE_SHA=3c011e94263e16e5780936b4769d3490cd03b682
STATUS=READY_FOR_QA
REPRO_EXIT=0
CHECKS_EXECUTED=40

FINDING_5_CLI=CONFIRMED
  — cmd_autocut("synth", root=isolated_tmp, llm="none") вызван реально
  — spy на context_start захватил: refs '1.1-2'→'1.2', t0 100.0→102.0, dur 25.0→23.0
  — dur_after=23.0 < min_sec=25.0; клип выпущен propose() без min_sec-проверки
  — generator=mixed из production r0.yaml; AutoParams из CLI ✓

FINDING_6_START_CLI=CONFIRMED
  — spy на context_start: t0_after=102.0, S1.2 начинается в 102.4s → drift=0.4s
  — 0.4s = пауза 102.0→102.4 не включена в rows[0][1] = sec("Уйти.") = 2.0

FINDING_6_END_CLI=CONFIRMED
  — prosody.json загружен (нет предупреждения об интонации)
  — spy на fix_open_end: refs '2.1-2'→'2.1', t1 232.0→229.0
  — drift=1.0s = пауза 228.0→229.0 не включена в cut=sec("Завтра.")=3.0
  — total-cut=29.0 ≥ min_sec=25.0 → guard проходит, клип выпущен с дрейфом

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

## §1 Метод R2 (изменения по сравнению с R1)

| Проблема Sol QA R1 | Решение R2 |
|---|---|
| A1: нет вызова cmd_autocut | `cmd_autocut("synth", root=isolated_tmp, llm="none")` вызывается в §1 |
| A2: изменён generator="passage" и другие поля | AutoParams берётся из первого propose()-spy-вызова (CLI-конфиг), generator=mixed ✓ |
| A3: хардкод audio timings | Используются реальные временны́е метки слов из синтетического транскрипта |
| A4: нет доказательства CLI-пути | Spy на context_start и fix_open_end перехватывает реальные before/after значения |

**Общая схема:**
- Изолированный tmpdir: config/ manifests/ transcripts/ data/cache/ reviews/ out/
- `config/r0.yaml` скопирован из production (SHA неизменён)
- Синтетический транскрипт с 11 словами в двух блоках + tail-слова (340-360s)
- `transcripts/synth.prosody.json` — синтетическая карта интонаций для block 2
- `cmd_autocut("synth", root=tmp, llm="none")` вызывается с patch на context_start, fix_open_end, propose
- Прямые вызовы помечены `HELPER_CONFIRMED`

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
| `autocut.generator` | mixed | режим генератора (не passage) |
| `sentence_pause_sec` | 0.35 | граница границ предложений |
| `min_pause_for_phrase_end` | 1.5 | граница разрыва блоков |

**r0.yaml SHA256:** `efdef3adb0396e7e282553a8e3bfb0c690df015abdb8398cea1db5e642aeabba`

---

## §3 Синтетический транскрипт

**Block 1 (finding #5 + #6-start):** t0=100.0, t1=125.0, refs="1.1-2"
```
S1.1: "Уйти."     100.0–102.0  (1 слово; stands_alone → "обрывок (1 сл.)")
      gap 0.4s (> sentence_pause_sec=0.35 → граница предложения;
                < min_pause_for_phrase_end=1.5 → тот же блок)
S1.2: "Принятие тревоги снижает интенсивность переживаний навсегда."
                   102.4–125.0  (6 слов; stands_alone → None)
```

**Block 2 (finding #6-end):** t0=200.0, t1=232.0, refs="2.1-2"
```
S2.1: "Принятие тревоги снижает интенсивность переживаний."
                   200.0–228.0  (5 слов; prosody t0=205.0, end_pct=15 → "final")
      gap 1.0s (< min_pause_for_phrase_end=1.5 → тот же блок)
S2.2: "Завтра."   229.0–232.0  (1 слово; prosody t0=229.0, end_pct=75 → "open")
```

**Tail block (340-360s):** midpoint=350 > 360-30=330 → tail-filtered → total_duration=360.0

Tail-filter для block 1 midpoint=112.5 < 330 → kept ✓  
Tail-filter для block 2 midpoint=216.0 < 330 → kept ✓

---

## §4 Находка #5 — CONFIRMED via CLI

**Доказательство:**
```
context_start spy (вызван из cmd_autocut):
  unit_id=1
  refs_before='1.1-2', refs_after='1.2'
  t0_before=100.0, t0_after=102.0
  dur_before=25.0, dur_after=23.0

dur_after=23.0 < min_sec=25.0 — no min_sec recheck in short-drop (autocut.py:718)
propose() испустил Proposal(refs='1.2', seconds=23.0) [stdout: M1 90@1.05 | 1.2]

Для сравнения — ветка context_later (строка 749) имеет guard:
  if left < p.context_later_min_sec or sum(_dur(c) for c in clip) - (total - left) < p.min_sec:
      break  ← есть проверка min_sec
context_later=False в production config → эта ветка выключена.
```

---

## §5 Находка #6 (начало) — CONFIRMED via CLI

**Доказательство:**
```
context_start spy:
  t0_after=102.0 (конец S1.1 "Уйти.")
  S1.2 первое слово "Принятие" начинается в 102.4s
  drift = 102.4 - 102.0 = 0.4s

Строка 718 (autocut.py):
  clip = [{**u, "refs": refs, "t0": float(u["t0"]) + float(rows[0][1])}] + clip[1:]
           ↑ t0 += rows[0][1] = sec("Уйти.") = 2.0 (только длительность предложения)
  Пауза 102.0→102.4 не включена → клип начинается с 0.4s тишины
```

---

## §6 Находка #6 (конец) — CONFIRMED via CLI

**Доказательство:**
```
fix_open_end spy (вызван из cmd_autocut):
  unit_id=2
  refs_before='2.1-2', refs_after='2.1'
  t1_before=232.0, t1_after=229.0

Механизм:
  end_tone("2.2") = "open" (prosody: t0=229.0, end_pct=75 ≥ 60)
  end_tone("2.1") = "final" (prosody: t0=205.0, end_pct=15 ≤ 30)
  cut = sec("Завтра.") = 232.0 - 229.0 = 3.0 (только длительность предложения)
  total - cut = 32.0 - 3.0 = 29.0 ≥ min_sec=25.0 → guard проходит
  new_last.t1 = 232.0 - 3.0 = 229.0

Фактическое последнее слово S2.1 ("переживаний.") заканчивается в 228.0s.
Дрейф: 229.0 - 228.0 = 1.0s тишины включено в t1 (пауза 228.0→229.0 перед S2.2).

Строка 640 (autocut.py):
  cut += float(rows[k][1] or 0.0)   # только sec предложения, не пауза до него
  new_last = {**last, "refs": refs, "t1": float(last["t1"]) - cut}
```

---

## §7 Запуск

```bash
cd /path/to/autoreels-m223
.venv/bin/python handoff/m224/REPRO.py
# → PASS: 40 проверок, 0 сбоев
echo $?  # → 0
```

**Вывод CLI:**
```
autocut synth: предложено сборок 2 из 2 мыслей → ...
  M1 90@1.05 | 1.2 | ...    ← refs="1.2" (не "1.1-2"), dur=23s < min_sec
  M2 89@1.05 | 2.1 | ...    ← refs="2.1" (не "2.1-2"), t1=229.0
```

---

## §8 Таблица

| Находка | Статус | Метод | Доказательство |
|---|---|---|---|
| #5 min_sec no-recheck | **CONFIRMED** | CLI spy + HELPER_CONFIRMED | §4: dur_after=23.0 < min_sec=25.0; propose emits; spy intercepts real call |
| #6 start (context_start) | **CONFIRMED** | CLI spy + HELPER_CONFIRMED | §5: t0=102.0, S1.2 starts at 102.4, drift=0.4s |
| #6 end (fix_open_end) | **CONFIRMED** | CLI spy + prosody + HELPER_CONFIRMED | §6: t1=229.0, last S2.1 word ends at 228.0, drift=1.0s |

---

## §9 Целостность

Производственный код не изменён. `manifests/`, `transcripts/`, `reviews/`, `reels-out/` — не затронуты.  
Тесты не изменены. `config/r0.yaml` скопирован, не изменён.

---

## §10 R2 vs R1

| Критерий Sol QA | R1 | R2 |
|---|---|---|
| cmd_autocut вызван | ✗ Нет | ✓ Да (`llm="none"`) |
| generator=mixed (production) | ✗ generator="passage" | ✓ Из CLI spy, generator='mixed' |
| Временны́е метки из транскрипта | ✗ Хардкод | ✓ Реальные слова с метками |
| Prosody для end_tone | ✗ Мок | ✓ synth.prosody.json загружен |
| Прямые вызовы | только эти | HELPER_CONFIRMED (доп. к CLI) |

---

## Следующий шаг

Запрос на независимое ревью Sol 6.1 на текущем SHA handoff HEAD. Правка кода не начинается без PASS.
