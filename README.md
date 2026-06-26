# Авто-Рилс

CLI: длинное горизонтальное видео (talking-head, статичная камера) → набор вертикальных
рилсов 9:16 с выжженными субтитрами и кликбейт-заголовками. **Полностью автоматически.**

Несущая граница — **ОБЛАКО / ЛОКАЛЬ**. Облако работает только с текстом
(аудио → транскрипт → манифест), исходник живёт на локали, где и рендерится.
Видео между тирами не передаётся.

- Инварианты — [CLAUDE.md](CLAUDE.md)
- Архитектура — [PROJECT_GUIDE.md](PROJECT_GUIDE.md)
- Ядро (выбор моментов) — [R0_SPEC.md](R0_SPEC.md)
- План реализации — [PLAN.md](PLAN.md)
- Раскладка — [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)

## Требования

- **Python 3.11+** (закреплено в `.python-version` = 3.13; системный macOS Python 3.9 не подойдёт).
- **ffmpeg** в `PATH` — извлечение аудио и весь локальный рендер. macOS: `brew install ffmpeg`.

```
python3.13 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

## Статус

M0 — вертикальный слайс «один клип end-to-end». Каркас собран; модули реализуются
пошагово по TDD (см. `PLAN.md`, M0 шаги 1→8).

## Запуск (цель M0)

```
python -m autoreels run video.mp4 --setup tearoom_main
```

→ папка с mp4-рилсами + `manifest.json`.
