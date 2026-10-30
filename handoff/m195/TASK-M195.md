# TASK M195 (окно MAIN, Mac): «шов внутри слова» — заглушки выравнивателя больше не дают время слову

Файлы — ветка `handoff`, папка `handoff/m195/`:
- `TASK-M195.md`;
- `m195-align-stub.patch` — код и тесты; патч написан и прогнан ассистентом;
- `stubs.py` — замер.

Около 20 минут. Рендер — один клип на Mac. LLM нет. Отчёт — только на русском.

## Зачем
Замер m194 (`handoff/m194/diag_seam.txt`) показал причину отказа `disko_beach_p1` M4 («seam inside word — cut at 1019.252s splits 'сталкивания'»).

- Выравниватель (MMS_FA) поставил «И» и «в» из фразы «И в моменте сталкивания» на 1019,29 и 1019,35 с. Это внутри «сталкивания» и на 1,3 с позже их времени у Whisper. Каждое слово длится 20 мс, при этом уверенность высокая: 0,94 и 0,89.
- Холодный старт начинается с «И» и взял его время. Поэтому окно открылось посреди «сталкивания».
- Прежнее правило M38 выбрасывает слово, стоящее не по порядку, только при почти нулевой уверенности. Эти два слова оно пропустило.

Правка в `cloud/plan.py`, функция `clean_alignment`. Если два слова стоят не по порядку и одно из них — **заглушка**, заглушка выбрасывается, а время слова берётся из карты речи, как у M38. Заглушка — слово не длиннее 45 мс, стоящее дальше 0,5 с от своего времени у Whisper, когда соседнее слово стоит на своём месте.

Остальное не меняется:
- уверенные слова нормальной длины не по порядку остаются, как раньше (случай M42 — Whisper записал фразу позже, чем она звучит);
- короткое слово на своём месте тоже остаётся.

Тесты `tests/test_m195_align_stub.py` (3 теста, первый — на настоящих числах из m194). Ассистент прогнал весь набор: 2601 тест прошёл. 9 упавших требуют ffmpeg/praat/OpenCV — их нет в его окружении, на Mac они проходят.

Готовые манифесты и уже отрендеренные клипы не меняются: правило работает только при новом `--apply` или `arl auto`.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить. Расхождение чисел в замере — не СТОП.
2. Перед стартом не должно идти других `arl` и рендера: `pgrep -fl "autoreels|ffmpeg"`.
3. **НЕ МЕНЯТЬ** ничего, кроме того, что вносит патч. `config/` не трогать. Временные файлы — только в `handoff/m195/`. Рендер — только в гейт `m195`. Без `--install`.
4. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.
5. Итог — «IMPLEMENTED, MEASURED». Гейт не объявлять.

## Часть 0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m195; bash handoff/bin/take.sh m194 >/dev/null
ls handoff/m194/p1_m4.txt
```
Ожидается: ветка `main`, чисто (кроме `handoff/`), последний коммит — M194 (`40ca97e`) или новее; файл `p1_m4.txt` есть.

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git apply --check handoff/m195/m195-align-stub.patch && git apply handoff/m195/m195-align-stub.patch && echo applied
.venv/bin/python -m pytest tests/test_m195_align_stub.py -q 2>&1 | tail -2
.venv/bin/python -m pytest -q 2>&1 | tail -2
git add src/autoreels/cloud/plan.py tests/test_m195_align_stub.py
git commit -m "Plan (M195): an aligner stub (≤45 ms, >0.5 s from its Whisper time) out of order with a word at its place is dropped — its time comes from the speech map (m194: «И», «в» put inside «сталкивания», the cold open cut the word)"
git push; git log --oneline -1
```
Ожидается:
- `applied`;
- 3 passed;
- весь набор — прежнее число прошедших плюс 3, упавших нет. Если упал `test_manual_plan.py` или другой тест эталонного плана → **СТОП**: правка изменила план эталона, это решает ассистент;
- коммит запушен.

## Часть 2. Замер: сколько слов правило выбрасывает
```bash
cd /Users/danny/Documents/autoreels
.venv/bin/python handoff/m195/stubs.py 2>&1 | tee handoff/m195/stubs.txt
```
Ожидается: строка на источник и `ИТОГО`. В `disko_beach_p1` среди новых — 1018,032 «И» и 1018,432 «в». Сколько всего — замер, не СТОП.

## Часть 3. M4 эталона `disko_beach_p1` — применить и отрендерить
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
mkdir -p handoff/m195/bak; touch handoff/m195/.t0; sleep 1
for g in reviews/disko_beach_p1.review*; do [ -e "$g" ] && cp -p "$g" handoff/m195/bak/; done
arl blocks --apply handoff/m194/p1_m4.txt > handoff/m195/apply_m4.txt 2>&1; echo "код $?"
grep -E '^manifest →|\[ERROR\]|window|cold' handoff/m195/apply_m4.txt | head -8
mv reviews/disko_beach_p1.review.json reviews/disko_beach_p1_m195.review.json
find reviews -maxdepth 1 -name "disko_beach_p1.review.*" -newer handoff/m195/.t0 -type f | while read -r g; do mv "$g" "${g/.review./_m195.review.}"; done
for g in handoff/m195/bak/*; do [ -e "$g" ] && cp -p "$g" reviews/; done
arl render --manifest reviews/disko_beach_p1_m195.review.json --gate m195 --reels 1 --encoder hevc_videotoolbox 2>&1 | tail -5
ls -la reels-out/disko_beach_p1/_gate/m195/
.venv/bin/python -c "
import json; r=json.load(open('reviews/disko_beach_p1_m195.review.json'))['reels'][0]
co=r.get('cold_open'); print('холодный старт:', co and (round(co['start'],3), round(co['end'],3)))
print('первые слова:', ' '.join(w['word'] for w in r['subtitles'][:7]))"
find reviews manifests -newer handoff/m195/.t0 -type f | sort
```
Ожидается:
- `код 0`, `manifest → … (1 reels …)`, нет `[ERROR] … seam inside word`;
- холодный старт начинается около 1018,0 с (до «И», в паузе после «другом.»), а не на 1019,25;
- первые слова субтитров: «И в моменте сталкивания ученые что делают?»;
- `r01.mp4` в `_gate/m195/`;
- изменено только `reviews/disko_beach_p1_m195.review*`.

## Отчёт
`handoff/m195/REPORT.md`:
```
M195 — IMPLEMENTED, MEASURED
Коммит: <хэш>; pytest: N passed (было M), test_m195: 3 passed
Замер (stubs.txt): <строка ИТОГО и строки источников>
M4 p1: apply код <к>; холодный старт <начало–конец>; рендер r01.mp4 — да/нет; первые слова: «…»
Пропущено/не совпало: …
```
```bash
bash handoff/bin/report.sh m195 stubs.txt apply_m4.txt
```
Владельцу в чат — 2 строки:
1. статус;
2. «шов внутри слова: клип собрался и отрендерился — да/нет; правило выбросило N слов-заглушек во всех источниках».
