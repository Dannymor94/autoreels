# TASK M177 (окно MAIN, Mac): убрать повторы и короткие планы среди клипов разметки (без нового рендера)

Файлы — ветка `handoff`, папка `handoff/m177/`: `TASK-M177.md`, `m177-repeats.patch`, `exclude.py`. Около 15 минут, без рендера.

## Зачем
В m176 вернулись клипы разметки, и вышло 105 вместо ~86. Две проблемы:
1. **Повторы.** Клип разметки и сборка сценариста рассказывают одно и то же. Например, «закрытый шкаф» у prew_isaev_danny: r01 поставлен после r13. Сборки между собой не повторяются (M68), а разметку с ними никто не сравнивал.
2. **11 коротких планов** — все в клипах разметки: правило M173 действовало только на сборки.

Патч:
- в `arl auto` клип разметки убирается, если больше `autocut.combined_overlap_max` (0,3) его секунд звучат в уже оставленном клипе. Сначала оставляются сборки, потом разметка по порядку;
- клип разметки с коротким планом убирается, как сборка;
- 1 = выкл.; тесты `tests/test_m177_repeats.py` (5).

Для готового m176 рендер не нужен: `exclude.py` теми же функциями находит такие клипы и переносит их файлы в `_gate/m176/_excluded/`. Затем выгрузка и сетка заново.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. Ничего не удалять: только перенос в `_excluded/`. `reviews/*_answer*.txt`, `manifests/`, гейты m163/m157/m174 не трогать.
3. pytest — не во время рендера.

## Шаг 1. Патч, тесты, коммит
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m177; mkdir -p handoff/m177
git apply --check handoff/m177/m177-repeats.patch && git apply handoff/m177/m177-repeats.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests config && git commit -m "Auto (M177): a label clip repeating a kept clip (autocut.combined_overlap_max of its seconds, montage first) or with a short shot leaves the combined draft (m176: 105 clips)" && git push && git log --oneline -1
```
Ожидается: `applied`. pytest: всё прошло, кроме известных пяти. `test_menu_bash` под нагрузкой иногда падает — тогда прогнать его отдельно. Коммит запушен.

## Шаг 2. Какие клипы m176 убрать
```bash
.venv/bin/python handoff/m177/exclude.py m176 | tee handoff/m177/exclude.txt
```
Ожидается: по источникам — список с причиной («repeats rNN: X% of its seconds» или «short shot …»). Среди них prew_isaev_danny r01 или r13 (шкаф). ВСЕГО — десятки, не больше 50. Больше 50 — СТОП: порог слишком строгий.

Проверить глазами три пары повторов: тексты постов обоих клипов пары.
```bash
.venv/bin/python - <<'PY' | tee handoff/m177/pairs.txt
import re
from pathlib import Path
cur = None; n = 0
for ln in Path("handoff/m177/exclude.txt").read_text(encoding="utf-8").splitlines():
    m = re.match(r"(\S+): клипов", ln)
    if m: cur = m.group(1); continue
    m = re.match(r"  (r\d+): repeats (r\d+)", ln)
    if m and n < 3:
        n += 1; d = Path("reels-out") / cur / "_gate" / "m176"
        for rid in m.groups():
            p = d / f"{rid}.post.txt"; t = p.read_text(encoding="utf-8")[:300] if p.exists() else "(нет поста)"
            print(f"{cur} {rid}: {t}\n")
        print("-----")
PY
```
Ожидается: в каждой паре один и тот же рассказ. Если нет (разные темы) — в отчёт: значит, совпадение по секундам ловит не то.

## Шаг 3. Перенос, выгрузка, сетка
```bash
.venv/bin/python handoff/m177/exclude.py m176 --do | tail -1
S7=(disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny)
mkdir -p ~/.Trash/autoreels-m177/export && mv export/crosspost/* ~/.Trash/autoreels-m177/export/ && cp ~/.Trash/autoreels-m177/export/schedule.csv export/crosspost/
for S in "${S7[@]}"; do d="reels-out/$S/_gate/m176"; R=$(ls "$d"/r[0-9]*.mp4 | grep -v ERROR | xargs -n1 basename | sed 's/\.mp4$//' | paste -sd, -)
  arl crosspost "$S" --gate m176 --reels "$R" 2>&1 | grep -E "клипов|пропущ"; done | tee handoff/m177/export.txt
.venv/bin/python handoff/m174/grid2.py m176 --from m176 | tee handoff/m177/grid.txt
cp export/crosspost/grid.csv handoff/m177/grid.csv
```
Ожидается: в `grid.txt` число строк = 105 минус убранные, «выпали» = убранные, «новые в конце 0», «в третьем лице: 0».

Посмотреть, не встали ли теперь подряд больше трёх роликов одной серии:
```bash
.venv/bin/python - <<'PY'
import csv
rows = list(csv.DictReader(open("export/crosspost/schedule.csv", encoding="utf-8-sig"), delimiter=";"))
run, prev, worst = 0, None, []
for r in rows:
    run = run + 1 if r["серия"] == prev else 1; prev = r["серия"]
    if run > 3: worst.append(f"{r['№']} {r['серия']}")
print("серия больше 3 дней подряд:", worst or "нет")
PY
```
Если есть — переставить эти строки в `schedule.csv` по смыслу и снова `grid2.py m176 --from m176`.

## Шаг 4. Отчёт
`handoff/m177/REPORT.md`:
- коммит, pytest;
- `exclude.txt` (итоги по источникам);
- `pairs.txt`;
- `export.txt`, `grid.txt`;
- клипов по источникам после.

`bash handoff/bin/report.sh m177 exclude.txt pairs.txt export.txt grid.txt grid.csv`

Владельцу — одна строка: «повторы и короткие планы убраны: N клипов (было 105), сетка — export/crosspost/grid.csv; убранные лежат в _gate/m176/_excluded/».

Статус: IMPLEMENTED, GATE PENDING.
