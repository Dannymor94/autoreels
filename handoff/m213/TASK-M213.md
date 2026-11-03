# TASK M213 (окно MAIN, Mac): `arl auto <ссылка Я.Диска>` — скачать, весь конвейер, спросить перед удалением исходника

Файлы — ветка `handoff`, папка `handoff/m213/`: `TASK-M213.md`, `m213-yandex-link.patch` (ложится на `main` после M212d, `3056588`).
Около 5 минут, без рендера. Отчёт — только на русском.

## Зачем
Владелец, 2026-11-02: по ссылке Я.Диска скрипт сам скачивает, проходит расшифровку и весь путь, а после окончания удаляет исходник — но сначала спрашивает.

## Что вносит патч
- `arl auto` принимает публичную ссылку Я.Диска (`disk.yandex.ru` / `.com` / `yadi.sk`): файл скачивается в `inputs/` готовым загрузчиком (докачка с обрывов, свежая ссылка на каждой попытке) и дальше идёт как видеофайл (`arl run` → подготовка → карта → сборка …). Битая ссылка — строка в итоге, следующие цели идут дальше.
- После итога — `_offer_source_delete`:
  - для каждого **скачанного этим прогоном** источника с удачным прогоном: «Удалить исходник <имя> (N ГБ)? Повторный рендер его не найдёт. [y/N]»;
  - без терминала, без ответа или при сбое прогона — **не удаляется** (путь печатается);
  - `--delete-source ask | keep | yes` (по умолчанию `ask`);
  - локальный файл, указанный путём, удалить не предлагается никогда.
- `PLAN.md` (M2: M213 сделано, дальше M214 — видео на gamebox), `README.md` (строка команды).
- `tests/test_m213_yandex_link.py` — 7 тестов (без правки падают все).

Ассистент прогнал весь набор: 2700 прошли, упали прежние 7.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: команда и последние 40 строк. Ничего не чинить.
2. **Без рендера и без скачивания**: живую проверку со ссылкой делает владелец (см. ниже). `data/token_scale.json` не коммитить.
3. Итог — «IMPLEMENTED».

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1
bash handoff/bin/take.sh m213
git apply --check handoff/m213/m213-yandex-link.patch && git apply handoff/m213/m213-yandex-link.patch && echo applied
.venv/bin/python -m pytest tests/test_m213_yandex_link.py tests/test_auto.py -q 2>&1 | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -3
.venv/bin/python -m autoreels auto --help | grep -A2 "delete-source"
git add PLAN.md README.md src/autoreels/__main__.py tests/test_m213_yandex_link.py
git commit -m "Ingest (M213): arl auto <public Yandex Disk link> — downloaded into inputs/, then the whole run as a video file; after the summary each downloaded source of a good run is offered for deletion (y/N; no terminal, no answer or a failed run keeps it; --delete-source ask|keep|yes); a local file is never offered"
git push; git log --oneline -1
git status -s | grep -v "handoff/\|data/token_scale.json" || echo "всё закоммичено"
```
Ожидается:
- последний коммит до — M212d (`3056588`); `applied`;
- первая строка pytest — все прошли; весь набор — прежнее число плюс 7 (флейк `test_menu_bash::…profile_picker…` — перезапустить отдельно);
- в справке есть `--delete-source {ask,keep,yes}`;
- коммит запушен; «всё закоммичено».

## Живая проверка (владелец, по желанию)
```bash
.venv/bin/python -m autoreels auto "<публичная ссылка Я.Диска на короткое видео>" --no-render --tag y213
```
В конце — вопрос об удалении; `n` — файл остаётся в `inputs/`.

## Отчёт
`handoff/m213/REPORT.md`: `M213 — IMPLEMENTED. Коммит <хэш>; pytest N passed (было M).`
```bash
bash handoff/bin/report.sh m213
```
Владельцу в чат — 2 строки:
1. статус и коммит;
2. «`arl auto <ссылка Я.Диска>` — скачивает, проходит весь путь, в конце спрашивает об удалении; проверить — короткой ссылкой с `--no-render`».
