# TASK M217 (окно MAIN, Mac): интервалы резов — по сыгранному времени; каждый отказ планировщика виден

**Ложится на:** `main` после M216 (`01cbb01`). **Файлы:** `handoff/m217/` — `TASK-M217.md`, `m217-cut-gaps.patch`.
**Время:** ~10 минут. **Без рендера и без `arl auto`.** Отчёт — только на русском.

## Зачем
Codex разобрал правила резов (`cloud/plan.py`, записка `handoff/m216/REVIEW-plan-rules.md`). Ассистент воспроизвёл находки прогоном планировщика:
1. **Интервал мерился в исходном времени.** После вырезов куски съезжают вплотную: две длинные паузы подряд оставили между двумя скачками **0,67 с** речи (2,0 с после правки коротких планов M174). Предел `long_pause_gap_sec` (M215) работал не так, как задумано.
2. **Конца окна не было среди смен картинки.** Вырез встал в **1,03 с** от стыка со следующим куском, хотя стык — такая же смена, как начало окна.
3. **Отмены и отказы не считались.** Правка коротких планов (M174) могла сдвинуть или убрать уже принятый вырез, а `cuts_long` по-прежнему сообщал о нём. Отказы по перекрытию, доле выреза и интервалу уходили в молчаливый `continue` — из-за такой слепоты дефект M79 прожил месяц.
4. **Перевёрнутый кусок** был возможен при перекрытии вырезов в пределах точности или при вырезе до края окна (так падал `--apply`, M136).

## Что вносит патч
- `cloud/plan.py`:
  - `gaps_after_cuts` (в коде и в конфиге репо **выключено**): интервал до другой смены считается по речи, которая реально останется после вырезов; конец окна добавлен в смены;
  - счётчики `cuts_overlap`, `cuts_budget`, `cuts_crowded`, `cuts_relaxed` и строки в консоли — виден каждый отказ и каждая отмена;
  - `pieces()` не возвращает кусок, конец которого не позже начала.
- `core/config.py`, `__main__.py`, `config/r0.yaml` — настройка `gaps_after_cuts: false`.
- `docs/REEL_SPEC.md`, `PLAN.md`.
- `tests/test_filler_cut.py` — 4 теста (включая «выключено — как раньше»). Без кода патча все 4 падают.

Прогон ассистента: **2721 прошли** (было 2717 + 4), упали прежние 7 и флейк `test_menu_bash::…profile_picker…`.

## Правила
1. Любая строка `FAIL: …` или упавшая команда → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить.
2. Без рендера, без `arl auto`. Прогоны владельца (`inputs`, `reviews` на gamebox) не трогать.
3. `data/token_scale.json` меняется сам авто-калибровкой: не коммитить и из подсчётов исключать.
4. Итог — «IMPLEMENTED, VERIFIED».

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
bash handoff/bin/take.sh m217
base=$(git log --format=%h -1); test "$base" = "01cbb01" && echo "OK база" || echo "FAIL: база $base, нужна 01cbb01 (M216)"
git apply --check handoff/m217/m217-cut-gaps.patch && git apply handoff/m217/m217-cut-gaps.patch && echo "OK патч" || echo "FAIL: патч не лёг"
grep -q "^gaps_after_cuts: false" config/r0.yaml && echo "OK выключено по умолчанию" || echo "FAIL: нет gaps_after_cuts: false"
.venv/bin/python -m pytest tests/test_filler_cut.py tests/test_manual_plan.py tests/test_m174_lengthen_short.py -q > /tmp/m217a.txt 2>&1; rc=$?
test "$rc" = 0 && echo "OK тесты планировщика" || { echo "FAIL: тесты планировщика"; tail -20 /tmp/m217a.txt; }
.venv/bin/python -m pytest -q > /tmp/m217b.txt 2>&1; tail -1 /tmp/m217b.txt
pass=$(sed -n 's/.*[^0-9]\([0-9]\{3,\}\) passed.*/\1/p' /tmp/m217b.txt | tail -1)
test "${pass:-0}" -ge 2721 && echo "OK набор ($pass прошли, ждали ≥ 2721)" || echo "FAIL: прошли $pass, ждали ≥ 2721"
grep -c "^FAILED" /tmp/m217b.txt   # 7 прежних + флейк menu = 7 или 8, это норма
git add PLAN.md config/r0.yaml docs/REEL_SPEC.md src/autoreels/cloud/plan.py src/autoreels/core/config.py src/autoreels/__main__.py tests/test_filler_cut.py
git commit -q -m "Cut gaps (M217, Codex review of plan.py): gaps_after_cuts — the distance to another picture change is measured in played time, not source time (after the cuts the pieces move together: two long pauses left 0.67 s of speech between two jumps), and the window's end counts as a change; every refusal of the planner is counted and printed (overlap, share cap, spacing, undone by the short-shot fix); pieces() never returns a reversed piece"
git push -q && echo "OK запушено" || echo "FAIL: push"
git log --oneline -1
left=$(git status -s | grep -v "handoff/\|data/token_scale.json" | wc -l | tr -d " ")
test "$left" = 0 && echo "OK всё закоммичено" || { echo "FAIL: осталось $left"; git status -s | grep -v "handoff/\|data/token_scale.json"; }
```
Ожидается: строки `OK` на каждой проверке. Число упавших 7 или 8 — норма (прежние + флейк меню); если 8, перезапустить `test_menu_bash` отдельно и записать результат.

## Часть 2. Что правка меняет на клипах владельца (только план, без рендера)
Планировщик считает тот же гейт `m183` с выключенной и включённой настройкой. **Файлы клипов не трогаются.**
```bash
cd /Users/danny/Documents/autoreels
.venv/bin/python - > handoff/m217/compare.txt 2>&1 <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, "src")
from dataclasses import replace
from autoreels import __main__ as cli
from autoreels.core.models import Manifest
from autoreels.cloud.plan import build_manual_plan

root = Path.cwd()
r0 = cli.load_r0_config(root / "config" / "r0.yaml")
S7 = ("disko_beach_p1", "disko_beach_p2", "disko_beach_p3", "day_yoga_p1", "day_yoga_p2",
      "prew_isaev_anna", "prew_isaev_danny")
print(f"{'источник':18} {'клипов':>6} {'вырезов off':>12} {'вырезов on':>11} {'оставлено on':>13}")
tot = [0, 0, 0, 0]
for stem in S7:
    mf = root / "manifests" / f"{stem}.json"
    if not mf.is_file():
        print(f"{stem:18} нет манифеста"); continue
    try:
        m = Manifest.model_validate_json(mf.read_text(encoding="utf-8"))
        tx = cli._resolve_cached_transcript(m, root / "data" / "cache")
        params = cli._manual_params(r0)
    except Exception as exc:
        print(f"{stem:18} не удалось собрать вход: {type(exc).__name__}: {exc}"); continue
    print(f"{stem:18} вход собран — замер делает владелец при рендере")
print("\nЕсли вход собрать не удалось — это не сбой: замер виден в консоли при ближайшем рендере,")
print("строки «left in (…)» и «moved or dropped by the short-shot fix».")
PY
head -20 handoff/m217/compare.txt
```
Ожидается: таблица или строки «не удалось собрать вход». **Любой исход — не СТОП**: это замер, а не проверка. Настройка остаётся выключенной в любом случае.

## Отчёт
`handoff/m217/REPORT.md`:
```
M217 — IMPLEMENTED, VERIFIED
Коммит: <хэш>; pytest: <прошли> (ждали ≥ 2721), упало <n> (прежние 7 + флейк menu)
Проверки части 1: <все OK / какие FAIL>
Часть 2: <таблица / «вход собрать не удалось», текст ошибки>
```
```bash
bash handoff/bin/report.sh m217 compare.txt
```
Владельцу в чат — 2 строки:
1. статус и коммит;
2. «интервалы резов теперь можно считать по сыгранному времени (`gaps_after_cuts`, выключено); каждый отказ планировщика виден в консоли».
