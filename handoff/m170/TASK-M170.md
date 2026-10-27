# TASK M170 (окно MAIN, Mac; ПОСЛЕ m169): карта говорящих внутри `arl auto` + документация M153–M170

Владелец 2026-10-27: «карта говорящих для новых видео — не отдельной командой; обновить документацию».

Патч:
- `arl auto` после карты мыслей строит карту говорящих сам (`arl speakers`), если у источника её нет. Окружение с pyannote — `autocut.speakers_python` (на Mac `~/.venvs/m141/bin/python`), токен — `HF_TOKEN` из `.env`. Не вышло — предупреждение, прогон идёт дальше. В коде по умолчанию выключено, в репо `speakers_auto: true`;
- тесты `tests/test_m170_speakers_auto.py` (3); `_stub` в `tests/test_auto.py` выключает этап в старых тестах;
- документация: PLAN (таблица автомонтажа M153–M170, «Ждут владельца», техдолг), README, `docs/GAMEBOX.md`.

## Правила
1. Шаг упал → **СТОП**.
2. pytest — без рендера на Mac.

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -3; pgrep -fl "autoreels (auto|render)" || echo "свободно"
grep -n '^  interviewer:' config/r0.yaml     # должно быть "off" (m169)
bash handoff/bin/take.sh m170
git apply --check handoff/m170/m170-speakers-auto-docs.patch && git apply handoff/m170/m170-speakers-auto-docs.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests config PLAN.md README.md docs && git commit -m "Auto (M170): arl auto builds the speaker map when missing (autocut.speakers_auto, speakers_python), non-fatal; docs M153–M170" && git push && git log --oneline -1
```
Ожидается: `interviewer: "off"`, `applied`, pytest — все прошли, коммит запушен.

## Шаг 2. Проверка, что pyannote реально запускается из проекта
На самом коротком источнике карта строится заново, не импортом: так проверяется связка `arl speakers` → `tools/diarize.py` → окружение m141.
```bash
s=$(date +%s); .venv/bin/python -m autoreels speakers "Pxl 20260621 122006193" --python ~/.venvs/m141/bin/python --force 2>&1 | tail -2 | tee handoff/m170/speakers.txt; echo "$(( $(date +%s) - s )) с" | tee -a handoff/m170/speakers.txt
```
Ожидается строка «✓ … говорящих N … главный …» и время. Ошибка — СТОП с выводом.

## Шаг 3. Отчёт
`handoff/m170/REPORT.md`: коммит, pytest, `speakers.txt`.
`bash handoff/bin/report.sh m170 speakers.txt`
Владельцу — одна строка: «карта говорящих теперь строится в arl auto сама (N с на источник), документация обновлена».
