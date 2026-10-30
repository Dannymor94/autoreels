# TASK M192B (окно MAIN, Mac): выгрузить тексты 20 клипов ab192 для слепых судей

Файлы — ветка `handoff`: `handoff/m192b/TASK-M192B.md`, скрипт `handoff/m192/export_texts.py`. Около 3 минут, без рендера, без LLM. Отчёт — только на русском.

## Зачем
Владелец, 2026-10-30, попросил провести оценку m192 вместо него. Судьи — две модели с чистым контекстом, которые не знают, чей клип. Им нужен только текст клипов: что слышит зритель, холодный старт, плашка, подпись, длительность. Строки разметки, метки и источник в выгрузку не идут.

Часть B задачи m192 (оценки владельца) остаётся на случай, если он всё же посмотрит листы. Ничего из неё сейчас не делать.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: команда, последние 40 строк.
2. **НЕ МЕНЯТЬ** ничего, кроме новых файлов `handoff/m192/blind_texts.json` и `handoff/m192/blind_map.csv`. Коммитов в `main` нет.
3. Не показывать владельцу `key.csv` и не писать, какой клип чей.

## Шаги
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -2; bash handoff/bin/take.sh m192 >/dev/null; bash handoff/bin/take.sh m192b
ls -1 reviews/*_ab192.review.json | wc -l
.venv/bin/python handoff/m192/export_texts.py
.venv/bin/python -c "import json;d=json.load(open('handoff/m192/blind_texts.json'));print(len(d), sum(1 for x in d if x['text']))"
```
Ожидается:
- 6 файлов `_ab192.review.json`;
- `клипов: 20 (с видео 19)`;
- `20 20` (у каждого клипа есть текст).

## Отчёт
`handoff/m192b/REPORT.md`: `M192B — EXPORTED` и вывод трёх последних команд.
```bash
mkdir -p handoff/m192b && cp handoff/m192/blind_texts.json handoff/m192/blind_map.csv handoff/m192b/
bash handoff/bin/report.sh m192b blind_texts.json blind_map.csv
```
Владельцу — одна строка: «m192b: тексты 20 клипов выгружены, ассистент запускает слепых судей».
