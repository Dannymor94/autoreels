# TASK M131 (окно MAIN, Mac): лицо говорящего — ближайшее к его месту, а не самое большое (Pxl r14 «поплыл» к слушателю)

Файлы — в ветке `handoff`, папка `handoff/m131/`: `TASK-M131.md`, `m131-speaker.patch`.

**После M130.** Около 35 минут, из них ~30 — рендер. Без модели, gamebox не нужен.

## Зачем
Владелец о `_gate/m130`, ролик 14: «камера поплыла». Лог m130: `кадр r14: лицо в 15 из 15 кадров (x 69.8, высота 252.7) … рамка x 1312 → 0`. В этом ролике у левого края сидит слушатель ближе к камере, его лицо крупнее, чем у говорящего (≈ 210 px), а код брал в каждом кадре самое большое лицо.

Патч: в каждом кадре ролика берётся лицо, ближайшее к месту говорящего во всём источнике (у Pxl x ≈ 1863 по 37 из 40 кадров), а не самое большое. Рамка внутри ролика неподвижна, как и раньше.

## Правила
1. Любой шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить.
2. Перед стартом не должно идти других `arl` и рендера. pytest — только в шаге 1. Если упал только `tests/test_menu_bash.py::test_menu_settings_profile_picker_and_cancel` — перезапустить его один раз; прошёл — не СТОП, отметить.
3. Не трогать `reviews/` (только читать `reviews/Pxl 20260621 112938952_m125.review.json`), `manifests/`, другие гейты. Новое — только `reels-out/Pxl 20260621 112938952/_gate/m131/`. `arl auto`, `arl export`, `--install` не запускать.
4. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.

## Шаг 1. Модель на месте, патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -1; git log --oneline -1; pgrep -fl "arl " || echo "arl не запущен"
git apply --check handoff/m131/m131-speaker.patch && git apply handoff/m131/m131-speaker.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add docs/REEL_SPEC.md src/autoreels/local/autocrop.py src/autoreels/local/render.py tests/test_calibration_face.py
git commit -m "Render (M131): the reel's face is the one nearest the speaker's place in the source, not the largest (Pxl 112938952 r14 went to a listener)"
git push; git log --oneline -1
```
Ожидается:
- `applied`; pytest — все прошли (новый `test_m131_*`); коммит запушен.

## Шаг 2. Pxl — тот же черновик, рендер в `_gate/m131/`, посты из m125, лист
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m131
S="Pxl 20260621 112938952"; M="reviews/${S}_m125.review.json"
N=$(.venv/bin/python -c "import json,sys;print(len(json.load(open(sys.argv[1]))['reels']))" "$M"); echo "клипов: $N"
arl render --manifest "$M" --reels 1-$N --gate m131 --encoder hevc_videotoolbox 2>&1 | tee handoff/m131/render.log | grep -E "лицо источника|^  кадр |^  крупный план|ошибка|Error" | tee handoff/m131/frames.txt
cp "reels-out/$S/_gate/m125/"r*.post.txt "reels-out/$S/_gate/m131/"
arl review-sheet "$S" --review "reviews/${S}_auto_m123-scen.txt" --manifest-file "$M" --gate m131 --preview none 2>&1 | tail -2
ls "reels-out/$S/_gate/m131/"r*.mp4 | wc -l
git status --short
```
Ожидается:
- `лицо источника: x ≈ 1860`;
- у всех роликов, и у r14, `кадр rNN: лицо … (x ≈ 1600–2200 …)`, без `рамка x 1312 → 0`;
- N файлов `.mp4`; лист `reels-out/Pxl 20260621 112938952/_gate/m131/_review.html`;
- новых строк в `git status` нет.

## Шаг 3. Отчёт в ветку
Записать `handoff/m131/REPORT.md`: коммит, строка pytest, `frames.txt` целиком, путь листа.
```bash
bash handoff/bin/report.sh m131 frames.txt
```
Владельцу в чат — две строки:
- куда встала рамка у r14;
- «смотреть: reels-out/Pxl 20260621 112938952/_gate/m131/_review.html».

Статус: IMPLEMENTED, GATE PENDING.
