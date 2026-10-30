# TASK M198 (окно MAIN, Mac): документация M188–M197; слияние ветки `ui` в `main`

Файлы — ветка `handoff`, папка `handoff/m198/`: `TASK-M198.md`, `m198-docs.patch`. Около 20 минут, без рендера, без LLM. Отчёт — только на русском.

## Зачем
Владелец 2026-10-30 решил: продакшн остаётся m183, работа над выбором клипов на этом останавливается, дальше — UI и crosspost.

1. **Документация.** Записать вехи M188–M197 в `PLAN.md`, `docs/REEL_SPEC.md`, `PROJECT_STRUCTURE.md`: эталон и слепые судьи, `answer_start`, исправления плана и выравнивания.
2. **Слияние `ui` → `main`.** Ветка `ui` отстала от `main` на 222 коммита, в ней 11 своих — этапы U1–U2d. Ассистент сделал пробное слияние на копии: **конфликтов нет**. Ветка добавляет только новые файлы: `ui/`, `src/autoreels/orchestr/`, `tests/ui/`, `demo/`, `docs/PLAN-UI.md`, `docs/UI-HANDOFF.md`. Существующие файлы не меняются.
   - Тесты на слитом дереве у ассистента: 2628 прошли.
   - Упали 10. Девять из них — тесты, которым нужны ffmpeg, praat или OpenCV (у ассистента их нет). Десятый — `tests/ui/test_openapi_snapshot.py`: у ассистента новее FastAPI, и схема ошибок отличается.
   - По `docs/PLAN-UI.md` после U3 UI живёт в `main`, задачи UI — короткими ветками от `main`. Сливаем сейчас, до U3: разрыв в 222 коммита дальше только растёт.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить.
2. Перед стартом не должно идти других `arl` и рендера: `pgrep -fl "autoreels|ffmpeg"`.
3. **НЕ МЕНЯТЬ:** `src/`, `config/`, `tests/` (кроме того, что приносит слияние), `reviews/`, гейты.
   - Конфликт при слиянии → **СТОП** (`git merge --abort`, список файлов в отчёт).
   - Пакеты не ставить. Если FastAPI нет, тесты `tests/ui/` пропускаются сами — это не СТОП, так и написать.
4. `tests/ui/test_openapi_snapshot.py` упал, а остальные тесты прошли → **не СТОП**. Снимок не перегенерировать, первые 15 строк вывода — в отчёт.
5. Итог — «MERGED, DOCS». Гейт не объявлять.

## Часть 0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m198
git fetch -q origin ui; git log --oneline -1 origin/ui
echo "main впереди: $(git rev-list --count origin/ui..HEAD), ui впереди: $(git rev-list --count HEAD..origin/ui)"
```
Ожидается:
- ветка `main`, чисто (кроме `handoff/`), последний коммит — M197 (`1aed744`) или новее;
- `origin/ui` — `52b8d31 ui(U2d): S/M/L thumbnail scale…`;
- ui впереди: 11.

## Часть 1. Документация
```bash
cd /Users/danny/Documents/autoreels
git apply --check handoff/m198/m198-docs.patch && git apply handoff/m198/m198-docs.patch && echo applied
git add PLAN.md docs/REEL_SPEC.md PROJECT_STRUCTURE.md
git commit -m "Docs (M198): M188–M197 — reference labelling and blind judges, answer_start (on), plan/alignment fixes"
git log --oneline -1
```
Ожидается: `applied`, коммит.

## Часть 2. Слияние `ui`
```bash
cd /Users/danny/Documents/autoreels
git merge --no-ff origin/ui -m "Merge ui (U1–U2d) into main (M198): FastAPI + React review UI lives in main; UI tasks go as short branches from main (PLAN-UI)" 2>&1 | tail -3
git status -sb | head -3
git diff --stat HEAD~1 HEAD | tail -1
git diff --name-only HEAD~1 HEAD | grep -vE '^(ui/|src/autoreels/orchestr/|tests/ui/|demo/|docs/PLAN-UI.md|docs/UI-HANDOFF.md)' || echo "только файлы UI"
.venv/bin/python -c "import fastapi; print('fastapi', fastapi.__version__)" 2>&1 | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -3
.venv/bin/python -m pytest tests/ui -q 2>&1 | tail -3
```
Ожидается:
- слияние без конфликтов;
- «только файлы UI»;
- весь набор: прежнее число прошедших плюс тесты UI (если FastAPI есть), упавших нет — кроме, возможно, снимка OpenAPI (правило 4);
- `tests/ui`: прошли или пропущены (нет FastAPI).

## Часть 3. Фронтенд (если есть Node)
```bash
cd /Users/danny/Documents/autoreels/ui
node -v && npm -v || echo "нет Node — часть пропущена"
[ -d node_modules ] || npm ci 2>&1 | tail -3
npm run build 2>&1 | tail -5
cd .. && git status -sb | head -5
```
Ожидается:
- `npm run build` без ошибок, или «нет Node» (не СТОП);
- `git status` чистый: `node_modules/` и `dist/` в `.gitignore` ветки `ui`. Если появились неотслеживаемые файлы — не коммитить, перечислить в отчёте.

## Часть 4. Push
```bash
cd /Users/danny/Documents/autoreels
git push origin main && git log --oneline -3
git push origin HEAD:ui && echo "ui = main"
git ls-remote origin main ui
```
Ожидается: `main` запушен; `ui` перемотан вперёд до `main`, без force — `ui` предок слияния. Отказ push в `ui` → не СТОП, написать.

## Отчёт
`handoff/m198/REPORT.md`:
```
M198 — MERGED, DOCS
Коммиты: <docs> <merge>; pytest: N passed (было M); tests/ui: <прошли K | пропущены — нет FastAPI>; снимок OpenAPI: <ок | упал (15 строк)>
Слияние: <файлов, строк>; только файлы UI — да/нет
Фронтенд: <npm run build ок | нет Node | ошибка>
ui = main — да/нет
Пропущено/не совпало: …
```
```bash
bash handoff/bin/report.sh m198
```
Владельцу в чат — 2 строки: статус и «UI в main; дальше — задачи UI короткими ветками от main».
