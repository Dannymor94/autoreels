# REPORT M170

## Шаг 1: патч, тесты, коммиты

Коммит `9ec85b8`: `Auto (M170): arl auto builds the speaker map when missing (autocut.speakers_auto, speakers_python), non-fatal; docs M153–M170`

Изменено: `src/autoreels/__main__.py` (speakers_auto в cmd_auto, expanduser в cmd_speakers), `src/autoreels/core/config.py` (поля speakers_auto/speakers_python), `config/r0.yaml` (`speakers_auto: true`, `speakers_python: ~/.venvs/m141/bin/python`), `tests/test_m170_speakers_auto.py` (3 теста), `tests/test_auto.py` (_stub выключает этап), `PLAN.md`, `README.md`, `docs/GAMEBOX.md`.

Исправлен баг патча — `import subprocess` отсутствовал в `cmd_speakers` (коммит `aabb667`).

pytest: **2548 passed, 9 deselected**.

## Шаг 2: проверка pyannote (speakers.txt)

```
реплик 151, говорящих 2, 105 с на mps
✓ Pxl 20260621 122006193.speakers.json: реплик 151, говорящих 2 — SPEAKER_00 100%, SPEAKER_01 0%; главный SPEAKER_00
117 с
```

Связка `arl speakers` → `tools/diarize.py` → окружение m141 работает. Источник «Pxl 20260621 122006193» — карта построена за 117 с.

## Статус: IMPLEMENTED
