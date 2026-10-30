# TASK M200 (окно MAIN, Mac): начало без опоры — правило `start_morph` (выключено); слово-ответ за «ну/вот»; пробный черновик m200 без рендера

Файлы — ветка `handoff`, папка `handoff/m200/`:
- `TASK-M200.md`;
- `m200-start-morph.patch` — код и тесты; патч написан и прогнан ассистентом;
- `hooks_diag.py` — откуда «оборванные» крючки замера M199 (только чтение);
- `export_diff.py` — тексты клипов, которые есть только в m196 или только в m200, для слепых судей.

Около 30 минут, без рендера. Отчёт — только на русском.

## Зачем
Ассистент сверил замер M199 со слепыми судьями (ab192, 20 клипов) и с эталоном ref191. Итог по четырём проверкам:

1. **Крючок обрывается** — не включаем. Все 5 срабатываний (m196, m183, ref191) устроены одинаково: крючок — целая фраза, а «лишнее» слово («Просто», «Вы», «И», «Что это») — первое слово **следующей** фразы, которая идёт в теле ролика. По коду конец крючка режется до следующей речи, а субтитры крючка — только слова его фразы. Значит, слово, скорее всего, не звучит в крючке: его время в субтитрах попало внутрь окна крючка, и замер приписал его крючку. Часть 2 проверяет это по числам.
2. **Плашка мимо клипа** — не включаем. У эталона ассистента доля фраз со словами плашки даже ниже, чем у автоматики (медиана 0,18 против 0,29). Проверка срабатывает на 4 из 7 клипов, которые оба судьи оценили «ok».
3. **Начало без опоры** — включаем как правило (этот патч, под флагом). В ab192 проверка сработала на 2 клипа, и это два худших начала из 20 (оба судьи: начало 1 из 5): «Как было, так и было.» и «Всем говорит, и он стоит на этом…». Было 2 ложных срабатывания: «У папы был рак…» и в эталоне «Вдохновляет меня то, что…». Правка: подлежащим считается слово, которое **может** стоять в именительном падеже. С правкой ложных срабатываний 0, в m196 срабатываний 3.
4. **Стыки без общих слов** — не включаем. Такие стыки есть у двух клипов, которые оба судьи оценили «ok», и у 10 из 62 клипов эталона.

Ещё нашлась утечка правила `answer_start` (M193, включено). В m196 остались два начала, которые судьи оценили на 2 из 5:
- «Ну да, вот я как-то говорил…»;
- «Да, у меня даже как получается.».

Правило искало слово-ответ только первым словом. Перед «да» стоит «Ну» — или, во втором случае, видимо, «Вот,», которое скрыто в субтитрах, но есть в тексте фразы.

## Что вносит патч
- `cloud/clipcheck.py`:
  - `start_morph` ищет подлежащее во всех прочтениях слова;
  - `require_morph()` — если правило включено, а pymorphy3 нет, это явная ошибка, а не тихое выключение.
- `cloud/autocut.py`:
  - поле `AutoParams.start_morph`;
  - `answer_start_reason` пропускает «ну»/«вот» перед словом-ответом.
- `cloud/scenario.py` — при `start_strict` и `start_morph` начало без опоры обрабатывается так же, как прочие плохие начала: ролик начинается раньше (до `start_extend_max` фраз), иначе уходит. Сдвиг начала **позже** не делается (M77).
- `__main__.py` — клипы разметки в `arl auto`: начало без опоры убирает клип, как `answer_start`.
- `core/config.py`, `config/r0.yaml` — `start_morph: false`.
- `tests/test_m200_start_morph.py` — 5 тестов.

Ассистент прогнал весь набор: 2615 прошли. 7 упавших требуют ключей, ffmpeg или praat — их нет у ассистента; без патча падают те же 7.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить. Расхождение чисел — не СТОП.
2. Перед стартом не должно идти других `arl` и рендера: `pgrep -fl "autoreels|ffmpeg"`.
3. **НЕ МЕНЯТЬ:**
   - ничего, кроме того, что вносит патч;
   - `config/r0.yaml` в коммите — `start_morph: false`. В части 3 флаг включается **только на время прогона**, потом файл возвращается через `git checkout`;
   - гейты `m183`, `m196` и их `reviews/*_m183*`, `reviews/*_m196*` не трогать.

   Без рендера, без `--install`. `arl export`, `arl crosspost` и сетку не запускать.
4. Итог — «IMPLEMENTED (флаг выключен), MEASURED». Флаг включает владелец по итогам замера и судей. Гейт не объявлять.

## Часть 0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m200
.venv/bin/python -c "import pymorphy3; print('pymorphy3', pymorphy3.__version__)"
ls -1 reviews/*_m196.review.json | wc -l
```
Ожидается:
- ветка `main`, чисто (кроме `handoff/`), последний коммит — M199 (`f326b67`) или новее;
- pymorphy3 печатает версию;
- 7 файлов `_m196.review.json`.

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git apply --check handoff/m200/m200-start-morph.patch && git apply handoff/m200/m200-start-morph.patch && echo applied
.venv/bin/python -m pytest tests/test_m200_start_morph.py tests/test_m199_clipcheck.py tests/test_m193_answer_start.py -q 2>&1 | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -2
git add config/r0.yaml src/autoreels/__main__.py src/autoreels/cloud/autocut.py src/autoreels/cloud/clipcheck.py src/autoreels/cloud/scenario.py src/autoreels/core/config.py tests/test_m200_start_morph.py
git commit -m "Starts (M200): autocut.start_morph (off) — with start_strict no reel opens on a verb without a subject or «он/их» before any noun (blind judges ab192: the two worst starts); a subject in any reading; answer_start finds the answer word behind «ну/вот»"
git push; git log --oneline -1
```
Ожидается:
- `applied`;
- 16 passed;
- весь набор — прежнее число плюс 5, упавших нет;
- коммит запушен.

## Часть 2. Откуда «оборванные» крючки (только чтение)
```bash
cd /Users/danny/Documents/autoreels
.venv/bin/python handoff/m200/hooks_diag.py m196 2>&1 | tee handoff/m200/hooks_diag.txt
```
Ожидается: 3 крючка. У каждого — окно крючка, лишнее слово и окно тела, в котором оно лежит. Если у какого-то «в окне тела: нет» — не СТОП, выписать в отчёт.

## Часть 3. Пробный черновик m200 без рендера (флаг включён на время прогона)
**Зачем:** увидеть, что правило и правка `answer_start` меняют в настоящем `arl auto`. Сценарист должен ответить из кэша: запрос тот же, что в m196.
```bash
cd /Users/danny/Documents/autoreels
.venv/bin/python - <<'EOF'
from pathlib import Path
p = Path("config/r0.yaml"); t = p.read_text(encoding="utf-8")
assert t.count("  start_morph: false") == 1
p.write_text(t.replace("  start_morph: false", "  start_morph: true", 1), encoding="utf-8"); print("start_morph on (на прогон)")
EOF
S7=(disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny)
.venv/bin/python -m autoreels auto "${S7[@]}" --gate m200 --tag m200 --no-render > handoff/m200/auto.txt 2>&1; echo "код $?"
git checkout config/r0.yaml; grep -n "start_morph:" config/r0.yaml
sed -n '/=== auto: итог/,$p' handoff/m200/auto.txt
grep -c "ответ из кэша" handoff/m200/auto.txt; grep -hiE "цена|\\\$[0-9]" handoff/m200/auto.txt | tail -3
grep -h "убран из черновика" handoff/m200/auto.txt | tee handoff/m200/dropped.txt
grep -hE "подлежащего|о ком|ответ" reviews/*_auto_m200.txt | tee handoff/m200/notes.txt
ls -1 reviews/*_m200.review.json | wc -l
```
Ожидается:
- после прогона `start_morph: false` (файл вернулся);
- у всех 7 источников `✓`;
- «ответ из кэша» — 7. Если меньше — не СТОП, написать цену;
- в `notes.txt` есть заметки «без подлежащего» или «о ком?» и заметки про ответ;
- 7 файлов `_m200.review.json`.

## Часть 4. Замер и тексты для судей
```bash
cd /Users/danny/Documents/autoreels
.venv/bin/python tools/clip_checks.py m200 2>&1 | head -8 | tee handoff/m200/checks_m200.txt
cp reels-out/_score/m200_checks.json handoff/m200/
.venv/bin/python handoff/m200/export_diff.py 2>&1 | tee handoff/m200/export_diff.txt
.venv/bin/python -c "import json;d=json.load(open('handoff/m200/blind_texts.json'));print(len(d), sum(1 for x in d if x['text']))"
git status -sb | head -5
```
Ожидается:
- `checks_m200.txt`: «начало без опоры: 0 из N»;
- `export_diff.txt`: строка на источник, первые слова изменившихся клипов и итог «для судей: N»;
- у всех текстов клипов текст не пустой;
- `git status` чистый вне `handoff/`.

## Отчёт
`handoff/m200/REPORT.md`:
```
M200 — IMPLEMENTED (флаг выключен), MEASURED
Коммит: <хэш>; pytest: N passed (было M); тесты M200/M199/M193: 16 passed
Крючки (hooks_diag.txt): <по каждому: слово, «в окне тела: …», на сколько раньше конца крючка>
Прогон m200: <итог auto.txt>; из кэша <k> из 7; цена <…>
Убрано из черновика (dropped.txt): <строки>
Заметки (notes.txt): <строки>
Замер m200: <строка «начало без опоры»>
m200 против m196 (export_diff.txt): <итог и строки источников>
Пропущено/не совпало: …
```
```bash
bash handoff/bin/report.sh m200 hooks_diag.txt auto.txt dropped.txt notes.txt checks_m200.txt m200_checks.json export_diff.txt blind_texts.json blind_map.csv
```
Владельцу в чат — 3 строки:
1. статус;
2. «m200: клипов N (m196: 68), изменилось: a ушло, b новых; начало без опоры 0»;
3. «тексты изменившихся у ассистента — он запускает слепых судей».
