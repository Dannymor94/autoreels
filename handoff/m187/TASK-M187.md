# TASK M187 (окно MAIN, Mac): документация M182–M186 и инструменты выпуска в репозиторий

Файлы — ветка `handoff`, папка `handoff/m187/`: `TASK-M187.md`, `m187-docs.patch`. Около 5 минут, без рендера. Отчёт — только на русском.

## Зачем
Владелец 2026-10-29: «теперь нужно всё задокументировать». Патч:
- **PLAN.md**: блок «Автомонтаж» до M187:
  - крючки и начала (итог m183 — 32 из 69, почему у интервью мало);
  - номера подряд (M185);
  - каталог публикации (M186);
  - инструменты выпуска;
  - продакшн 2026-10-29 = чистовик m183.
- **README**: раздел «Выпуск» — пять шагов от листа ревью до `export/publish/`, переключатель `autocut.label_hooks`.
- **PROJECT_STRUCTURE.md**: новые файлы `tools/`.
- **Скрипты выпуска переезжают из handoff в репозиторий:**
  - `tools/grid.py` — бывший `handoff/m174/grid2.py`, теперь `--from` обязателен, без зашитых гейтов;
  - `tools/publish_dir.py`;
  - `tools/measure_shots.py`.

## Шаги
```bash
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; bash handoff/bin/take.sh m187
git apply --check handoff/m187/m187-docs.patch && git apply handoff/m187/m187-docs.patch && echo applied
.venv/bin/python tools/grid.py m183 --from m183 | tail -2
.venv/bin/python tools/publish_dir.py m183 | head -2
.venv/bin/python tools/measure_shots.py reviews/*_m183.review.json | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -2
git add PLAN.md README.md PROJECT_STRUCTURE.md tools && git commit -m "Docs (M187): M182–M186 — hooks and starts, renumbering, export/publish; release tools in tools/ (grid, publish_dir, measure_shots)" && git push && git log --oneline -1
```
Ожидается:
- `applied`;
- `tools/grid.py`: «69 строк … выпали 0»;
- `publish_dir.py` в пробном режиме: «клипов найдено 69, нет файла: 0»;
- `measure_shots`: SLIVER 0;
- pytest — как раньше;
- коммит запушен.

`tools/grid.py` пересобирает `grid.csv` с прежними именами «Что». Если m186 уже выполнен, после него запустить `python tools/publish_dir.py m183 --do`, чтобы вернуть имена `NNN_rXX_…`.

## Отчёт
`handoff/m187/REPORT.md`: коммит, вывод трёх инструментов. `bash handoff/bin/report.sh m187`. Владельцу — одна строка: «документация M182–M186 и инструменты выпуска в main (коммит …)».
