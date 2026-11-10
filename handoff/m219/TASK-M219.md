# TASK M219 (окно MAIN, Mac): свести документацию с кодом — итог этапа, M216 в плане, `remote.py` в структуре

**Ложится на:** `main` после M218 (`4afeb08`). **Файлы:** `handoff/m219/` — `TASK-M219.md`, `m219-docs-gaps.patch`.
**Время:** ~3 минуты. Только документация: кода, конфигов и тестов не трогает. **Отчёт — только на русском.**

## Зачем
Владелец, 2026-11-10: «закоммитить всё и задокументировать». Код M201–M218 уже в `main`, каждая веха со своей документацией. Ассистент сверил документы с кодом и нашёл три пробела:
1. **M216** (формат задач для агентов) не попала в `PLAN.md` — единственная веха этапа без строки в плане.
2. **`src/autoreels/local/remote.py`** не упомянут в `PROJECT_STRUCTURE.md`, хотя через него идут и рендер на gamebox (M161), и весь `arl auto --on-remote` (M214c).
3. **Нет сводки этапа:** что сделано с 2026-11-02 по 11-10 и что из этого ждёт владельца, а не кода.

Настройки конфигов, не названные в документах, — служебные мелочи с комментариями прямо в `config/r0.yaml` и `config/render.yaml`; отдельного описания не требуют.

## Что вносит патч
- `PLAN.md`:
  - строка «Итог этапа M201–M219» — что закрыто по направлениям (видимость, работа без модели, отбор, сценарист, приём, рендер) и что решено **не делать** по замерам (стыки, крючки, плашки правилами, голос в оценке);
  - строка «Ждёт владельца (не код)» — гейт `m183`, два новых черновика, решения на листах ревью, рендер для проверки включённых флагов;
  - M216 и M217 добавлены в строку порядка механик.
- `PROJECT_STRUCTURE.md` — `local/remote.py`.

## Правила
1. Любая строка `FAIL: …` или упавшая команда → **СТОП**: команда и последние 40 строк. Ничего не чинить.
2. Ничего, кроме `PLAN.md` и `PROJECT_STRUCTURE.md`. Без рендера и без `arl auto`.
3. `data/token_scale.json` не коммитить и из подсчётов исключать; неотслеживаемые файлы (`??`) не трогать.
4. Итог — «DOCUMENTED».

## Часть 1. Патч и коммит
```bash
cd /Users/danny/Documents/autoreels
bash handoff/bin/take.sh m219
base=$(git log --format=%h -1); test "$base" = "4afeb08" && echo "OK база" || echo "FAIL: база $base, нужна 4afeb08 (M218)"
git apply --check handoff/m219/m219-docs-gaps.patch && git apply handoff/m219/m219-docs-gaps.patch && echo "OK патч" || echo "FAIL: патч не лёг"
n=$(git diff --name-only | grep -v "^data/token_scale.json$" | grep -cv "^$")
test "$n" = 2 && echo "OK два файла" || { echo "FAIL: изменено файлов $n:"; git diff --name-only | grep -v "^data/token_scale.json$"; }
grep -q "Итог этапа M201–M219" PLAN.md && echo "OK сводка" || echo "FAIL: сводки нет"
grep -q "M216" PLAN.md && echo "OK M216 в плане" || echo "FAIL: M216 нет"
grep -q "remote.py" PROJECT_STRUCTURE.md && echo "OK remote.py" || echo "FAIL: remote.py нет"
git add PLAN.md PROJECT_STRUCTURE.md
git commit -q -m "Docs (M219): the stage M201–M219 summed up in PLAN (what is closed by direction, what the measurements said not to do, what waits for the owner rather than for code), M216 added to the plan, local/remote.py to PROJECT_STRUCTURE"
git push -q && echo "OK запушено" || echo "FAIL: push"
git log --oneline -1
dirty=$(git status -s | grep -v "^??" | grep -v "data/token_scale.json" | wc -l | tr -d " ")
test "$dirty" = 0 && echo "OK отслеживаемое закоммичено" || { echo "FAIL: осталось $dirty"; git status -s | grep -v "^??" | grep -v "data/token_scale.json"; }
```
Ожидается: семь строк `OK`. Тесты не нужны — кода патч не меняет.

## Отчёт
`handoff/m219/REPORT.md`:
```
M219 — DOCUMENTED
Коммит: <хэш>
Проверки: <все OK / какие FAIL>
```
```bash
bash handoff/bin/report.sh m219
```
Владельцу в чат — 1 строка: «M219 — DOCUMENTED, коммит <хэш>: документация сведена с кодом, этап M201–M219 подытожен в плане».
