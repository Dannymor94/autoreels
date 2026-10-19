# Ветка handoff — задачи ассистента и отчёты агента

Здесь только папка `handoff/`. Код проекта — в `main`, и в `main` коммитит только агент, после тестов.

- `handoff/mNN/` — задача: `TASK-MNN.md`, патчи, скрипты. Выкладывает ассистент.
- `handoff/mNN/REPORT.md` (+ файлы отчёта) — отчёт агента о выполнении. Выкладывает агент.
- `handoff/bin/take.sh mNN` — забрать задачу в рабочую копию на Mac.
- `handoff/bin/report.sh mNN [файлы]` — отдать отчёт.

Окну MAIN: «Выполни mNN». Правило записано в `CLAUDE.md` проекта.
Первый раз, пока скриптов нет:
`git fetch -q origin handoff && git restore --source=origin/handoff --worktree -- handoff/bin && bash handoff/bin/take.sh mNN`.
