# TASK M197 (окно MAIN, Mac): начало со слова-ответа — ролик начинается со следующей фразы; пересобрать 2 источника в m196

Файлы — ветка `handoff`, папка `handoff/m197/`:
- `TASK-M197.md`;
- `m197-answer-later.patch` — код и тест; патч написан и прогнан ассистентом.

Около 30 минут. Рендер — 2 источника на Mac. Отчёт — только на русском.

## Зачем
В m196 правило `answer_start` убрало целиком два хороших ролика сценариста:
- `prew_isaev_anna` r04 — «Да, если брать восстановление… Как ты отдыхаешь? — А я и не работаю…»;
- `day_yoga_p2` r05 — «Да, возможно, это совсем другая работа. Смотрите, прежде чем искать другую работу…».

Правило умело только начинать раньше, а перед этими фразами стоит вопрос ведущего или фраза, которая тоже не держит начало.

Правка в `cloud/scenario.py`: если ролик открывается **словом-ответом** («Да, …», «Нет.», «Конечно, …»), сначала пробуется начало со следующей фразы. Условия: следующая фраза сама держит начало (те же проверки `start_strict` + `answer_start`), и ролик не короче `min_sec`. Не вышло — как раньше: начать раньше, иначе ролик уходит. Отрезать фразу с начала разрешено только при слове-ответе. Остальное не меняется: владелец запретил отрезать начало (M77, `context_later`).

Тест — в `tests/test_m193_answer_start.py`. Прежний тест M193 поправлен так, чтобы его следующая фраза ссылалась назад и проверялся путь «раньше». Ассистент прогнал весь набор: 2603 прошли. 9 упавших требуют ffmpeg/praat/OpenCV, у ассистента их нет.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить. Расхождение чисел — не СТОП.
2. Перед стартом не должно идти других `arl` и рендера: `pgrep -fl "autoreels|ffmpeg"`. Пока идёт рендер, pytest не запускать.
3. **НЕ МЕНЯТЬ** ничего, кроме того, что вносит патч. Гейт `m183` и его `reviews/*_m183*` не трогать. Пересобираются только два источника, в пробный гейт `m196`. Без `--install`, без `arl export` / `arl crosspost` / сетки.
4. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.
5. Итог — «RENDERED, MEASURED». Гейт не объявлять.

## Часть 0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m197; bash handoff/bin/take.sh m196 >/dev/null
ls -1 reviews/prew_isaev_anna_m196.review.json reviews/day_yoga_p2_m196.review.json
```
Ожидается: ветка `main`, чисто (кроме `handoff/`), последний коммит — M196 (`b03bf80`) или новее; оба файла есть.

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git apply --check handoff/m197/m197-answer-later.patch && git apply handoff/m197/m197-answer-later.patch && echo applied
.venv/bin/python -m pytest tests/test_m193_answer_start.py -q 2>&1 | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -2
git add src/autoreels/cloud/scenario.py tests/test_m193_answer_start.py
git commit -m "Starts (M197): a scenarist reel opening on an answer word starts one sentence later when that sentence stands (m196: «Да, если брать восстановление… Как ты отдыхаешь?» went whole); else earlier, else none — as before"
git push; git log --oneline -1
```
Ожидается: `applied`; 6 passed; весь набор — прежнее число плюс 1, упавших нет; коммит запушен.

## Часть 2. Пересобрать 2 источника в m196
```bash
cd /Users/danny/Documents/autoreels
.venv/bin/python -m autoreels auto prew_isaev_anna day_yoga_p2 --gate m196 --tag m196 --encoder hevc_videotoolbox > handoff/m197/auto.txt 2>&1; echo "код $?"
sed -n '/=== auto: итог/,$p' handoff/m197/auto.txt
grep -h "следующей фразы" reviews/prew_isaev_anna_auto_m196.txt reviews/day_yoga_p2_auto_m196.txt | tee handoff/m197/later.txt
grep -hiE "цена|\\\$[0-9]" handoff/m197/auto.txt | tail -3
ls reels-out/prew_isaev_anna/_gate/m196/*.mp4 reels-out/day_yoga_p2/_gate/m196/*.mp4 | wc -l
ls reels-out/{prew_isaev_anna,day_yoga_p2}/_gate/m196/*.ERROR.mp4 2>/dev/null | wc -l
```
Ожидается:
- оба `✓`;
- в `later.txt` — 2 строки: «Да, если брать восстановление…» и «Да, возможно, это совсем другая работа.» с пометкой «убрано, ролик начинается со следующей фразы»;
- `.ERROR.mp4` — 0.

## Часть 3. Сверка с m183
```bash
cd /Users/danny/Documents/autoreels
rm -f reels-out/_score/m196.json
.venv/bin/python tools/score_gate.py m196 --compare m183 2>&1 | tail -6 | tee handoff/m197/compare.txt
.venv/bin/python handoff/m196/export_diff.py 2>&1 | tee handoff/m197/export_diff.txt
.venv/bin/python - <<'EOF' 2>&1 | tee handoff/m197/starts.txt
import json
for s in ("prew_isaev_anna", "day_yoga_p2"):
    for r in json.load(open(f"reviews/{s}_m196.review.json"))["reels"]:
        words = [w["word"] for w in r["subtitles"]]
        print(f"{s} {r['id']} «{r.get('title_overlay','')[:40]}»: {' '.join(words[:10])}")
EOF
git status -sb | head -5
```
Ожидается:
- `export_diff.txt`: «только m183» = 0 у обоих источников (оба ролика вернулись);
- в `starts.txt` есть ролик, начинающийся «Как ты отдыхаешь?», и ролик, начинающийся «Но смотрите, прежде чем…» или «Смотрите, прежде чем…».

`blind_texts.json` и `blind_map.csv` в `handoff/m196/` перепишутся — это ожидаемо.

## Отчёт
`handoff/m197/REPORT.md`:
```
M197 — RENDERED, MEASURED (продакшн — m183)
Коммит: <хэш>; pytest: N passed
Пересборка: <итог auto.txt>; цена <…>; ERROR <k>
Сдвинутые начала (later.txt): <строки>
m196 против m183: <export_diff итог>; ИТОГО m196 — <строка>
Начала двух роликов: <строки из starts.txt>
Пропущено/не совпало: …
```
```bash
bash handoff/bin/report.sh m197 auto.txt later.txt compare.txt export_diff.txt starts.txt
```
Владельцу в чат — 2 строки:
1. статус;
2. «оба ролика вернулись: „Как ты отдыхаешь?…“ и „…прежде чем искать другую работу“ — да/нет; m196: N клипов».
