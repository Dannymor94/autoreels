# TASK M126 (окно MAIN, Mac): слова-паразиты — не в субтитрах, изредка вырезаны из звука, сценарист их избегает; рендер IMG_6848

Файлы — в ветке `handoff`, папка `handoff/m126/`: `TASK-M126.md`, `m126-fillers.patch`.

**После M125** (не параллельно). Около 45 минут, из них ~30 — рендер. gamebox не нужен.

## Зачем
Владелец: «много вводных слов у человека, который говорит». Берём все три варианта, с оговоркой «вырезать можно не часто, иначе вернётся дёрганье».

Отдельно стоящее слово из `filler_removal.filler_words` («Ну, …», «…, как бы, …», «…, вот.»; «Вот этот дом» не трогается):
1. `subtitles_hide_fillers: true` — его нет в субтитрах, звук целиком.
2. `filler_word_cut: true` — оно вырезается из звука как обычный вырез паузы. Действуют те же правила профиля: не ближе 6 с к другой смене картинки (`montage_tempo change_gap_sec`), маска сменой плана, лимит доли вырезанного. Не на краю куска и только если рядом нет звука другого слова. Поэтому вырезы редкие. Вырезанное слово в субтитрах тоже не показывается.
3. Сценарист предпочитает фразы, где таких слов мало, и не начинает и не кончает ими ролик.

Оба флага включаются по решению владельца сразу (`config/r0.yaml`). Откат — две строки. С выключенными флагами выход прежний (тесты).

## Правила
1. Любой шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить.
2. Перед стартом не должно идти других `arl` и рендера. pytest — только в шаге 1. Если упал только `tests/test_menu_bash.py::test_menu_settings_profile_picker_and_cancel` — перезапустить его один раз; прошёл — не СТОП, отметить.
3. Не трогать:
   - `reviews/*_answer.txt`, `reviews/verdicts.jsonl`, черновики прошлых задач, `manifests/`;
   - `reviews/IMG_6848.review.json` — только копия и возврат.

   Новые файлы:
   - `reviews/IMG_6848_auto_m126-scen.txt`;
   - `reviews/IMG_6848_m126.review.json`;
   - `reels-out/IMG_6848/_gate/m126/`.

   `arl auto`, `arl export`, `--install` не запускать.
4. Модель — Sonnet (`--llm sonnet`, названа явно): сценарист с новым правилом — новый запрос, посты. Цена — порядка $0,2.
5. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -1; git log --oneline -1; pgrep -fl "arl " || echo "arl не запущен"
git apply --check handoff/m126/m126-fillers.patch && git apply handoff/m126/m126-fillers.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add config/r0.yaml docs/REEL_SPEC.md src/autoreels/__main__.py src/autoreels/cloud/plan.py src/autoreels/cloud/scenario.py src/autoreels/core/config.py tests/test_filler_cut.py
git commit -m "Plan (M126): standalone filler words hidden from the subtitles and, rarely, cut from the sound under the filler-cut rules; the scenarist avoids them (owner: on)"
git push; git log --oneline -1
```
Ожидается: `applied`; pytest — все прошли (3 новых `test_m126_*` в `tests/test_filler_cut.py`); коммит запушен.

## Шаг 2. Сценарист IMG_6848 с новым правилом, рендер в `_gate/m126/`, посты, лист
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m126
arl autocut IMG_6848 --scenario --llm sonnet --out reviews/IMG_6848_auto_m126-scen.txt 2>&1 | grep -E "^autocut|сценарист|Claude |ошибка" | tee handoff/m126/run.txt
R=reviews/IMG_6848.review.json; B=handoff/m126/IMG_6848.review.json.before
rm -f "$B"; [ -f "$R" ] && cp "$R" "$B"
arl blocks --apply reviews/IMG_6848_auto_m126-scen.txt --labeler auto 2>&1 | tee handoff/m126/apply.txt | tail -5
cp "$R" reviews/IMG_6848_m126.review.json
if [ -f "$B" ]; then cp "$B" "$R" && cmp "$B" "$R" && echo "review.json возвращён"; else rm "$R" && echo "review.json не было — убран"; fi
.venv/bin/python - <<'PY' | tee handoff/m126/fillers.txt
import json
m = json.load(open("reviews/IMG_6848_m126.review.json"))
FW = {"ну", "вот", "значит", "наверное", "типа", "короче"}
for r in m["reels"]:
    segs = r.get("segments") or []
    cuts = sum(1 for s in segs if s.get("window_cut"))
    shown = [w["word"].strip(",.!?…").lower() for w in r.get("subtitles") or []]
    print(f"{r['id']}: вырезов внутри кусков (паузы и паразиты) {cuts}, слов «ну/вот/значит…» в субтитрах {sum(1 for w in shown if w in FW)}, "
          f"длина {sum(s['end'] - s['start'] for s in segs):.0f} с")
PY
N=$(.venv/bin/python -c "import json;print(len(json.load(open('reviews/IMG_6848_m126.review.json'))['reels']))"); echo "клипов: $N"
arl render --manifest reviews/IMG_6848_m126.review.json --reels 1-$N --gate m126 --encoder hevc_videotoolbox 2>&1 | tail -8
arl describe IMG_6848 --gate m126 --llm sonnet 2>&1 | tail -4
arl review-sheet IMG_6848 --review reviews/IMG_6848_auto_m126-scen.txt --manifest-file reviews/IMG_6848_m126.review.json --gate m126 --preview none 2>&1 | tail -2
for f in reels-out/IMG_6848/_gate/m126/r*.mp4; do printf "%s %s\n" "$(basename "$f")" "$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")"; done | tee handoff/m126/render.txt
git status --short
```
Ожидается:
- строки сценариста и `предложено сборок N`, цена;
- `review.json возвращён` (или «не было — убран»);
- в `fillers.txt` по клипу — число вырезов (паузы и паразиты вместе; не чаще раза в 6 с) и сколько «ну/вот/значит…» осталось в субтитрах (оставшиеся — не отдельно стоящие, например «вот этот»);
- рендер без ошибок; посты; лист `reels-out/IMG_6848/_gate/m126/_review.html`;
- новых строк в `git status` нет.

## Шаг 3. Отчёт в ветку
Записать `handoff/m126/REPORT.md`:
1. Коммит, строка pytest.
2. `run.txt`.
3. `fillers.txt` и строки `apply.txt` о вырезах (`cut`), если есть.
4. Возврат `review.json`, `render.txt`, путь листа.

```bash
bash handoff/bin/report.sh m126 run.txt apply.txt fillers.txt render.txt
```
Владельцу в чат — две строки:
- сколько вырезов на ролик и остались ли паразиты в субтитрах;
- «смотреть: reels-out/IMG_6848/_gate/m126/_review.html».

Статус: IMPLEMENTED, GATE PENDING (просмотр владельцем).
