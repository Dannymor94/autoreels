# TASK M212C (окно MAIN, Mac + ssh gamebox): у ошибки клипа — причина рядом, прежние ошибки — в `_errors/`; найти сбойный h264 на gamebox

Файлы — ветка `handoff`, папка `handoff/m212c/`: `TASK-M212C.md`, `m212c-error-notes.patch` (ложится на `main` после M212b, `0d2c14a`).
Около 10 минут, без рендера. Отчёт — только на русском.

## Зачем
m212b по файлам:
- `prew_isaev_anna/_gate/ab192/r03.integrity.txt` записан в 11:22 рендером **h264 на gamebox**; `r03.mp4` рядом — **hevc с Mac**, 11:40, чистый. Успешный перерендер удалил старый `r03.ERROR.mp4`, но оставил его `.integrity.txt` — и сбойный файл снова потерян (цель M180 не достигнута).
- `prew_isaev_danny/_gate/ab192/r01.ERROR.mp4` — причина ошибки печаталась только в консоль, нигде не сохранилась.

Gamebox снова в сети (причина «No route to host» — VPN на Mac). Его собственная копия `ab192` могла сохранить исходный сбойный h264 — его и нужно разобрать.

## Что вносит патч
- `local/render.py`:
  - клип с ошибкой пишет `rNN.error.txt`: время, машина, кодек, все причины;
  - чистый перерендер переносит прежние `rNN.ERROR.mp4`, `rNN.error.txt`, `rNN.integrity.txt` в `_errors/rNN.<время>.*` (а не удаляет `.ERROR.mp4` и не оставляет лог рядом с новым клипом).
- `tests/test_render.py` — тест M212c (без правки падает).
- `docs/GAMEBOX.md` — абзац M212c; раздел «SSH до gamebox: No route to host» (VPN, «Локальная сеть» macOS, IP, сеть); убран повтор абзаца M180.
- `PLAN.md` — строка порядка механик.

Ассистент прогнал весь набор: 2691 прошли, упали прежние 7 и флейк menu.

## Правила
1. Команда упала → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить.
2. **Без рендера.** На gamebox и в `reels-out/` — только чтение: ничего не переименовывать и не удалять (перенос в `_errors/` делает только рендер). `data/token_scale.json` не коммитить.
3. Итог — «IMPLEMENTED, MEASURED».

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1
bash handoff/bin/take.sh m212c
git apply --check handoff/m212c/m212c-error-notes.patch && git apply handoff/m212c/m212c-error-notes.patch && echo applied
.venv/bin/python -m pytest tests/test_render.py -q 2>&1 | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add PLAN.md docs/GAMEBOX.md src/autoreels/local/render.py tests/test_render.py
git commit -m "Render (M212c): a failed clip writes <rid>.error.txt (when, where, codec, reasons); a clean re-render moves the previous ERROR.mp4 / error.txt / integrity.txt to _errors/<rid>.<time>.* instead of deleting the clip and leaving its log (m212: an h264 gamebox log lay beside a clean hevc Mac clip, the failing file lost); GAMEBOX.md: No route to host — the VPN"
git push; git log --oneline -1
git status -s | grep -v "handoff/\|data/token_scale.json" || echo "всё закоммичено"
```
Ожидается:
- последний коммит до — M212b (`0d2c14a`); `applied`;
- `test_render.py` — все прошли;
- весь набор — прежнее число плюс 1 (флейк `test_menu_bash::…profile_picker…` — перезапустить отдельно);
- коммит запушен; «всё закоммичено».

## Часть 2. Gamebox: файлы ошибок и разбор сбойного h264
```bash
cd /Users/danny/Documents/autoreels
ssh gamebox 'cd /mnt/data/autoreels && ffmpeg -version | head -1; find reels-out \( -name "*.integrity.txt" -o -name "*.ERROR.mp4" \) -printf "%TY-%Tm-%Td %TH:%TM  %s  %p\n" 2>/dev/null | sort' 2>&1 | tee handoff/m212c/gamebox_found.txt
ssh gamebox 'cd /mnt/data/autoreels && for f in $(find reels-out -name "*.integrity.txt"); do echo "== $f"; cat "$f"; done' 2>&1 | tee handoff/m212c/gamebox_integrity.txt
for f in $(grep -o "reels-out/[^ ]*\.ERROR\.mp4" handoff/m212c/gamebox_found.txt | head -6); do
  ssh gamebox "sh -s -- /mnt/data/autoreels/$f" < handoff/m179/probe_au.sh
done 2>&1 | tee handoff/m212c/gamebox_probe.txt
```
Ожидается:
- `ssh` отвечает; список файлов ошибок с датами и размерами (пусто — тоже ответ);
- для каждого `.ERROR.mp4` на gamebox (до 6) — разбор: проверка (copy), полное декодирование, пакеты < 64 байт, NAL-единицы маленького пакета.

## Отчёт
`handoff/m212c/REPORT.md`:
```
M212C — IMPLEMENTED, MEASURED
Коммит: <хэш>; pytest: N passed (было M)
Gamebox: integrity.txt <n>, ERROR.mp4 <n> (ffmpeg <версия>)
Сбойный h264 (если найден): <файл>; маленький пакет <размер, время, последний ли>; NAL <типы>; полное декодирование <чисто/ошибки>
```
```bash
bash handoff/bin/report.sh m212c gamebox_found.txt gamebox_integrity.txt gamebox_probe.txt
```
Владельцу в чат — 2 строки:
1. статус и коммит;
2. «gamebox: сбойный h264 <найден: что в маленьком пакете / не найден>».
