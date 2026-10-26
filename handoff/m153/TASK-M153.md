# TASK M153 (окно MAIN, Mac): `arl auto` пишет ролики сценаристом по умолчанию + переключатели

Файлы — ветка `handoff`, папка `handoff/m153/`: `TASK-M153.md`, `m153-auto-mode.patch`. Около 10 минут, без рендера и без платных вызовов. Можно до или после m150: файлы не пересекаются.

## Зачем
Владелец 2026-10-26: «сейчас нужно будет прогнать все видео сценаристом — сценарист по умолчанию для текущей работы; переключатели должны быть описаны». Раньше `arl auto` всегда звал автомонтаж, сценарист был только в `arl autocut --scenario`. Патч:
- `config/r0.yaml autocut.auto_mode: scenario` и `autocut.scenario_llm: sonnet`. В коде по умолчанию `autocut`, то есть выключенный флаг даёт прежнюю последовательность M63.
- `arl auto … --mode autocut|scenario`, `--scenario-llm haiku|sonnet` — переключение на один прогон.
- Если сценарист не ответил (нет ключа, ошибка API), источник идёт бесплатным автомонтажом, итог это называет.
- Карта и посты остаются на бесплатных моделях (`--llm`). В начале прогона печатается, кто пишет ролики.
- Тесты `tests/test_m153_auto_mode.py` (6).
- Документация: таблица «Переключатели `arl auto`» в README, PLAN, PROJECT_GUIDE, REEL_SPEC. В CLAUDE.md записано, что `auto_mode: scenario` считается явно названным платным режимом.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. `arl auto` в этой задаче не запускать (платно, по всем видео — отдельная команда владельца).

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m153
git apply --check handoff/m153/m153-auto-mode.patch && git apply handoff/m153/m153-auto-mode.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests config docs PLAN.md PROJECT_GUIDE.md README.md CLAUDE.md
git commit -m "Auto (M153): arl auto writes reels with the scenarist by default (owner 2026-10-26; autocut.auto_mode, scenario_llm sonnet), --mode/--scenario-llm per run, falls back to the free autocut; switches documented" && git push && git log --oneline -1
```
Ожидается: `applied`; pytest — все прошли; коммит запушен.

## Шаг 2. Проверка без вызовов модели
```bash
.venv/bin/python -m autoreels auto --help | grep -A2 -E "\-\-mode|\-\-scenario-llm"
grep -n "ANTHROPIC_API_KEY" .env >/dev/null && echo "ключ Claude в .env есть" || echo "КЛЮЧА Claude В .env НЕТ — сценарист будет падать на автомонтаж"
```
Ожидается: оба флага в справке; строка о ключе (сам ключ не печатать).

## Шаг 3. Отчёт
`handoff/m153/REPORT.md`: коммит, pytest, вывод шага 2.
`bash handoff/bin/report.sh m153`
Владельцу — одна строка: «`arl auto` теперь пишет ролики сценаристом (sonnet); бесплатно — `--mode autocut`; переключатели — таблица в README».
