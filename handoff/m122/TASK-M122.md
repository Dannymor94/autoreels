# TASK M122 (окно MAIN, Mac): предложений вдвое больше, чем владелец берёт; рендер IMG_6848 для просмотра

Файлы — в ветке `handoff`, папка `handoff/m122/`: `TASK-M122.md`, `m122-proposals.patch`.

**Только после M121** (коммит M121 в `main`). Около 40 минут, из них ~25 — рендер. gamebox не нужен.

## Зачем
m120: смешанная сборка строит достаточно кандидатов — на трёх источниках 46, из них 11 похожи на клипы владельца. Но потолок «1 сборка на 3,5 мин» пропускает 26, и наверх встают не те: в прогоне с моделью покрыто 5 из 31.

Владелец сам берёт примерно 1 клип на 3,5 мин и выбирает на листе ревью. Поэтому черновик должен предлагать больше: `clips_every_min: 2`, примерно вдвое больше его выбора.

Тесты, проверяющие порядок при заданном `clips`, теперь фиксируют `clips_every_min: 0` и не зависят от значения по умолчанию.

Затем — рендер черновика IMG_6848 в `_gate/m122/` с листом ревью, чтобы владелец посмотрел глазами (скачки, перестановки, концовки). Его разметка и `reviews/IMG_6848.review.json` не меняются: копия сохраняется до `--apply` и возвращается сразу после.

## Правила
1. Любой шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить.
2. Перед стартом не должно идти других `arl` и рендера. pytest — только в шаге 1, во время рендера — нет. Если упал только `tests/test_menu_bash.py::test_menu_settings_profile_picker_and_cancel` — перезапустить его один раз; прошёл — не СТОП, отметить.
3. Не трогать:
   - `reviews/*_answer.txt`, `reviews/verdicts.jsonl`, черновики прошлых задач, манифесты в `manifests/`;
   - `reviews/IMG_6848.review.json` — только копия и возврат (шаг 3).

   Новые файлы:
   - `reviews/<stem>_auto_m122.txt`;
   - `reviews/IMG_6848_m122.review.json`;
   - `reels-out/IMG_6848/_gate/m122/`.

   `arl auto`, `arl export`, `--install` не запускать.
4. Модель — Claude Haiku (`--llm haiku`, назван явно): у него лучше плашки. Цена — меньше $0,1.
5. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -1; git log --oneline -1; pgrep -fl "arl " || echo "arl не запущен"
git apply --check handoff/m122/m122-proposals.patch && git apply handoff/m122/m122-proposals.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add config/r0.yaml tests/test_autocut.py
git commit -m "Autocut (M122): the draft offers one clip per 2 min of a talk (the owner keeps one per 3.5 and chooses on the sheet); count-sensitive tests pin clips_every_min"
git push; git log --oneline -1
```
Ожидается:
- последний коммит до патча — M121; `applied`;
- pytest — все прошли (с оговоркой правила 2); коммит запушен.

## Шаг 2. Черновики трёх источников с новыми значениями по умолчанию
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m122; rm -f handoff/m122/run.txt
for S in "IMG_6848" "2026-08-08 11h 42m 49s" "Pxl 20260621 112938952"; do
  { echo "=== $S"; arl autocut "$S" --llm haiku --out "reviews/${S}_auto_m122.txt"; } 2>&1 | tee -a handoff/m122/run.txt | grep -E "^autocut|сборок: до|Claude |ошибка"
done
.venv/bin/python handoff/m120/owner_drafts.py m120-montage m120-mixed m122 2>&1 | tee handoff/m122/drafts.txt
```
Ожидается:
- `сборок: до 18`, `до 7`, `до 23`;
- строки `autocut …: предложено сборок N` и цены;
- в `drafts.txt` — строки m122 рядом с m120 и «ВСЕГО».

## Шаг 3. Рендер IMG_6848 в `_gate/m122/` и лист ревью
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
R=reviews/IMG_6848.review.json; B=handoff/m122/IMG_6848.review.json.before
rm -f "$B"; [ -f "$R" ] && cp "$R" "$B"
arl blocks --apply reviews/IMG_6848_auto_m122.txt --labeler auto 2>&1 | tail -5
cp "$R" reviews/IMG_6848_m122.review.json
if [ -f "$B" ]; then cp "$B" "$R" && cmp "$B" "$R" && echo "review.json возвращён"; else rm "$R" && echo "review.json не было — убран"; fi
N=$(.venv/bin/python -c "import json;print(len(json.load(open('reviews/IMG_6848_m122.review.json'))['reels']))"); echo "клипов: $N"
arl render --manifest reviews/IMG_6848_m122.review.json --reels 1-$N --gate m122 --encoder hevc_videotoolbox 2>&1 | tail -8
arl review-sheet IMG_6848 --review reviews/IMG_6848_auto_m122.txt --manifest-file reviews/IMG_6848_m122.review.json --gate m122 --preview none 2>&1 | tail -3
for f in reels-out/IMG_6848/_gate/m122/*.mp4; do printf "%s %s\n" "$(basename "$f")" "$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")"; done | tee handoff/m122/render.txt
git status --short
```
Ожидается:
- `--apply` прошёл без ошибки; `review.json возвращён` (или «не было — убран»);
- `клипов: N`, где N совпадает с числом сборок IMG_6848 из шага 2;
- рендер без ошибок; путь листа `reels-out/IMG_6848/_gate/m122/_review.html`;
- в `render.txt` N файлов с длительностями;
- новых строк в `git status` нет.

## Шаг 4. Отчёт в ветку
Записать `handoff/m122/REPORT.md`:
1. Коммит шага 1 и строка pytest.
2. Из `run.txt`: по источнику — `сборок: до N`, `предложено сборок K` со скобками, цена.
3. `drafts.txt` целиком.
4. Строку о возврате `review.json`, число клипов, `render.txt` и путь листа.

```bash
cd /Users/danny/Documents/autoreels
bash handoff/bin/report.sh m122 run.txt drafts.txt render.txt
```
Владельцу в чат — две строки:
- сборок и покрытие m122 против m120;
- «смотреть: reels-out/IMG_6848/_gate/m122/_review.html».

Статус: IMPLEMENTED, GATE PENDING (просмотр владельцем).
