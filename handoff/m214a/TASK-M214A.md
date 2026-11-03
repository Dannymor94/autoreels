# TASK M214A (окно MAIN, Mac + ssh gamebox): папка Я.Диска — видео по одному; проверка gamebox для полного прогона там

Файлы — ветка `handoff`, папка `handoff/m214a/`: `TASK-M214A.md`, `m214a-yandex-folder.patch` (ложится на `main` **после M213**).
Около 10 минут, без рендера и без скачивания. Отчёт — только на русском.

## Зачем
Владелец, 2026-11-03: «https://disk.yandex.ru/d/CFGY7HK8UrWECQ — тут много видео, все надо обработать», видео должны жить на gamebox.
1. **Папка (`/d/…`)** — загрузчик брал только файлы. Патч: видео папки обрабатываются по одному.
2. **Полный прогон на gamebox (M214c)** — сначала узнать, чего там не хватает: выравниванию нужны `torch` + `torchaudio` + `parselmouth` (extra `align`, сейчас «только Mac»), проверкам начала — `pymorphy3`, моделям — ключи в `.env` gamebox.

## Что вносит патч
- `_yandex_folder_videos` — видео публичной папки (этот уровень, по имени, постранично); `_download_yandex_disk(…, path=…)` — файл внутри папки.
- `arl auto <ссылка /d/…>`:
  - папка → видео по одному: скачать → весь путь → следующее;
  - вопрос об удалении — **один раз в начале**: «В папке N видео (M ГБ). Удалять каждый исходник сразу после удачной обработки? [y/N]»;
  - при «да» каждый файл удаляется до скачивания следующего — на диске одно видео; при «нет», без терминала или при сбое прогона — файлы остаются;
  - `/d/…` на один файл — как одиночная ссылка (вопрос в конце, M213); `/i/…` — файл без лишнего запроса к API.
- `PLAN.md`, `README.md`.
- `tests/test_m214a_yandex_folder.py` — 5 тестов.

Ассистент прогнал весь набор поверх M213: 2704 прошли, упали прежние 7 и флейк menu.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить.
2. **Без рендера, без скачивания, на gamebox ничего не ставить** (только чтение). `.env` не печатать — только «есть / нет» ключа. `data/token_scale.json` не коммитить.
3. Итог — «IMPLEMENTED, MEASURED».

## Часть 0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -2
bash handoff/bin/take.sh m214a
```
Ожидается: последний коммит — **M213** (`Ingest (M213): …`). Если M213 не выполнена — **СТОП**: «сначала m213».

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git apply --check handoff/m214a/m214a-yandex-folder.patch && git apply handoff/m214a/m214a-yandex-folder.patch && echo applied
.venv/bin/python -m pytest tests/test_m214a_yandex_folder.py tests/test_m213_yandex_link.py tests/test_auto.py -q 2>&1 | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add PLAN.md README.md src/autoreels/__main__.py tests/test_m214a_yandex_folder.py
git commit -m "Ingest (M214a): arl auto <public Yandex Disk folder link> — the folder's videos by name, one by one (download → the whole run → the next); whether each source goes right after a good run is asked once at the start (no terminal — kept), so with «yes» one video is on disk at a time; a /d/ link to one file is a single file"
git push; git log --oneline -1
git status -s | grep -v "handoff/\|data/token_scale.json" || echo "всё закоммичено"
```
Ожидается: `applied`; первая строка pytest — все прошли; весь набор — прежнее число плюс 5 (флейк `test_menu_bash::…profile_picker…` — перезапустить отдельно); коммит запушен; «всё закоммичено».

## Часть 2. Gamebox: хватит ли его для полного прогона (только чтение)
```bash
cd /Users/danny/Documents/autoreels
ssh gamebox 'cd /mnt/data/autoreels && echo "== python"; .venv/bin/python -V;
  echo "== пакеты"; .venv/bin/python -m pip list 2>/dev/null | grep -iE "^(torch|torchaudio|praat-parselmouth|pymorphy3|opencv-python-headless|httpx|numpy|pyannote.audio) ";
  echo "== ключи (.env: есть=1, нет=0)"; for k in GROQ_API_KEY OPENROUTER_API_KEY ANTHROPIC_API_KEY HF_TOKEN YANDEX_DISK_TOKEN; do printf "%s: %s\n" "$k" "$(grep -c "^$k=." .env 2>/dev/null || echo 0)"; done;
  echo "== модель выравнивания"; ls ~/.cache/torch/hub/checkpoints 2>/dev/null | head -5;
  echo "== ресурсы"; nproc; free -g | head -2; df -h /mnt/data | tail -1; ffmpeg -version | head -1;
  echo "== код"; git -C /mnt/data/autoreels log --oneline -1 2>/dev/null || echo "не git (код приходит с Mac, M161)"' 2>&1 | tee handoff/m214a/gamebox.txt
```
Ожидается: всё выводится, ошибок ssh нет. Отсутствующие пакеты или ключи — не СТОП, это и есть замер.

## Отчёт
`handoff/m214a/REPORT.md`:
```
M214A — IMPLEMENTED, MEASURED
Коммит: <хэш>; pytest: N passed (было M)
gamebox: python <…>; torch <есть/нет>, torchaudio <…>, parselmouth <…>, pymorphy3 <…>, opencv <…>; ключи: GROQ <0/1>, OPENROUTER <0/1>, HF <0/1>
модель выравнивания: <есть/нет>; ресурсы: ядер <n>, память <n> ГБ, /mnt/data свободно <…>
```
```bash
bash handoff/bin/report.sh m214a gamebox.txt
```
Владельцу в чат — 2 строки:
1. статус и коммит;
2. «gamebox для полного прогона: не хватает — <список пакетов и ключей / ничего>».
