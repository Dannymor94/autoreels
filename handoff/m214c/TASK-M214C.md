# TASK M214C (окно MAIN, Mac + ssh gamebox): `arl auto … --on-remote` — весь прогон на gamebox, на Mac — тексты

Файлы — ветка `handoff`, папка `handoff/m214c/`: `TASK-M214C.md`, `m214c-auto-remote.patch` (ложится на `main` после M214b, `90463fa`).
Около 10 минут, без рендера и без скачивания видео. Отчёт — только на русском.

## Зачем
Владелец, 2026-11-02: gamebox — дом видео, видео не идёт через Mac. M214b подготовила gamebox: VPN для моделей, `torch`, модель выравнивания, ключи.

## Что вносит патч
- `local/remote.py` — `auto_remote`:
  1. проверка gamebox;
  2. код туда (`git ls-files`, как M161);
  3. метка `.arl/auto-mark`;
  4. **та же команда** там через `ssh -t` — вопросы об удалении придут в терминал Mac;
  5. назад на Mac — файлы `manifests/`, `transcripts/`, `reviews/`, `exchange/`, изменённые после метки (tar по ssh).

  Пути Mac (`--root`, `--cache-dir`, `--inputs-dir`) туда не передаются.
- `arl auto … --on-remote` (`cmd_auto_remote`); машина — `config/render.yaml remote:` (host, root).
- Документация: `docs/GAMEBOX.md` (раздел «Весь прогон на gamebox»), `README.md`, `PLAN.md`.
- `tests/test_m214c_auto_remote.py` — 6 тестов.

Ассистент прогнал весь набор: 2713 прошли, упали прежние 7 и флейк menu.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить.
2. **Без рендера и без скачивания:** папку владельца не запускать — это делает владелец (ниже). `data/token_scale.json` не коммитить.
3. Итог — «IMPLEMENTED, VERIFIED».

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1
bash handoff/bin/take.sh m214c
git apply --check handoff/m214c/m214c-auto-remote.patch && git apply handoff/m214c/m214c-auto-remote.patch && echo applied
.venv/bin/python -m pytest tests/test_m214c_auto_remote.py tests/test_auto.py -q 2>&1 | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add PLAN.md README.md docs/GAMEBOX.md src/autoreels/__main__.py src/autoreels/local/remote.py tests/test_m214c_auto_remote.py
git commit -m "Remote auto (M214c): arl auto … --on-remote — the code to gamebox, the same command there through ssh -t (the delete questions in this terminal), the texts changed by the run back (manifests, transcripts, reviews, exchange); the video stays on gamebox"
git push; git log --oneline -1
git status -s | grep -v "handoff/\|data/token_scale.json" || echo "всё закоммичено"
```
Ожидается: последний коммит до — M214b (`90463fa`); `applied`; первая строка pytest — все прошли; весь набор — прежнее число плюс 6 (флейк `test_menu_bash::…profile_picker…` — перезапустить отдельно); коммит запушен; «всё закоммичено».

## Часть 2. Сквозная проверка без видео
Цель, которой на gamebox нет: прогон там завершится быстро («манифест не найден», код 1), но пройдут все шаги — ssh, код, метка, команда там, сбор текстов.
```bash
cd /Users/danny/Documents/autoreels
.venv/bin/python -m autoreels auto __m214c_check__ --no-render --on-remote 2>&1 | tee handoff/m214c/check.txt; echo "код $?"
ssh gamebox 'cd /mnt/data/autoreels && ls -la .arl/auto-mark && .venv/bin/python -m autoreels auto --help | grep -c -- "--on-remote"'
```
Ожидается:
- первая строка «=== auto на gamebox:/mnt/data/autoreels — видео остаётся там …»;
- вывод прогона с gamebox («манифест не найден» для `__m214c_check__`);
- «назад на Mac: изменённых текстов нет»; код 1 (цели нет — это и ожидается);
- на gamebox есть метка и новый код (`--on-remote` в справке — `1`).

## Отчёт
`handoff/m214c/REPORT.md`:
```
M214C — IMPLEMENTED, VERIFIED
Коммит: <хэш>; pytest: N passed (было M)
Сквозная проверка: шаги ssh/код/метка/команда/сбор — <прошли>; код <1>
```
```bash
bash handoff/bin/report.sh m214c check.txt
```
Владельцу в чат — 2 строки:
1. статус и коммит;
2. «папка на gamebox: `.venv/bin/python -m autoreels auto "https://disk.yandex.ru/d/CFGY7HK8UrWECQ" --mode autocut --llm cloud --no-render --on-remote`».
