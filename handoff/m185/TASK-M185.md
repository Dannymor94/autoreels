# TASK M185 (окно MAIN, Mac): номера клипов без пропусков — r01, r02, … (без перерендера)

Файлы — ветка `handoff`, папка `handoff/m185/`: `TASK-M185.md`, `m185-renumber.patch`, `renumber_gate.py`. Около 10 минут. Отчёт — только на русском.

## Зачем
Владелец о `_gate/m183`: «почему они так пронумерованы, нет 1 и т. д.» (r03, r11, r12…).

Номера даются клипам общего черновика до отсева. Затем убираются повторы, слабые начала, короткие планы — и остаются дыры.

Патч:
- после отсева в `arl auto` клипы нумеруются заново, подряд;
- тест `test_m185_clips_left_are_numbered_without_gaps` в `tests/test_m177_repeats.py`.

Для готового m183 рендер не нужен — `renumber_gate.py`:
- переименует файлы клипов (mp4, пост, подпись, расшифровка…) через временные имена;
- в `reviews/<S>_m183.review.json` оставит только эти клипы с новыми номерами (прежний — `.before-m185.json`);
- поправит `schedule.csv`.

Затем — лист ревью, выгрузка и сетка заново.

## Шаги
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; git pull -q; pgrep -fl "autoreels" || echo "не запущен"; bash handoff/bin/take.sh m185; mkdir -p handoff/m185
git apply --check handoff/m185/m185-renumber.patch && git apply handoff/m185/m185-renumber.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests && git commit -m "Auto (M185): the clips left after the combined draft's checks are numbered r01, r02, … again (owner: gaps in m183)" && git push && git log --oneline -1
.venv/bin/python handoff/m185/renumber_gate.py m183 | tee handoff/m185/dry.txt
.venv/bin/python handoff/m185/renumber_gate.py m183 --do | tee handoff/m185/do.txt
for S in disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny; do
  echo "$S: $(ls reels-out/$S/_gate/m183/r*.mp4 | xargs -n1 basename | paste -sd' ' -)"
  D="reviews/${S}_auto_all_m183.txt"; [ -f "$D" ] || D="reviews/${S}_auto_m183.txt"
  arl review-sheet "$S" --gate m183 --manifest-file "reviews/${S}_m183.review.json" --review "$D" 2>&1 | tail -1
done | tee handoff/m185/after.txt
mkdir -p ~/.Trash/autoreels-m185/export && mv export/crosspost/* ~/.Trash/autoreels-m185/export/ && cp ~/.Trash/autoreels-m185/export/schedule.csv export/crosspost/
for S in disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny; do d="reels-out/$S/_gate/m183"
  R=$(ls "$d"/r[0-9]*.mp4 | grep -v ERROR | xargs -n1 basename | sed 's/\.mp4$//' | paste -sd, -); arl crosspost "$S" --gate m183 --reels "$R" 2>&1 | grep -E "клипов|пропущ"; done | tee handoff/m185/export.txt
.venv/bin/python handoff/m174/grid2.py m183 --from m183 | tee handoff/m185/grid.txt
cp export/crosspost/grid.csv handoff/m185/grid.csv
```
Ожидается:
- `applied`; pytest — всё прошло, кроме известных пяти;
- в `after.txt` у каждого источника номера r01…rNN подряд, лист ревью записан;
- 7 строк «клипов N», в сумме 69;
- в `grid.txt` 69 строк, «выпали 0, новые в конце 0».

Если `review-sheet` ругается на черновик — в отчёт; это не СТОП, клипы и сетка важнее.

## Отчёт
`handoff/m185/REPORT.md`: коммит, `do.txt`, `after.txt`, `export.txt`, `grid.txt`. `bash handoff/bin/report.sh m185 do.txt after.txt grid.txt grid.csv`.
Владельцу — одна строка: «номера подряд r01…, листы ревью и сетка обновлены».
