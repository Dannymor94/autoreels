# TASK M215 (окно MAIN, Mac + ssh gamebox): сценарист через чат с `--on-remote` без `scp`; предел для длинной паузы (M79)

Файлы — ветка `handoff`, папка `handoff/m215/`: `TASK-M215.md`, `m215-chat-and-long-pause.patch` (ложится на `main` после M214c, `bf59085`).
Около 10 минут, **без рендера**. Отчёт — только на русском.

## Зачем
1. **Сценарист через чат на удалённой машине.** M207 работает, но при `--on-remote` задание и ответ владелец возил `scp` руками.
2. **Открытый дефект M79.** Длинная пауза режется в обход интервала между резами и доли выреза; на m126 это дало частые резы в r03/r08/r09/r12. План с октября: «возможно, нужен предел».

## Что вносит патч
- `local/remote.py` (`auto_remote`):
  - перед прогоном `exchange/*.scenario.answer.txt` с Mac уезжают на gamebox (rsync только этих файлов) — в логе «на gamebox: ответы чата — …»;
  - после прогона, если вернулось задание `exchange/<ист>.scenario.md`, печатается строка с готовыми путями: файл → чат → ответ сюда → та же команда ещё раз.
- `cloud/plan.py`, `core/config.py`, `config/r0.yaml` — `long_pause_gap_sec` (в коде 0 = как раньше, в конфиге репо **2.0**): длинная пауза по-прежнему обходит интервал и долю выреза, но не берётся ближе 2 с к другой смене картинки; счётчик `cuts_long_spaced` и строка в консоли «long pause(s) left in (too close to another change)».
- `docs/GAMEBOX.md`, `docs/REEL_SPEC.md`, `PLAN.md` (дефект M79 закрыт правкой, ждёт просмотра).
- Тесты: 2 в `tests/test_filler_cut.py` (включая «выключено — как раньше»), 2 в `tests/test_m214c_auto_remote.py`.

Ассистент прогнал весь набор: 2717 прошли (было 2713 + 4), упали прежние 7 и флейк menu.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить.
2. **Без рендера.** Прогоны владельца (`inputs`, `reviews` на gamebox) не трогать. `data/token_scale.json` не коммитить.
3. Итог — «IMPLEMENTED, VERIFIED».

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1
bash handoff/bin/take.sh m215
git apply --check handoff/m215/m215-chat-and-long-pause.patch && git apply handoff/m215/m215-chat-and-long-pause.patch && echo applied
grep -n "^long_pause_gap_sec:" config/r0.yaml
.venv/bin/python -m pytest tests/test_filler_cut.py tests/test_m214c_auto_remote.py tests/test_manual_plan.py -q 2>&1 | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add PLAN.md config/r0.yaml docs/GAMEBOX.md docs/REEL_SPEC.md src/autoreels/cloud/plan.py src/autoreels/core/config.py src/autoreels/__main__.py src/autoreels/local/remote.py tests/test_filler_cut.py tests/test_m214c_auto_remote.py
git commit -m "Chat scenarist on the remote and long pauses (M215): --on-remote sends the chat's answers (exchange/*.scenario.answer.txt) to gamebox before the run and says what to do with a task that came back — the scenarist through a chat without scp; long_pause_gap_sec 2.0 — a long pause is still cut whatever the spacing and share rules say, but never closer than that to another picture change (M79 open defect: bursts of cuts on m126)"
git push; git log --oneline -1
git status -s | grep -v "handoff/\|data/token_scale.json" || echo "всё закоммичено"
```
Ожидается: последний коммит до — M214c (`bf59085`); `applied`; `long_pause_gap_sec: 2.0`; первая строка pytest — все прошли; весь набор — прежнее число плюс 4 (флейк `test_menu_bash::…profile_picker…` — перезапустить отдельно); коммит запушен; «всё закоммичено».

## Часть 2. Что предел меняет на готовых клипах (только план, без рендера)
Клипы гейта `m183` пересобираются в план, **файлы не трогаются**: видно, сколько длинных пауз уйдёт из-за предела.
```bash
cd /Users/danny/Documents/autoreels
S7=(disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny)
for s in "${S7[@]}"; do .venv/bin/python -m autoreels plan "$s" --gate m183 2>/dev/null | grep -E "^cuts " | sed "s|^|$s: |"; done > handoff/m215/plan.txt 2>&1 || true
head -20 handoff/m215/plan.txt; grep -c "left in (too close to another change)" handoff/m215/plan.txt
```
Ожидается: строки `cuts …` по источникам; где длинные паузы стояли вплотную к другой смене — «long pause(s) left in (too close to another change)».
Команды `plan` с такими ключами нет — **не СТОП**: записать «команды нет», этот замер делает владелец при следующем рендере.

## Отчёт
`handoff/m215/REPORT.md`:
```
M215 — IMPLEMENTED, VERIFIED
Коммит: <хэш>; pytest: N passed (было M)
Предел длинной паузы: оставлено пауз в m183 — <n> (или «команды нет»)
```
```bash
bash handoff/bin/report.sh m215 plan.txt
```
Владельцу в чат — 2 строки:
1. статус и коммит;
2. «сценарист через чат теперь работает с `--on-remote` сам: задание приедет на Mac, ответ положить в `exchange/` и повторить команду; длинная пауза больше не режется вплотную к другой смене».
