# TASK M210 (окно MAIN, Mac): уборка плана, выбор хранения, порядок механик

Файлы — ветка `handoff`, папка `handoff/m210/`: `TASK-M210.md`, `m210-plan.patch` (только `PLAN.md`, ложится на `main` после M209, `dcabfc4`).
Около 3 минут. Только документация. Отчёт — только на русском.

## Что вносит патч (`PLAN.md`)
- Техдолг: строка «повторные номера `M` в общем черновике» — исправлено в M175; ложная тревога целостности на gamebox → M212.
- M2: хранение — выбор владельца 2026-11-02 «gamebox — дом видео» (на Mac только звук и тексты); позже по необходимости Tailscale / rclone / Syncthing; план M213 — `arl auto <ссылка Я.Диска>` с вопросом об удалении исходника.
- Строка «Порядок механик»: M210 → M211 → M212 → M213.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: команда и последние 40 строк. Ничего не чинить.
2. Ничего, кроме `PLAN.md`. `data/token_scale.json` не коммитить.
3. Итог — «DOCUMENTED».

## Часть 1
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1
bash handoff/bin/take.sh m210
git apply --check handoff/m210/m210-plan.patch && git apply handoff/m210/m210-plan.patch && echo applied
git add PLAN.md
git commit -m "Plan (M210): storage — gamebox is the home of the video (owner 2026-11-02), the planned arl auto <Yandex Disk link> with a delete question (M213), the order of the mechanics M210–M213; stale tech debt removed"
git push; git log --oneline -1
git status -s | grep -v "handoff/\|data/token_scale.json" || echo "всё закоммичено"
```
Ожидается: последний коммит до — M209 (`dcabfc4`); `applied`; коммит запушен; «всё закоммичено».

## Отчёт
`handoff/m210/REPORT.md`: `M210 — DOCUMENTED. Коммит <хэш>.`
```bash
bash handoff/bin/report.sh m210
```
Владельцу в чат — 1 строка: «M210 — DOCUMENTED, коммит <хэш>».
