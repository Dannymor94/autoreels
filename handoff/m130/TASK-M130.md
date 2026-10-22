# TASK M130 (окно MAIN, Mac): рамка держит весь путь лица — Pxl 112938952 r06 вышел из крупного плана

Файлы — в ветке `handoff`, папка `handoff/m130/`: `TASK-M130.md`, `m130-face-span.patch`.

**После M129.** Около 35 минут, из них ~30 — рендер. Без модели, gamebox не нужен.

## Зачем
Владелец о `_gate/m129`, ролик 6: «в этом кадре нет фокуса на человеке (только в нескольких кадрах)» — на крупном плане он у правого края, обрезан.

Причина: рамка ролика неподвижна и ставится по медиане лица (r06 — x 1677). Говорящий в этом ролике наклоняется вправо, а крупный план плотный (×1.6 по лицу) и узкий, и в эти моменты он выходит из кадра.

Патч:
- рамки ролика держат весь путь его лица — от самого левого до самого правого положения в кадрах ролика; крупный план отъезжает настолько, чтобы его вместить (не меньше ×1.15);
- кадров для поиска лица 15 вместо 7, чтобы такие наклоны попали в замер;
- внутри ролика рамка по-прежнему неподвижна.

## Правила
1. Любой шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить.
2. Перед стартом не должно идти других `arl` и рендера. pytest — только в шаге 1. Если упал только `tests/test_menu_bash.py::test_menu_settings_profile_picker_and_cancel` — перезапустить его один раз; прошёл — не СТОП, отметить.
3. Не трогать `reviews/` (только читать `reviews/Pxl 20260621 112938952_m125.review.json`), `manifests/`, другие гейты. Новое — только `reels-out/Pxl 20260621 112938952/_gate/m130/`. `arl auto`, `arl export`, `--install` не запускать.
4. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.

## Шаг 1. Модель на месте, патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -1; git log --oneline -1; pgrep -fl "arl " || echo "arl не запущен"
git apply --check handoff/m130/m130-face-span.patch && git apply handoff/m130/m130-face-span.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add config/render.yaml docs/REEL_SPEC.md src/autoreels/core/calibration.py src/autoreels/local/render.py tests/test_calibration_face.py tests/test_render.py
git commit -m "Render (M130): a reel's frames hold the whole way its face goes (Pxl 112938952 r06 leaned out of the close shot); 15 frames looked at"
git push; git log --oneline -1
```
Ожидается:
- `applied`; pytest — все прошли (новый `test_m130_*`); коммит запушен.

## Шаг 2. Pxl — тот же черновик, рендер в `_gate/m130/`, посты из m125, лист
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m130
S="Pxl 20260621 112938952"; M="reviews/${S}_m125.review.json"
N=$(.venv/bin/python -c "import json,sys;print(len(json.load(open(sys.argv[1]))['reels']))" "$M"); echo "клипов: $N"
arl render --manifest "$M" --reels 1-$N --gate m130 --encoder hevc_videotoolbox 2>&1 | tee handoff/m130/render.log | grep -E "лицо источника|^  кадр |^  крупный план|ошибка|Error" | tee handoff/m130/frames.txt
cp "reels-out/$S/_gate/m125/"r*.post.txt "reels-out/$S/_gate/m130/"
arl review-sheet "$S" --review "reviews/${S}_auto_m123-scen.txt" --manifest-file "$M" --gate m130 --preview none 2>&1 | tail -2
ls "reels-out/$S/_gate/m130/"r*.mp4 | wc -l
git status --short
```
Ожидается:
- по каждому ролику строка `кадр rNN: … лицо ходит по x A…B …`; у r06 диапазон шире, чем у большинства;
- строки `крупный план rNN: ×…` — у r06 меньше 1.6;
- N файлов `.mp4`; лист `reels-out/Pxl 20260621 112938952/_gate/m130/_review.html`;
- новых строк в `git status` нет.

## Шаг 3. Отчёт в ветку
Записать `handoff/m130/REPORT.md`: коммит, строка pytest, `frames.txt` целиком, путь листа.
```bash
bash handoff/bin/report.sh m130 frames.txt
```
Владельцу в чат — две строки:
- диапазон лица и крупный план у r06;
- «смотреть: reels-out/Pxl 20260621 112938952/_gate/m130/_review.html».

Статус: IMPLEMENTED, GATE PENDING.
