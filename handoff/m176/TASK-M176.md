# TASK M176 (окно MAIN, Mac): вернуть клипы разметки в arl auto + перепрогон в m176 + сетка

Файлы — ветка `handoff`, папка `handoff/m176/`: `TASK-M176.md`, `m176-combined.patch`. Долго: перепрогон 7 источников с рендером (в фоне, около 2 ч). Сценарист — из кэша.

## Зачем
По замеру m175 общий черновик (строки разметки + сборки) не проходил у 5 из 7 источников, и в m174 вошли только сборки: 61 клип вместо 86–88. Две причины:
1. **«no room after last word»** у строк разметки (13 клипов в 5 источниках): после последнего слова нет места до следующей речи. Правило M166 верное, но отказ одного клипа ронял весь черновик.
   - Патч: в `arl auto` (и только там) такой клип убирается из черновика один, с строкой «⚠ rNN убран из черновика: …», остальное собирается.
   - Так же с «short shot».
   - Проверка строки автомонтажа и обычный `--apply` отказывают как раньше (тест).
2. **«montage M1: label used twice»** (disko_beach_p3, day_yoga_p2): в черновике разметки есть свои строки M, и номера сборок с ними совпадали. Патч: в общем черновике сборки нумеруются после строк разметки.

Тесты `tests/test_m176_combined_draft.py` (4).

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. `--install` не запускать. `reviews/*_answer*.txt` и `manifests/` не трогать. Гейты `m163`, `m157`, `m174` не трогать.
3. Рендер один за раз; pytest — не во время рендера.

## Шаг 1. Патч, тесты, коммит
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m176; mkdir -p handoff/m176
git apply --check handoff/m176/m176-combined.patch && git apply handoff/m176/m176-combined.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests && git commit -m "Auto (M176): a refused automatic clip leaves the combined draft alone (not the whole draft); autocut montage lines numbered after the label draft's (m175: 86 → 61 clips)" && git push && git log --oneline -1
```
Ожидается: `applied`. pytest: всё прошло, кроме известных (`test_run_dispatch_*` ×4, `test_r0_output_parsing_survives_lower_max_tokens`; `test_menu_bash` иногда падает под нагрузкой и проходит отдельно — тогда прогнать его отдельно). Коммит запушен.

## Шаг 2. Перепрогон (в фоне)
```bash
S7=(disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny)
nohup .venv/bin/python -m autoreels auto "${S7[@]}" --gate m176 --tag m176 --encoder hevc_videotoolbox > handoff/m176/auto.txt 2>&1 &
echo "pid $!"
```
Проверять раз в 10 минут (`tail -5 handoff/m176/auto.txt`) до строки `=== auto: итог`.

## Шаг 3. Итог, замер, посты, выгрузка, сетка
```bash
sed -n '/=== auto: итог/,$p' handoff/m176/auto.txt | tee handoff/m176/itog.txt
grep -h "убран из черновика" handoff/m176/auto.txt | tee handoff/m176/dropped.txt | wc -l
.venv/bin/python handoff/m173/measure_shots.py reviews/*_m176.review.json > handoff/m176/after.txt; tail -1 handoff/m176/after.txt
for S in "${S7[@]}"; do d="reels-out/$S/_gate/m176"
  for k in 1 2; do miss=$(for f in "$d"/r[0-9]*.mp4; do b=$(basename "$f" .mp4); [ -f "$d/$b.post.txt" ] || echo "$b"; done | paste -sd, -)
    [ -z "$miss" ] && break; arl describe "$S" --gate m176 --reels "$miss" --force --llm sonnet 2>&1 | grep -E "^describe|не принято"; done
  echo "$S: клипов $(ls "$d"/r[0-9]*.mp4 | grep -v ERROR | wc -l), ERROR: $(ls "$d" | grep -c ERROR), без поста: $(for f in "$d"/r[0-9]*.mp4; do b=$(basename "$f" .mp4); [ -f "$d/$b.post.txt" ] || echo "$b"; done | paste -sd, -)"
done | tee handoff/m176/posts.txt
mkdir -p ~/.Trash/autoreels-m176/export && mv export/crosspost/* ~/.Trash/autoreels-m176/export/ && cp ~/.Trash/autoreels-m176/export/schedule.csv export/crosspost/
for S in "${S7[@]}"; do d="reels-out/$S/_gate/m176"; R=$(ls "$d"/r[0-9]*.mp4 | grep -v ERROR | xargs -n1 basename | sed 's/\.mp4$//' | paste -sd, -)
  arl crosspost "$S" --gate m176 --reels "$R" 2>&1 | grep -E "клипов|пропущ"; done | tee handoff/m176/export.txt
.venv/bin/python handoff/m174/grid2.py m176 --from m174 | tee handoff/m176/grid.txt
```
Ожидается:
- в итоге нет «общий черновик не прошёл»;
- клипов около 86;
- `dropped.txt` — около 13 строк (это клипы с «no room», которые раньше роняли черновик);
- SLIVER 0;
- «без поста:» пусто;
- `grid.txt`: «в третьем лице: 0», «с хэштегом в заголовке: 0».

Клип с ERROR при рендере — перерендерить его один раз: `arl render --manifest reviews/<S>_m176.review.json --reels <N> --gate m176 --encoder hevc_videotoolbox`. Опять ERROR — в отчёт.

Новые клипы (клипы разметки, которых нет в m174) `grid2.py` ставит в конец. Прочитать их посты и переставить каждый в `export/crosspost/schedule.csv` на место по смыслу, рядом с близким по теме. Правила m171:
- соседние связаны;
- части серий по порядку;
- одна серия не больше трёх дней подряд, если без этого можно;
- «связь» заполнить.

Затем `python handoff/m174/grid2.py m176 --from m176`: «выпали 0, новые 0». И `cp export/crosspost/grid.csv handoff/m176/grid.csv`.

## Шаг 4. Отчёт
`handoff/m176/REPORT.md`:
- коммит, pytest;
- `itog.txt` — клипов по источникам против m174 и m163/m157;
- `dropped.txt`, итог `after.txt`, `posts.txt`, `export.txt`, `grid.txt`;
- куда встали новые клипы.

`bash handoff/bin/report.sh m176 itog.txt dropped.txt after.txt posts.txt export.txt grid.txt grid.csv`

Владельцу — две строки:
- «перепрогон: N клипов в _gate/m176 (m174 — 61, до правил против скачков — 86); листы reels-out/<источник>/_gate/m176/_review.html»;
- «сетка — export/crosspost/grid.csv, N строк».

Статус: IMPLEMENTED, GATE PENDING.
