# TASK M199 (окно MAIN, Mac): четыре проверки клипа — только замер на m196, m183, эталоне и ab192

Файлы — ветка `handoff`, папка `handoff/m199/`:
- `TASK-M199.md`;
- `m199-clipcheck.patch` — новый модуль, скрипт, тесты, необязательная зависимость; патч написан и прогнан ассистентом.

Около 15 минут. Без рендера, без LLM. Отчёт — только на русском.

## Зачем
Владелец 2026-10-30: «берём 1–4 по алгоритму». Это четыре недостатка, которые слепые судьи m192b назвали у автоматики. Сначала **только замер**: сколько клипов задевает каждая проверка и совпадает ли это с оценками судей. Включать как правило будем то, что ловит плохое и не трогает хорошее.

1. **Крючок обрывается** — холодный старт кончается предлогом, союзом, частицей или местоимением: «…свою силу, Вы».
2. **Плашка мимо клипа** — доля предложений клипа со словами плашки; есть ли эти слова в начале или выводе.
3. **Начало без опоры** (морфология `pymorphy3`):
   - первая фраза — глагол без подлежащего: «Всем говорит…», «Как было, так и было»;
   - или местоимение 3-го лица идёт раньше любого существительного: «Он надевает маски…».

   Безличные конструкции («Было интересно», «Бывает, что…») и вопросы правило пропускает.
4. **Стык из разных мыслей** — у соседних кусков сборки нет ни одного общего содержательного слова.

Код:
- `src/autoreels/cloud/clipcheck.py` — чистые функции. Сборка их **не вызывает**, выход конвейера не меняется;
- `tools/clip_checks.py <гейт>` — таблица и `reels-out/_score/<гейт>_checks.json`;
- тесты `tests/test_m199_clipcheck.py` — 5 тестов;
- зависимость `pymorphy3` — необязательная группа `.[nlp]` в `pyproject.toml`. Ставим её по решению владельца.

Ассистент прогнал весь набор: 2633 прошли. Упали 10, все из-за окружения:
- 9 требуют ffmpeg, praat или OpenCV;
- 1 — снимок OpenAPI: у ассистента другая версия FastAPI.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить. Расхождение чисел в замере — не СТОП.
2. Перед стартом не должно идти других `arl` и рендера: `pgrep -fl "autoreels|ffmpeg"`.
3. **НЕ МЕНЯТЬ:** ничего, кроме того, что вносит патч. `config/` не трогать. Ставится только `pymorphy3` (часть 1).
4. Итог — «IMPLEMENTED (только замер), MEASURED». Гейт не объявлять.

## Часть 0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m199
ls -1 reviews/*_m196.review.json reviews/*_m183.review.json reviews/*_ref191.review.json reviews/*_ab192.review.json | wc -l
```
Ожидается:
- ветка `main`, чисто (кроме `handoff/`), последний коммит — M198 (`5f5455c`) или новее;
- 27 файлов: 7 + 7 + 7 + 6.

## Часть 1. Патч, зависимость, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git apply --check handoff/m199/m199-clipcheck.patch && git apply handoff/m199/m199-clipcheck.patch && echo applied
.venv/bin/pip install -e ".[nlp]" 2>&1 | tail -1
.venv/bin/python -c "import pymorphy3; print('pymorphy3', pymorphy3.__version__)"
.venv/bin/python -m pytest tests/test_m199_clipcheck.py -q 2>&1 | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -2
git add pyproject.toml src/autoreels/cloud/clipcheck.py tools/clip_checks.py tests/test_m199_clipcheck.py
git commit -m "Clip checks (M199): cloud/clipcheck + tools/clip_checks.py — cold open cut off, plate words, a start with nothing to stand on (pymorphy3, extra .[nlp]), seams of unrelated pieces; measurement only"
git push; git log --oneline -1
```
Ожидается:
- `applied`;
- `pymorphy3 2.x`;
- 5 passed (`test_start_morph` не пропущен);
- весь набор: прежнее число прошедших плюс 5, упавших нет;
- коммит запушен.

## Часть 2. Замер на четырёх гейтах
```bash
cd /Users/danny/Documents/autoreels
for G in m196 m183 ref191 ab192; do
  echo "=========== $G"
  .venv/bin/python tools/clip_checks.py "$G" 2>&1 | tee "handoff/m199/checks_$G.txt"
  cp "reels-out/_score/${G}_checks.json" "handoff/m199/"
done
git status -sb | head -4
```
Ожидается:
- по каждому гейту: строка «морфология: pymorphy3», четыре строки итогов и до 12 примеров на проверку;
- четыре файла `handoff/m199/<гейт>_checks.json`;
- `git status` чистый вне `handoff/`.

## Отчёт
`handoff/m199/REPORT.md`:
```
M199 — IMPLEMENTED (только замер), MEASURED
Коммит: <хэш>; pytest: N passed (было M); pymorphy3 <версия>
m196:   <4 строки итогов>
m183:   <4 строки итогов>
ref191: <4 строки итогов>
ab192:  <4 строки итогов>
Пропущено/не совпало: …
```
```bash
bash handoff/bin/report.sh m199 checks_m196.txt checks_m183.txt checks_ref191.txt checks_ab192.txt m196_checks.json m183_checks.json ref191_checks.json ab192_checks.json
```
Владельцу в чат — 2 строки:
1. статус;
2. «замер у ассистента — он сверит с оценками судей и скажет, какие проверки включать».
