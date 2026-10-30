# TASK M196 (окно MAIN, Mac): `answer_start` включён; полный прогон `arl auto` в гейт m196; сравнение с m183

Файлы — ветка `handoff`, папка `handoff/m196/`:
- `TASK-M196.md`;
- `m196-answer-start-on.patch` — `config/r0.yaml` и тест; патч прогнан ассистентом;
- `export_diff.py` — тексты изменившихся клипов для слепых судей.

Рендер всех 7 источников в фоне — как m183, на Mac. Отчёт — только на русском.

## Зачем
С m183 в коде появилось четыре правки:
- M193 `answer_start` — ролик не начинается с ответа на неуслышанный вопрос. Владелец 2026-10-30: «давай» — включаем;
- M194 — крючок из другого места: субтитры идут по порядку проигрывания;
- M195 — заглушки выравнивателя больше не дают время слову;
- M191 — линейка `--ref`.

Нужен новый прогон, чтобы увидеть, что это даёт на деле:
1. линейка M188 сравнит m196 с m183;
2. клипы, которых нет в другом гейте, ассистент отдаст тем же слепым судьям, что в m192b.

Гейт **m183 остаётся продакшном**. m196 — пробный гейт: ничего не удаляется, ничего не выгружается в crosspost, сетка не меняется.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить. Расхождение чисел — не СТОП.
2. Перед стартом не должно идти других `arl` и рендера: `pgrep -fl "autoreels|ffmpeg"`. Пока идёт рендер, pytest не запускать.
3. **НЕ МЕНЯТЬ:**
   - `src/`, `prompts/`; в `config/` — только то, что вносит патч;
   - гейт `m183` и его `reviews/*_m183*` (не трогать, не удалять, не перезаписывать);
   - `export/`.

   Без `--install`. `arl export`, `arl crosspost`, `tools/grid.py`, `tools/publish_dir.py` не запускать.
4. LLM — как в m183 (сценарист и судьи — Sonnet по `config/r0.yaml`). Цену `arl auto` печатает в конце. Больше **$4** за весь прогон — не СТОП, но написать в отчёте.
5. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.
6. Итог — «RENDERED, MEASURED». Гейт не объявлять.

## Часть 0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m196
ls -1 reviews/*_m183.review.json | wc -l; ls -d reels-out/*/_gate/m196 2>/dev/null | wc -l
```
Ожидается:
- ветка `main`, чисто (кроме `handoff/`), последний коммит — M195 (`ed2b7a0`) или новее;
- 7 файлов `_m183.review.json`;
- папок `_gate/m196` нет (0).

## Часть 1. Включить `answer_start`
```bash
cd /Users/danny/Documents/autoreels
git apply --check handoff/m196/m196-answer-start-on.patch && git apply handoff/m196/m196-answer-start-on.patch && echo applied
grep -n "answer_start:" config/r0.yaml
.venv/bin/python -m pytest tests/test_m193_answer_start.py -q 2>&1 | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -2
git add config/r0.yaml tests/test_m193_answer_start.py
git commit -m "Config (M196): autocut.answer_start on — owner 2026-10-30 after m193 (9 of 52 scenarist reels changed, 0 good starts hit)"
git push; git log --oneline -1
```
Ожидается:
- `applied`;
- `answer_start: true`;
- 5 passed;
- весь набор — прежнее число, упавших нет;
- коммит запушен.

## Часть 2. Проба без рендера: `prew_isaev_danny`
**Зачем:** перед часом рендера убедиться, что правило в `arl auto` работает: черновик собирается, заметки про ответ есть.
```bash
cd /Users/danny/Documents/autoreels
.venv/bin/python -m autoreels auto prew_isaev_danny --gate m196pre --tag m196pre --no-render > handoff/m196/pre.txt 2>&1; tail -4 handoff/m196/pre.txt
grep -c '^M' reviews/prew_isaev_danny_auto_m196pre.txt
grep -hiE "ответ" handoff/m196/pre.txt reviews/prew_isaev_danny_auto_m196pre.txt | head -10 | tee handoff/m196/pre_answer.txt
```
Ожидается:
- `✓ prew_isaev_danny: готово`;
- строк `M` больше 0;
- в `pre_answer.txt` есть строки про ответ (как в m193: «ответ, а вопроса в ролике нет» / «ответ на вопрос ведущего»). Нет ни одной — **СТОП**: правило не дошло до `arl auto`.

## Часть 3. Полный прогон в m196 (в фоне)
```bash
cd /Users/danny/Documents/autoreels
S7=(disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny)
nohup .venv/bin/python -m autoreels auto "${S7[@]}" --gate m196 --tag m196 --encoder hevc_videotoolbox > handoff/m196/auto.txt 2>&1 &
echo "pid $!"
```
Проверять раз в 10 минут, пока не появится `=== auto: итог`. Затем:
```bash
cd /Users/danny/Documents/autoreels
sed -n '/=== auto: итог/,$p' handoff/m196/auto.txt | tee handoff/m196/itog.txt
grep -hiE "цена|стоимость|\\\$[0-9]" handoff/m196/auto.txt | tail -8 | tee handoff/m196/cost.txt
ls reels-out/*/_gate/m196/*.mp4 | wc -l; ls reels-out/*/_gate/m196/*.ERROR.mp4 2>/dev/null | wc -l
.venv/bin/python tools/measure_shots.py reviews/*_m196.review.json | tail -1
```
Ожидается:
- у всех 7 источников `✓`;
- `.ERROR.mp4` — 0. Если есть — не СТОП, перечислить с причиной из `auto.txt`;
- `SLIVER 0`.

## Часть 4. Линейка и тексты для судей
```bash
cd /Users/danny/Documents/autoreels
.venv/bin/python tools/score_gate.py m196 --compare m183 2>&1 | tee handoff/m196/compare.txt
.venv/bin/python tools/score_gate.py m196 --ref m183 2>&1 | grep -A3 "эталон m183 в m196\|Эталон m183 в m196" | tee handoff/m196/overlap.txt
.venv/bin/python handoff/m196/export_diff.py 2>&1 | tee handoff/m196/export_diff.txt
.venv/bin/python -c "import json;d=json.load(open('handoff/m196/blind_texts.json'));print(len(d), sum(1 for x in d if x['text']))"
git status -sb | head -5
```
Ожидается:
- `compare.txt`: ИТОГО m196, ИТОГО m183 и разница;
- `export_diff.txt`: строка на источник и итог «для судей: N (только m183 a, только m196 b)»;
- у всех текстов клипов текст не пустой;
- `git status` чистый вне `handoff/`.

## Отчёт
`handoff/m196/REPORT.md`:
```
M196 — RENDERED, MEASURED (гейт не объявляется; продакшн — m183)
Коммит: <хэш>; pytest: N passed
Проба (pre): строк M <n>; заметки про ответ: <первые 3 строки pre_answer.txt>
Прогон: <itog.txt>; клипов <N>, ERROR <k> (<какие>); SLIVER <s>; цена: <cost.txt>
Линейка: ИТОГО m196 — <строка>; ИТОГО m183 — <строка>; разница — <строка>
Изменившиеся клипы (export_diff.txt): <итог и строки источников>
Пропущено/не совпало: …
```
```bash
bash handoff/bin/report.sh m196 pre.txt pre_answer.txt itog.txt cost.txt compare.txt overlap.txt export_diff.txt blind_texts.json blind_map.csv
```
Владельцу в чат — 3 строки:
1. статус;
2. «клипов m196: N (m183: 69), изменилось: a ушло, b новых»;
3. «тексты изменившихся у ассистента — он запускает слепых судей».
