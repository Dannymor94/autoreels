# TASK M216 (окно MAIN, Mac): правила написания задач — в `CLAUDE.md`

**Ложится на:** `main` после M215 (`03b81b3`). **Файлы:** `handoff/m216/` — `TASK-M216.md`, `m216-task-rules.patch`, `REVIEW-plan-rules.md` (записка для Codex, выполнять не нужно).
**Время:** ~3 минуты. Только документация: кода, конфигов и тестов не трогает. **Отчёт — только на русском.**

## Зачем
Владелец, 2026-11-04: задачи должны надёжно выполняться Sonnet 4.6 и Codex. В m214c ассистент ошибся в «Ожидается» (код `tee` вместо кода прогона; «1» вместо «≥ 1») — агент верно встал по правилу СТОП, но время потерялось. Правила формата переезжают в `CLAUDE.md`, чтобы их читал любой агент и чат, а не только этот разговор.

## Что вносит патч
`CLAUDE.md`, раздел «Задачи от ассистента» — подраздел «Как пишется задача»: проверка командой с `OK`/`FAIL`, код выхода отдельно от вывода (без `| tee`), пометка нестрогих ожиданий, самостоятельность каждой части, код приходит готовым патчем, одна задача — одна цель, Codex — разбор, Sonnet — исполнение.

## Правила
1. Любая строка `FAIL: …` или команда, которая упала → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить.
2. Ничего, кроме `CLAUDE.md`. Без рендера и без `arl auto`. `data/token_scale.json` не коммитить.
3. Итог — «DOCUMENTED».

## Часть 1. Патч и коммит
```bash
cd /Users/danny/Documents/autoreels
bash handoff/bin/take.sh m216
base=$(git log --format=%h -1); test "$base" = "03b81b3" && echo "OK база" || echo "FAIL: база $base, нужна 03b81b3 (M215)"
git apply --check handoff/m216/m216-task-rules.patch && git apply handoff/m216/m216-task-rules.patch && echo "OK патч" || echo "FAIL: патч не лёг"
n=$(git diff --name-only | grep -cv "^$"); test "$n" = 1 && echo "OK один файл" || { echo "FAIL: изменено файлов $n:"; git diff --name-only; }
grep -q "Как пишется задача" CLAUDE.md && echo "OK раздел" || echo "FAIL: раздела нет"
git add CLAUDE.md
git commit -q -m "CLAUDE.md (M216): how a handoff task is written — a check prints OK/FAIL instead of numbers to compare by eye, the exit code taken apart from the output (no | tee), loose expectations marked, each part self-contained, the code arrives as a patch already run by the assistant, one task one goal, Codex reviews and Sonnet executes"
git push -q && echo "OK запушено" || echo "FAIL: push"
git log --oneline -1
left=$(git status -s | grep -v "handoff/\|data/token_scale.json" | wc -l | tr -d " ")
test "$left" = 0 && echo "OK всё закоммичено" || { echo "FAIL: осталось $left"; git status -s | grep -v "handoff/\|data/token_scale.json"; }
```
Ожидается: пять строк `OK` и `OK запушено`. Тесты не нужны — кода патч не меняет.

## Часть 2. Записка для Codex (ничего не выполнять)
`handoff/m216/REVIEW-plan-rules.md` — задание на разбор `src/autoreels/cloud/plan.py`: найти пары правил резов, которые могут дать противоречивый план (как было в M136 и M79). Отдаёт её в Codex владелец; агенту выполнять не нужно, в `main` она не коммитится.
```bash
test -f handoff/m216/REVIEW-plan-rules.md && echo "OK записка на месте" || echo "FAIL: записки нет"
```

## Отчёт
`handoff/m216/REPORT.md`:
```
M216 — DOCUMENTED
Коммит: <хэш>
Проверки части 1: <все OK / какие FAIL>
```
```bash
bash handoff/bin/report.sh m216
```
Владельцу в чат — 1 строка: «M216 — DOCUMENTED, коммит <хэш>: правила написания задач в CLAUDE.md; записка для Codex — `handoff/m216/REVIEW-plan-rules.md`».
