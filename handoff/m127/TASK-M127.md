# TASK M127 (окно MAIN, Mac): рамка по лицу источника — Pxl 20260621 112938952 «на чайнике»

Файлы — в ветке `handoff`, папка `handoff/m127/`: `TASK-M127.md`, `m127-source-face.patch`.

**После M126.** Около 35 минут, из них ~30 — рендер. gamebox не нужен, модель не нужна.

## Зачем
Владелец о `_gate/m125` (сценарист, Pxl 112938952): «фокус взят на чайник, кроме 15, 14, 6 и 4 — человек левее».

Рамка источника у Pxl — `setup_id: auto`, середина кадра 3840×2160, а это полки. M102 сдвигает рамку ролика к лицу, если лицо найдено хотя бы в 40% из 7 кадров ролика. Детектор видит этого говорящего примерно в половине кадров (M87 на этом же видео: 10–11 из 20). Поэтому 12 роликов своего лица не нашли и остались посередине.

Патч: если ролик своего лица не нашёл, рамка ставится по месту лица во всём источнике. Это 40 кадров равномерно по видео, преобладающее место, не меньше чем в 4 кадрах. Ищется один раз за рендер. Ролики со своим лицом — как раньше. Рамка внутри ролика неподвижна. Флаг `framing_source_fallback` (`config/render.yaml`) включён; выключенный — прежний выход.

## Правила
1. Любой шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить.
2. Перед стартом не должно идти других `arl` и рендера. pytest — только в шаге 1. Если упал только `tests/test_menu_bash.py::test_menu_settings_profile_picker_and_cancel` — перезапустить его один раз; прошёл — не СТОП, отметить.
3. Не трогать:
   - `reviews/` (только читать `reviews/Pxl 20260621 112938952_m125.review.json`);
   - `manifests/`;
   - `_gate/m125`.

   Новое — только `reels-out/Pxl 20260621 112938952/_gate/m127/`. `arl auto`, `arl export`, `--install` не запускать.
4. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -1; git log --oneline -1; pgrep -fl "arl " || echo "arl не запущен"
git apply --check handoff/m127/m127-source-face.patch && git apply handoff/m127/m127-source-face.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add config/render.yaml docs/REEL_SPEC.md src/autoreels/core/config.py src/autoreels/local/render.py tests/test_calibration_face.py tests/test_render.py
git commit -m "Render (M127): a reel without its own face is framed on the speaker's place in the whole source (Pxl 112938952: 12 of 16 reels stayed on the shelves)"
git push; git log --oneline -1
```
Ожидается: `applied`; pytest — все прошли (новый `test_m127_*`); коммит запушен.

## Шаг 2. Тот же черновик Pxl — рендер в `_gate/m127/`, посты из m125, лист
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m127
S="Pxl 20260621 112938952"; M="reviews/${S}_m125.review.json"
N=$(.venv/bin/python -c "import json,sys;print(len(json.load(open(sys.argv[1]))['reels']))" "$M"); echo "клипов: $N"
arl render --manifest "$M" --reels 1-$N --gate m127 --encoder hevc_videotoolbox 2>&1 | tee handoff/m127/render.log | grep -E "лицо источника|^  кадр |ошибка|Error" | tee handoff/m127/frames.txt
cp "reels-out/$S/_gate/m125/"r*.post.txt "reels-out/$S/_gate/m127/"
arl review-sheet "$S" --review "reviews/${S}_auto_m123-scen.txt" --manifest-file "$M" --gate m127 --preview none 2>&1 | tail -2
ls "reels-out/$S/_gate/m127/"r*.mp4 | wc -l
git status --short
```
Ожидается:
- строка `лицо источника: x …, в K из 40 кадров`, где x заметно меньше 1920 — человек левее середины;
- по каждому ролику строка `кадр rNN: …`; у роликов без своего лица — `по лицу источника`;
- N файлов `.mp4`; лист `reels-out/Pxl 20260621 112938952/_gate/m127/_review.html`;
- новых строк в `git status` нет.

`лицо источника: не найдено` — не СТОП: записать в отчёт и всё равно доделать шаг.

## Шаг 3. Отчёт в ветку
Записать `handoff/m127/REPORT.md`:
1. Коммит и строка pytest.
2. `frames.txt` целиком.
3. Путь листа.

```bash
bash handoff/bin/report.sh m127 frames.txt
```
Владельцу в чат — две строки:
- где нашлось лицо источника и сколько роликов кадрированы по нему;
- «смотреть: reels-out/Pxl 20260621 112938952/_gate/m127/_review.html».

Статус: IMPLEMENTED, GATE PENDING.
