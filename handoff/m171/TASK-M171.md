# TASK M171 (окно MAIN, Mac): человеческие имена исходников и сетка публикаций по смыслу

Владелец 2026-10-28:
1. **Имена.** IMG_6848 → `prew_isaev_anna`, 10h59 → `disko_beach_p1`, 11h42 → `disko_beach_p2`, 09h33 → `disko_beach_p3`, PXL → `prew_isaev_danny` (рабочая копия `PXL_20260729_copy`; ручной манифест оригинала не трогать), Pxl 122006193 → `day_yoga_p1`, Pxl 112938952 → `day_yoga_p2`. Все имена в нижнем регистре.
2. **Сетка.** Таблица публикаций, по одному ролику в день с сегодняшнего дня (2026-10-28), 19:00 МСК. Порядок — **по смыслу**: соседние ролики связаны темой, вопрос одного раскрывается в следующем, части серии идут по порядку там, где продолжают друг друга.

Ничего не публикуется.

## Правила
1. Шаг упал → **СТОП**.
2. Рендера нет, кроме одной проверки в шаге 1. `--install` не запускать.

## Шаг 1. Переименование
```bash
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m171
.venv/bin/python handoff/m171/rename_sources.py 2>&1 | tee handoff/m171/rename_dry.txt | tail -15
```
Посмотреть `rename_dry.txt`: у каждого из семи — видео, манифест, файлы transcripts/reviews/cache и папка reels-out. СТОП, если какого-то нет или где-то «уже есть».
```bash
.venv/bin/python handoff/m171/rename_sources.py --do 2>&1 | tee handoff/m171/rename.txt | tail -5
git status --short manifests/ | head; git add -A manifests && git commit -m "Sources (M171): human names — prew_isaev_anna/danny, day_yoga_p1-2, disko_beach_p1-3 (owner 2026-10-28)" && git push
.venv/bin/python -m autoreels render --manifest reviews/day_yoga_p1_m163.review.json --reels 1 --gate m171check --encoder hevc_videotoolbox 2>&1 | tail -2
ls reels-out/day_yoga_p1/_gate/m171check/r01.mp4 && mkdir -p ~/.Trash/autoreels-m171 && mv reels-out/day_yoga_p1/_gate/m171check ~/.Trash/autoreels-m171/
```
Ожидается: `СДЕЛАНО`, коммит, проверочный клип собрался (исходник найден под новым именем) и ушёл в Корзину.

## Шаг 2. Выгрузка заново, под новыми именами
```bash
mkdir -p ~/.Trash/autoreels-m171/export && mv export/crosspost/* ~/.Trash/autoreels-m171/export/ 2>/dev/null; ls export/crosspost | wc -l
for SG in "disko_beach_p1|m163" "disko_beach_p2|m163" "disko_beach_p3|m163" "day_yoga_p1|m163" "day_yoga_p2|m163" "prew_isaev_anna|m157" "prew_isaev_danny|m157"; do
  S="${SG%|*}"; G="${SG#*|}"; d="reels-out/$S/_gate/$G"
  R=$(ls "$d"/r[0-9]*.mp4 | grep -v ERROR | xargs -n1 basename | sed 's/\.mp4$//' | paste -sd, -)
  .venv/bin/python -m autoreels crosspost "$S" --gate "$G" --reels "$R" 2>&1 | grep -E "клипов|пропущ"
done | tee handoff/m171/export.txt
.venv/bin/python handoff/m171/clips_for_grid.py
```
Ожидается: 7 строк «клипов N», в сумме 86, без пропусков; `клипов: 86, серий: 7`.

## Шаг 3. Сетка по смыслу
Прочитать `handoff/m171/clips.md` целиком: заголовок и пост каждого ролика. Разложить все 86 роликов в одну последовательность:
- соседние ролики связаны (общая тема; вопрос одного раскрывается в следующем; от простого к глубокому);
- части одной серии (disko_beach p1→p2→p3, day_yoga p1→p2) идут по порядку, когда продолжают друг друга;
- одна серия не идёт больше трёх дней подряд, если без этого можно;
- открывает сетку ролик, понятный без контекста и цепляющий.

Записать `export/crosspost/schedule.csv` (UTF-8 с BOM, разделитель «;») с колонками `№;дата;время;серия;клип;файл;заголовок;пост;связь`:
- дата с 2026-10-28, по одной в день; время 19:00;
- `файл`, `заголовок`, `пост` — из `clips.json`;
- `связь` — 5–12 слов: чем ролик продолжает предыдущий.

Затем проверка и план для crosspost в порядке сетки:
```bash
.venv/bin/python handoff/m171/check_grid.py
.venv/bin/python - <<'PY'
import csv
rows = list(csv.DictReader(open("export/crosspost/schedule.csv", encoding="utf-8-sig", newline=""), delimiter=";"))
with open("export/crosspost/plan_by_date.csv", "w", encoding="utf-8-sig", newline="") as fh:
    w = csv.writer(fh, delimiter=";"); w.writerow(["файл", "текст", "тип"])
    for r in rows: w.writerow([r["файл"], r["пост"], "пост"])
print("plan_by_date.csv:", len(rows))
PY
cp export/crosspost/schedule.csv handoff/m171/schedule.csv
```
Ожидается: `OK: 86 роликов, 2026-10-28 … 2027-01-21`; `plan_by_date.csv: 86`.

## Шаг 4. Отчёт
`handoff/m171/REPORT.md`: коммит, `rename.txt` (итоговая строка), `export.txt`, первые 10 строк сетки (дата — серия клип — заголовок — связь), вывод `check_grid.py`.
`bash handoff/bin/report.sh m171 rename.txt export.txt schedule.csv`
Владельцу: «исходники переименованы; сетка на 86 дней в export/crosspost/schedule.csv, в crosspost — одна таблица plan_by_date.csv в порядке сетки».
