# TASK M123 (окно MAIN, Mac): сценарист — ролики пишет модель по всему тексту, код проверяет; ролики длиннее; рендер IMG_6848

Файлы — в ветке `handoff`, папка `handoff/m123/`: `TASK-M123.md`, `m123-scenarist.patch`, `test_scenario_recorded.py`.

**Ставится поверх M122** (2d65e3b). Около 60 минут, из них ~30 — рендер. gamebox не нужен.

## Зачем
Владелец о m122: «везде какая-то проблема со сценарием», хороши только 5 и 9, ролики коротковаты — «можно длиннее».

Причина: автосборка видит у мысли одну строку пересказа, а не текст, и не понимает, есть ли в ролике вопрос, развитие и вывод. M1 из m122 — ответ на вопрос, которого зритель не слышал.

Патч:
- `arl autocut … --scenario --llm sonnet|haiku` — сценарист. Модель читает весь текст видео (фразы `B.k [сек] текст`) и пишет ролики строками разметки: о чём ролик, где крючок, где вывод.
  - Перестановки и тизер разрешены.
  - Код проверяет каждую строку правилами автосборки: фразы только из нумерации, длина, скачки, законченный конец не «→», затем `--apply`.
  - Принятое оформляется как обычно: плашка, `k:`, `c:`.
  - Непринятое попадает в черновик с причиной.
  - Примеры для модели — клипы владельца из других видео.
  - Ответ модели кэшируется в `data/cache/scenario/`: повторный запуск не платит второй раз.
- Длина автосборки: `target_sec` 35 → 55, `max_sec` 65 → 90.

## Правила
1. Любой шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить.
2. Перед стартом не должно идти других `arl` и рендера. pytest — в шагах 1 и 5, не во время рендера. Если упал только `tests/test_menu_bash.py::test_menu_settings_profile_picker_and_cancel` — перезапустить его один раз; прошёл — не СТОП, отметить.
3. Не трогать:
   - `reviews/*_answer.txt`, `reviews/verdicts.jsonl`, черновики прошлых задач, `manifests/`;
   - `reviews/IMG_6848.review.json` — только копия и возврат (шаг 4).

   Новые файлы:
   - `reviews/<stem>_auto_m123*.txt`;
   - `reviews/IMG_6848_m123.review.json`;
   - `reels-out/IMG_6848/_gate/m123/`.

   `arl auto`, `arl export`, `--install` не запускать.
4. Модель названа явно: сценарист — Sonnet, автосборка для сравнения — Haiku. Ожидаемая цена всего — до $0,5; строки цены печатаются.
5. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -1; git log --oneline -1; pgrep -fl "arl " || echo "arl не запущен"
git apply --check handoff/m123/m123-scenarist.patch && git apply handoff/m123/m123-scenarist.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add config/r0.yaml docs/REEL_SPEC.md src/autoreels/__main__.py src/autoreels/cloud/scenario.py src/autoreels/core/config.py tests/test_scenario.py
git commit -m "Autocut (M123): the scenarist — a named model writes the reels from the whole text, the code checks every line with the automatic path's rules; reels longer (target 55, max 90)"
git push; git log --oneline -1
```
Ожидается:
- последний коммит до патча — M122 (2d65e3b); `applied`;
- pytest — все прошли, среди них 4 новых в `tests/test_scenario.py`; коммит запушен.

## Шаг 2. Сценарист и автосборка — три источника
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m123; rm -f handoff/m123/run.txt
for S in "IMG_6848" "2026-08-08 11h 42m 49s" "Pxl 20260621 112938952"; do
  { echo "=== $S scenarist"; arl autocut "$S" --scenario --llm sonnet --out "reviews/${S}_auto_m123-scen.txt"; } 2>&1 | tee -a handoff/m123/run.txt | grep -E "^autocut|сценарист|Claude |ошибка"
  { echo "=== $S autocut"; arl autocut "$S" --llm haiku --out "reviews/${S}_auto_m123.txt"; } 2>&1 | tee -a handoff/m123/run.txt | grep -E "^autocut|Claude |ошибка"
done
.venv/bin/python handoff/m120/owner_drafts.py m122 m123 m123-scen 2>&1 | tee handoff/m123/drafts.txt
grep -h "^#   сценарий:" "reviews/IMG_6848_auto_m123-scen.txt" | head -20 | tee handoff/m123/why.txt
```
Ожидается:
- у сценариста — строки `сценарист: claude-…, фраз N, до K роликов …`, `сценарист: строк X, принято кодом Y …`, `autocut …: предложено сборок M` и цена;
- у автосборки — `предложено сборок M` и цена;
- в `drafts.txt` — три тега по трём источникам и «ВСЕГО»;
- в `why.txt` — по строке «сценарий: …» на ролик.

Сценарист вернул 0 принятых строк — не СТОП: записать причины из раздела `# --- сценарист:` черновика.

## Шаг 3. Записать настоящий ответ сценариста как фикстуру
```bash
cd /Users/danny/Documents/autoreels
F=$(ls -t data/cache/scenario/IMG_6848.*.txt | head -1); echo "$F"
cp "$F" tests/fixtures/scenario_raw_IMG_6848.txt
cp handoff/m123/test_scenario_recorded.py tests/test_scenario_recorded.py
.venv/bin/python -m pytest -q tests/test_scenario_recorded.py tests/test_scenario.py 2>&1 | tail -2
```
Ожидается: тесты прошли. Коммит — в шаге 5, после рендера.

## Шаг 4. Рендер сценариста IMG_6848 в `_gate/m123/` и лист ревью
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
R=reviews/IMG_6848.review.json; B=handoff/m123/IMG_6848.review.json.before
rm -f "$B"; [ -f "$R" ] && cp "$R" "$B"
arl blocks --apply "reviews/IMG_6848_auto_m123-scen.txt" --labeler auto 2>&1 | tail -5
cp "$R" reviews/IMG_6848_m123.review.json
if [ -f "$B" ]; then cp "$B" "$R" && cmp "$B" "$R" && echo "review.json возвращён"; else rm "$R" && echo "review.json не было — убран"; fi
N=$(.venv/bin/python -c "import json;print(len(json.load(open('reviews/IMG_6848_m123.review.json'))['reels']))"); echo "клипов: $N"
arl render --manifest reviews/IMG_6848_m123.review.json --reels 1-$N --gate m123 --encoder hevc_videotoolbox 2>&1 | tail -8
arl review-sheet IMG_6848 --review "reviews/IMG_6848_auto_m123-scen.txt" --manifest-file reviews/IMG_6848_m123.review.json --gate m123 --preview none 2>&1 | tail -3
for f in reels-out/IMG_6848/_gate/m123/*.mp4; do printf "%s %s\n" "$(basename "$f")" "$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")"; done | tee handoff/m123/render.txt
```
Ожидается:
- `review.json возвращён` (или «не было — убран»);
- `клипов: N` — столько же, сколько сборок сценариста IMG_6848 в шаге 2;
- рендер без ошибок; лист `reels-out/IMG_6848/_gate/m123/_review.html`;
- в `render.txt` N длительностей.

## Шаг 5. Коммит фикстуры и отчёт
```bash
cd /Users/danny/Documents/autoreels
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add tests/fixtures/scenario_raw_IMG_6848.txt tests/test_scenario_recorded.py
git commit -m "Tests (M123): a recorded answer of the scenarist (Sonnet, IMG_6848) parses in the asked format"
git push; git log --oneline -1; git status --short
```
Записать `handoff/m123/REPORT.md`:
1. Коммиты шагов 1 и 5, строки pytest.
2. Из `run.txt`: по источнику — строки сценариста, `предложено сборок` обоих вариантов, цены.
3. `drafts.txt`, `why.txt`.
4. Раздел `# --- сценарист:` черновика IMG_6848 (что код не принял и почему).
5. Возврат `review.json`, `render.txt`, путь листа.

```bash
bash handoff/bin/report.sh m123 run.txt drafts.txt why.txt render.txt
```
Владельцу в чат — две строки:
- сборок у сценариста и у автосборки, покрытие клипов владельца;
- «смотреть: reels-out/IMG_6848/_gate/m123/_review.html».

Статус: IMPLEMENTED, GATE PENDING (просмотр владельцем).
