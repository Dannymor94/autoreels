# REPORT M187

## Коммит

`11c5c28` «Docs (M187): M182–M186 — hooks and starts, renumbering, export/publish; release tools in tools/ (grid, publish_dir, measure_shots)»
pytest: 2583 passed, 16 skipped, 9 deselected (exit 0).

## tools/grid.py

```
grid.csv: 69 строк, 2026-10-28 … 2027-01-04; на месте 69 (номер тот же у 69), выпали 0, новые в конце 0
в третьем лице: 0
с хэштегом в заголовке: 0
```

## tools/publish_dir.py (dry run)

```
строк сетки 69, клипов найдено 69, нет файла: 0
  001_r06_prew_isaev_danny.mp4  ← prew_isaev_danny/r06.mp4  (2026-10-28)
  002_r02_day_yoga_p1.mp4  ← day_yoga_p1/r02.mp4  (2026-10-29)
```

## tools/measure_shots.py

```
итого: SLIVER 0, short 0
ВСЕГО: SLIVER 0, short 0
```

## После grid.py

`tools/publish_dir.py m183 --do` запущен — имена `NNN_rXX_…` в `grid.csv` и `export/publish/` восстановлены (69 видео, 69 постов, 69 обложек).
