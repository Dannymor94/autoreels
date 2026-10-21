# TASK M129 (окно MAIN, Mac): лица для рамки — YuNet вместо каскада Хаара; Pxl 112938952 заново

Файлы — в ветке `handoff`, папка `handoff/m129/`: `TASK-M129.md`, `m129-yunet.patch`.

**После M128.** Около 35 минут, из них ~30 — рендер. Без модели, gamebox не нужен.

## Зачем
Замер m128 на Pxl 112938952:
- каскад Хаара нашёл «лицо» в 5 кадрах из 12, ни разу с глазом; самая большая находка — полка с чайниками (x 894, высота 668 px). Рамки роликов уходили туда, а m127 разнёс ошибку на все ролики;
- YuNet нашёл говорящего в 12 из 12 кадров: x ≈ 1650–1940, высота ≈ 210 px, score ≥ 0.84. Это середина кадра, где и стоит рамка источника.

Патч: лица для рамки ролика (M102) и для лица источника (M127) ищет YuNet (`face_model` в `config/render.yaml`; файл модели скачан в m128 в `data/models/`). Нет файла — каскад Хаара, как раньше.

## Правила
1. Любой шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить.
2. Перед стартом не должно идти других `arl` и рендера. pytest — только в шаге 1. Если упал только `tests/test_menu_bash.py::test_menu_settings_profile_picker_and_cancel` — перезапустить его один раз; прошёл — не СТОП, отметить.
3. Не трогать `reviews/` (только читать `reviews/Pxl 20260621 112938952_m125.review.json`), `manifests/`, другие гейты. Новое — только `reels-out/Pxl 20260621 112938952/_gate/m129/`. `arl auto`, `arl export`, `--install` не запускать.
4. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.

## Шаг 1. Модель на месте, патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -1; git log --oneline -1; pgrep -fl "arl " || echo "arl не запущен"
ls -la data/models/face_detection_yunet_2023mar.onnx
git apply --check handoff/m129/m129-yunet.patch && git apply handoff/m129/m129-yunet.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add config/render.yaml docs/REEL_SPEC.md src/autoreels/core/config.py src/autoreels/local/autocrop.py src/autoreels/local/render.py tests/test_calibration_face.py
git commit -m "Render (M129): the reel framing finds faces with YuNet (m128: the Haar cascade framed Pxl 112938952 on a shelf of teapots); no model file = Haar as before"
git push; git log --oneline -1
```
Ожидается:
- файл модели есть, около 230 КБ (если файла нет — СТОП);
- `applied`; pytest — все прошли (новый `test_m129_*`); коммит запушен.

## Шаг 2. Pxl — тот же черновик, рендер в `_gate/m129/`, посты из m125, лист
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m129
S="Pxl 20260621 112938952"; M="reviews/${S}_m125.review.json"
N=$(.venv/bin/python -c "import json,sys;print(len(json.load(open(sys.argv[1]))['reels']))" "$M"); echo "клипов: $N"
arl render --manifest "$M" --reels 1-$N --gate m129 --encoder hevc_videotoolbox 2>&1 | tee handoff/m129/render.log | grep -E "лицо источника|^  кадр |ошибка|Error" | tee handoff/m129/frames.txt
cp "reels-out/$S/_gate/m125/"r*.post.txt "reels-out/$S/_gate/m129/"
arl review-sheet "$S" --review "reviews/${S}_auto_m123-scen.txt" --manifest-file "$M" --gate m129 --preview none 2>&1 | tail -2
ls "reels-out/$S/_gate/m129/"r*.mp4 | wc -l
git status --short
```
Ожидается:
- `лицо источника: x ≈ 1700–1950`;
- у роликов в `кадр rNN:` x лица около 1650–1950 и чаще всего «в центре рамки, рамка источника» (x рамки 1312), без ухода к x ≈ 270;
- N файлов `.mp4`; лист `reels-out/Pxl 20260621 112938952/_gate/m129/_review.html`;
- новых строк в `git status` нет.

Если у какого-то ролика рамка ушла к x < 800 — не СТОП, отметить в отчёте номер ролика.

## Шаг 3. Отчёт в ветку
Записать `handoff/m129/REPORT.md`: коммит, строка pytest, `frames.txt` целиком, путь листа.
```bash
bash handoff/bin/report.sh m129 frames.txt
```
Владельцу в чат — две строки:
- куда встали рамки;
- «смотреть: reels-out/Pxl 20260621 112938952/_gate/m129/_review.html».

Статус: IMPLEMENTED, GATE PENDING.
