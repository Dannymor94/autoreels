# TASK M109 (окно MAIN, Mac; без модели и gamebox): задачи и отчёты — через ветку `handoff` на GitHub

Файлы — в ветке `origin/handoff`, папка `handoff/m109/`: `TASK-M109.md`, `m109-claude-handoff.patch`. Скрипты — `handoff/bin/take.sh`, `handoff/bin/report.sh`.

**Ставится поверх M108** (530dd08). Одна сессия, без фоновых задач.

## Зачем
Чтобы владелец больше не скачивал и не копировал файлы. Ассистент выкладывает задачи в ветку `handoff`, в `main` не пишет. Агент забирает задачу одной командой, а отчёт отправляет туда же — ассистент читает его сам. В `main`, как и раньше, коммитит только агент после тестов. Правило записывается в `CLAUDE.md`: дальше владелец пишет просто «Выполни mNN».

## Правила
1. Любой шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить.
2. В ветку `handoff` агент пишет только через `handoff/bin/report.sh`, и только папку `handoff/m109/`. Ветку `handoff` не переписывать (`--force` запрещён).
3. В `git status` допустимы три строки (` M data/blocks_dataset/IMG_6848.jsonl`, ` M data/token_scale.json`, `?? manifests/_archive/`), прежние `??` из `transcripts/` и `*.discarded.json`. `handoff/` в `main` не попадает.
4. Итог — «IMPLEMENTED».

## Шаг 1. Правило в CLAUDE.md: патч, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -1; git log --oneline -1; pgrep -fl "arl " || echo "arl не запущен"
ls handoff/bin/ handoff/m109/
git apply --check handoff/m109/m109-claude-handoff.patch && git apply handoff/m109/m109-claude-handoff.patch && echo applied
grep -n "Задачи от ассистента" CLAUDE.md
git add CLAUDE.md
git commit -m "Workflow (M109): the assistant's tasks come from the handoff branch (take.sh), reports go back there (report.sh); main is committed only by the agent after tests"
git push; git status --short
```
Ожидается:
- последний коммит — M108 (530dd08); `arl не запущен`;
- в `handoff/bin/` — `take.sh`, `report.sh`; в `handoff/m109/` — задача и патч;
- `applied`, строка `## Задачи от ассистента (ветка \`handoff\`)` в `CLAUDE.md`;
- `handoff/` нет в `git status`.

## Шаг 2. Отчёт через ветку handoff (проверка обратного пути)
Записать отчёт (раздел «Отчёт» ниже) в `handoff/m109/REPORT.md`, затем:
```bash
cd /Users/danny/Documents/autoreels
bash handoff/bin/report.sh m109
git fetch -q origin handoff && git show origin/handoff:handoff/m109/REPORT.md | head -5
git status --short; git log --oneline -1
```
Ожидается:
- `отчёт m109 отправлен в ветку handoff`;
- `git show` выводит начало отчёта;
- `main` не изменился (последний коммит — из шага 1), `handoff/` нет в `git status`.

## Отчёт (в REPORT.md и коротко владельцу в чат)
1. Шаг 1 — хэш коммита.
2. Шаг 2 — строка `report.sh` и начало отчёта из ветки.

Статус: IMPLEMENTED.
