# TASK M211 (окно MAIN, Mac): голос в оценке клипа — замер на клипах владельца

Файлы — ветка `handoff`, папка `handoff/m211/`: `TASK-M211.md`, `m211-voice-check.patch` (ложится на `main` после M210).
Около 5 минут, только чтение. Отчёт — только на русском.

## Зачем
PLAN M1.9, этап E: голос как признак оценки клипа. Прежде чем вводить его в счёт, нужно измерить: отличает ли голос (громкость, тон, размах тона, темп, сводная энергия) мысли, которые владелец взял в свои клипы, от остальных? Для сравнения рядом — сила мысли по модели.

## Что вносит патч
- `tools/voice_owner_check.py`:
  - мысли карты против ручных клипов владельца (`manifests/<ист>.json`, `selection_source: human`); мысль — «владельца», если ≥ 50 % её времени внутри тела его клипа;
  - для каждого признака — AUC «мысли владельца против остальных» внутри источника (по рангам): 0,50 — не отличает; ≥ 0,60 или ≤ 0,40 — сигнал.
- `tests/test_m211_voice_owner.py` — 2 теста.
- `PROJECT_STRUCTURE.md` — строка инструмента.

Ассистент прогнал весь набор: 2690 прошли, упали прежние 7 и флейк menu.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить. Любые числа AUC — не СТОП.
2. Ничего, кроме того, что вносит патч. **Без рендера**, без `arl auto`. `data/token_scale.json` не коммитить.
3. Итог — «IMPLEMENTED, MEASURED».

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1
bash handoff/bin/take.sh m211
git apply --check handoff/m211/m211-voice-check.patch && git apply handoff/m211/m211-voice-check.patch && echo applied
.venv/bin/python -m pytest tests/test_m211_voice_owner.py -q 2>&1 | tail -1
git add PROJECT_STRUCTURE.md tools/voice_owner_check.py tests/test_m211_voice_owner.py
git commit -m "Voice check (M211): tools/voice_owner_check.py — the AUC of each voice measure (level, pitch, range, rate, energy) and of the model's strength for the owner's thoughts against the rest, within each source; read only"
git push; git log --oneline -1
git status -s | grep -v "handoff/\|data/token_scale.json" || echo "всё закоммичено"
```
Ожидается: последний коммит до — M210; `applied`; `2 passed`; коммит запушен; «всё закоммичено».

## Часть 2. Замер
```bash
cd /Users/danny/Documents/autoreels
.venv/bin/python tools/voice_owner_check.py 2>&1 | tee handoff/m211/voice.txt
```
Ожидается: строка на каждый источник (у `prew_isaev_danny` может быть «нет ручной разметки владельца» — не СТОП) и строка «ВСЕ» с AUC по 6 признакам.

## Отчёт
`handoff/m211/REPORT.md`:
```
M211 — IMPLEMENTED, MEASURED
Коммит: <хэш>
AUC по всем источникам: громкость <…>, тон <…>, размах тона <…>, темп <…>, энергия <…>, сила (модель) <…>
Мыслей владельца: <n>
```
```bash
bash handoff/bin/report.sh m211 voice.txt
```
Владельцу в чат — 2 строки:
1. статус и коммит;
2. «голос и клипы владельца (AUC, 0,5 — нет сигнала): энергия <…>, громкость <…>, темп <…>; сила по модели <…>».
