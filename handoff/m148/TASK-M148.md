# TASK M148 (окно MAIN, Mac): опции концовки, правила сценариста, уборка, документация, старые гейты

Файлы — ветка `handoff`, папка `handoff/m148/`: `TASK-M148.md`, `m148-endings-docs.patch`, `gates.sh`. Около 15 минут, без рендера и без платных моделей.

## Что в патче
- **M151, опции концовки (все выключены, `config/render.yaml`):** `ending_loop` — клип с холодным стартом без ухода в чёрное (петля); `end_freeze_sec` — последний кадр держится N с, затем чёрное; `end_sting_path` + `end_sting_volume` — свой звук после последнего слова. Только план клипа (M1.7); проверка «кадр завис» пропускает добавленный стоп-кадр. Тесты `tests/test_m151_ending.py` (настоящий ffmpeg).
- **M152, сценарист** (владелец об IMG_6848 r01/r09: «спутанный сценарий», «недоговорил»): промпт — не выбрасывать фразы из середины, не открывать на «То есть / Но / И…», кончать там, где говорящий закрыл мысль, а не реакцией интервьюера; ролик, открытый отсылкой назад, код ставит в конец пула (`start_doubt`). Тесты `tests/test_m152_scenario.py`.
- **Уборка:** удалены `src/autoreels/local/archive.py` и `tests/test_archive.py` — модуль нигде не вызывался (архивация — `_archive_video` в CLI, поиск источника — `resolve_source`).
- **Документация M133–M152:** PLAN (таблица автомонтажа, закрытые гейты, «ждут владельца», концовки, две длины = `short_variant`), REEL_SPEC, R0_SPEC, PROJECT_GUIDE, PROJECT_STRUCTURE, README.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. Рендера нет. `reviews/*_answer.txt` не трогать.

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m148
git apply --check handoff/m148/m148-endings-docs.patch && git apply handoff/m148/m148-endings-docs.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add -A src tests config docs PLAN.md PROJECT_GUIDE.md PROJECT_STRUCTURE.md R0_SPEC.md README.md
git commit -m "Render (M151): ending options off (loop, freeze, sting); scenarist (M152): keep sentences in a row, no back-reference opening; remove unused local/archive.py; docs M133–M152" && git push && git log --oneline -1
```
Ожидается: `applied`; pytest — все прошли (локально падали 5 тестов песочницы без ключей/данных — у тебя их быть не должно); коммит запушен.

## Шаг 2. Старые гейты → Корзина (владелец 2026-10-26: «старые гейты закрываем и можем удалять»)
```bash
bash handoff/m148/gates.sh | tee handoff/m148/gates.txt | tail -5
bash handoff/m148/gates.sh --do | tail -2
ls -d reels-out/*/_gate/*/ 2>/dev/null
```
Ожидается: остаются только `m146a`, `m146b`, `m147` (и гейты моложе суток, если есть); остальное в `~/.Trash/autoreels-m148/`. Насовсем ничего не удаляется — место освободится, когда владелец очистит Корзину.

## Шаг 3. Отчёт
`handoff/m148/REPORT.md`: коммит, pytest, сколько гейтов и МБ ушло в Корзину, что осталось.
`bash handoff/bin/report.sh m148 gates.txt`
Владельцу — одна строка: «опции концовки есть (выключены), документация обновлена, старые гейты в Корзине — N МБ освободится после её очистки».
