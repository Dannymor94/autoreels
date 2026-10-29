# TASK M186 (окно MAIN, Mac): общий каталог чистовика — NNN_rXX_<источник>.mp4 в порядке публикации

Файлы — ветка `handoff`, папка `handoff/m186/`: `TASK-M186.md`, `publish_dir.py`. Около 5 минут, без рендера и правок кода. Отчёт — только на русском.

## Зачем
Владелец 2026-10-29: «поместить всё в общий каталог с порядковым номером в начале и подписью источника в конце названия».

`export/publish/` — все 69 клипов в порядке сетки:
- имя `NNN_rXX_<источник>.mp4`: номер строки сетки = день публикации, потом номер клипа в его гейте, в конце источник; например `001_r06_prew_isaev_danny.mp4`;
- рядом пост `NNN_rXX_<источник>.txt` и обложка, если crosspost её сделал;
- видео — жёсткие ссылки на файлы гейта m183: место на диске не удваивается, а сами клипы в гейте остаются;
- в `grid.csv` колонка «Что» получает новые имена;
- `schedule.csv` и `plan_by_date.csv` (импорт crosspost) не меняются.

Если сетку потом пересобрать (`grid2.py`), имена в `grid.csv` вернутся к `<источник>/rXX.mp4` — тогда запустить `publish_dir.py` ещё раз.

## Шаги
```bash
cd /Users/danny/Documents/autoreels; git pull -q; bash handoff/bin/take.sh m186; mkdir -p handoff/m186
.venv/bin/python handoff/m186/publish_dir.py m183 | tee handoff/m186/dry.txt
.venv/bin/python handoff/m186/publish_dir.py m183 --do | tail -1 | tee handoff/m186/do.txt
ls export/publish | head -8; ls export/publish/*.mp4 | wc -l
du -sh export/publish; ls -li export/publish/001_*.mp4 reels-out/*/_gate/m183/$(ls export/publish/001_*.mp4 | sed -E 's#.*/001_(r[0-9]+)_.*#\1#').mp4 2>/dev/null | head -3
cp export/crosspost/grid.csv handoff/m186/grid.csv; head -3 handoff/m186/grid.csv
```
Ожидается:
- «клипов найдено 69, нет файла: 0»;
- `export/publish: 69 видео, 69 постов`;
- первые имена `001_…`, `002_…`;
- `du` маленький, потому что ссылки: inode у файла в publish и в гейте один;
- в `grid.csv` «Что» = `001_r06_prew_isaev_danny.mp4` и т. д.

«нет файла» больше 0 — СТОП: сетка и гейт не совпадают.

## Отчёт
`handoff/m186/REPORT.md`: `dry.txt`, `do.txt`, первые 8 имён, `du`. `bash handoff/bin/report.sh m186 dry.txt do.txt grid.csv`.
Владельцу — одна строка: «общий каталог: export/publish — 69 клипов NNN_rXX_<источник>.mp4 с постами, порядок = сетка».
