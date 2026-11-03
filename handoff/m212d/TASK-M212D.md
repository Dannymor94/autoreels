# TASK M212D (окно MAIN, Mac + ssh gamebox): кадр, потерянный `h264_vaapi`, — повторный рендер программным кодеком

Файлы — ветка `handoff`, папка `handoff/m212d/`: `TASK-M212D.md`, `m212d-vaapi-retry.patch` (ложится на `main` после M212c, `5695ccd`).
Около 10 минут, **без рендера**. Отчёт — только на русском.

## Зачем
m212c разобрала сохранённый на gamebox `prew_isaev_anna/_gate/ab192/r03.ERROR.mp4`:
- на месте одного кадра `h264_vaapi` поставил пакет в 12 байт только со служебным SEI (NAL 6) — на 54,9 с из ~68,7 (в середине, не в конце);
- 4120 пакетов, 4119 кадров; полное декодирование — «missing picture», «no frame!».

Тревога не ложная: кадр потерян. Сбой плавающий (m165: 16 из 26, m179: 0 из 41, ab192: 1). Владелец, 2026-11-03: лечить детерминированно.

## Что вносит патч
- `local/render.py`: после основного прохода `render_crop` клип, который упал ровно так (`rNN.ERROR.mp4` + «missing picture in access unit» в `rNN.integrity.txt` + `*_vaapi` в `rNN.error.txt`), рендерится ещё раз программным кодеком (`h264_vaapi` → `libx264`, `hevc_vaapi` → `libx265`):
  - чистый результат сдаётся, сбойный файл уходит в `_errors/` (M212c);
  - в `rNN.render.json` — `encoder_retry: {encoder, why}`;
  - в консоли — «↻ rNN: аппаратный кодек потерял кадр — заново libx264»;
  - другие ошибки и другие кодеки — как раньше.
- `core/config.py`: `vaapi_soft_retry` (в коде по умолчанию выключено); `config/render.yaml`: `vaapi_soft_retry: true` (решение владельца).
- `tests/test_render.py` — тест M212d (без правки падает; включает проверку «выключено — как раньше»).
- `docs/GAMEBOX.md` — причина и лечение; `PLAN.md` — техдолг закрыт, строка порядка.

Ассистент прогнал весь набор: 2692 прошли, упали прежние 7 и флейк menu.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить.
2. **Без рендера.** `reels-out/` и `_errors/` не трогать. `data/token_scale.json` не коммитить.
3. Итог — «IMPLEMENTED, VERIFIED».

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1
bash handoff/bin/take.sh m212d
git apply --check handoff/m212d/m212d-vaapi-retry.patch && git apply handoff/m212d/m212d-vaapi-retry.patch && echo applied
grep -n "^vaapi_soft_retry:" config/render.yaml
.venv/bin/python -m pytest tests/test_render.py -q 2>&1 | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add PLAN.md config/render.yaml docs/GAMEBOX.md src/autoreels/core/config.py src/autoreels/local/render.py tests/test_render.py
git commit -m "Render (M212d): a clip whose h264_vaapi/hevc_vaapi encode lost a frame (integrity: missing picture in access unit — m212c: a 12-byte SEI-only access unit in ab192/r03) is rendered once more by libx264/libx265; the failed file goes to _errors/, <rid>.render.json says why (render.yaml vaapi_soft_retry: true); tech debt closed"
git push; git log --oneline -1
git status -s | grep -v "handoff/\|data/token_scale.json" || echo "всё закоммичено"
```
Ожидается:
- последний коммит до — M212c (`5695ccd`); `applied`; `vaapi_soft_retry: true`;
- `test_render.py` — все прошли; весь набор — прежнее число плюс 1 (флейк `test_menu_bash::…profile_picker…` — перезапустить отдельно);
- коммит запушен; «всё закоммичено».

## Часть 2. На gamebox есть чем перекодировать
```bash
cd /Users/danny/Documents/autoreels
ssh gamebox 'ffmpeg -hide_banner -encoders 2>/dev/null | grep -E " (libx264|libx265|h264_vaapi|hevc_vaapi) "' 2>&1 | tee handoff/m212d/encoders.txt
grep -c "libx264\|libx265" handoff/m212d/encoders.txt
```
Ожидается: 4 строки — `libx264`, `libx265`, `h264_vaapi`, `hevc_vaapi`; счёт программных — `2`. Нет `libx264` — **СТОП**: повтор на gamebox не сработает, решение владельца.

## Отчёт
`handoff/m212d/REPORT.md`:
```
M212D — IMPLEMENTED, VERIFIED
Коммит: <хэш>; pytest: N passed (было M)
gamebox: libx264 <есть/нет>, libx265 <есть/нет>
```
```bash
bash handoff/bin/report.sh m212d encoders.txt
```
Владельцу в чат — 2 строки:
1. статус и коммит;
2. «потерянный кадр h264_vaapi теперь перерендеривается libx264 сам; на gamebox libx264 — <есть/нет>».
