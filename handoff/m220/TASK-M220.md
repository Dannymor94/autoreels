# TASK M220 (окно MAIN, Mac): `docs/PIPELINE.md` — весь путь по шагам

**Ложится на:** `main` после M219 (`2ee3053`). **Файлы:** `handoff/m220/` — `TASK-M220.md`, `m220-pipeline-doc.patch`.
**Время:** ~3 минуты. Только документация. **Отчёт — только на русском.**

## Зачем
Владелец, 2026-11-10: нужна цельная картина — как работает механика, логика и код по каждому шагу. Разрозненно это лежало в `PLAN.md` (решения и замеры), `REEL_SPEC.md` (правила клипа), `GAMEBOX.md` (машины) и в комментариях модулей. Единого прохода по пути не было.

## Что вносит патч
- **`docs/PIPELINE.md`** (новый): девять шагов `arl auto` — что делает каждый, какая за ним логика, зачем он так устроен (с причинами: почему время берётся по звуку, почему похожесть считается по сыгранным фразам, почему каждый отказ печатается) и где это в коде с размерами модулей. В конце — что держит систему вместе: граница облако/локаль, «решает код», кэш ответов, флаги и замеры.
- `README.md` — ссылка на новый документ рядом со ссылкой на `REEL_SPEC.md`.
- `PROJECT_STRUCTURE.md` — строка файла.

## Правила
1. Любая строка `FAIL: …` или упавшая команда → **СТОП**: команда и последние 40 строк. Ничего не чинить.
2. Ничего, кроме этих трёх файлов. Без рендера и без `arl auto`.
3. `data/token_scale.json` не коммитить и из подсчётов исключать; неотслеживаемые файлы (`??`) не трогать.
4. Итог — «DOCUMENTED».

## Часть 1. Патч и коммит
```bash
cd /Users/danny/Documents/autoreels
bash handoff/bin/take.sh m220
base=$(git log --format=%h -1); test "$base" = "2ee3053" && echo "OK база" || echo "FAIL: база $base, нужна 2ee3053 (M219)"
git apply --check handoff/m220/m220-pipeline-doc.patch && git apply handoff/m220/m220-pipeline-doc.patch && echo "OK патч" || echo "FAIL: патч не лёг"
test -f docs/PIPELINE.md && echo "OK файл создан" || echo "FAIL: docs/PIPELINE.md нет"
steps=$(grep -c "^## Шаг " docs/PIPELINE.md)
test "$steps" -ge 8 && echo "OK шагов $steps" || echo "FAIL: шагов $steps, ждали ≥ 8"
grep -q "docs/PIPELINE.md" README.md && echo "OK ссылка в README" || echo "FAIL: ссылки нет"
git add docs/PIPELINE.md README.md PROJECT_STRUCTURE.md
git commit -q -m "Docs (M220): docs/PIPELINE.md — the whole path step by step: what each step does, the reasoning behind it (why time comes from the sound, why closeness is counted in played sentences, why every refusal is printed) and where it lives in the code; linked from README and the structure"
git push -q && echo "OK запушено" || echo "FAIL: push"
git log --oneline -1
dirty=$(git status -s | grep -v "^??" | grep -v "data/token_scale.json" | wc -l | tr -d " ")
test "$dirty" = 0 && echo "OK отслеживаемое закоммичено" || { echo "FAIL: осталось $dirty"; git status -s | grep -v "^??" | grep -v "data/token_scale.json"; }
```
Ожидается: семь строк `OK`. Тесты не нужны — кода патч не меняет.

## Отчёт
`handoff/m220/REPORT.md`:
```
M220 — DOCUMENTED
Коммит: <хэш>; шагов в документе: <n>
Проверки: <все OK / какие FAIL>
```
```bash
bash handoff/bin/report.sh m220
```
Владельцу в чат — 1 строка: «M220 — DOCUMENTED, коммит <хэш>: `docs/PIPELINE.md` — весь путь по шагам».
