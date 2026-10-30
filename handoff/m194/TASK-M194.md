# TASK M194 (окно MAIN, Mac): крючок из другого места — субтитры по порядку проигрывания; замер «шва внутри слова»; .gitignore

Файлы — ветка `handoff`, папка `handoff/m194/`:
- `TASK-M194.md`;
- `m194-plan-fixes.patch` — код и тест; патч написан и прогнан ассистентом;
- `diag_seam.py` — замер.

Около 20 минут. Рендер — один клип на Mac. LLM нет. Отчёт — только на русском.

## Зачем
На эталонной разметке m191 нашлись три сбоя плана и рендера:

1. **Крючок из другого места** (`prew_isaev_danny` M6, `h:37.2` после тела клипа): `--apply` отказал: «last subtitle 'силу».' != planned last word 'идти.'».
   - **Причина найдена и воспроизведена тестом.** Слова холодного старта сортировались по времени исходника. Крючок звучит в исходнике позже тела, поэтому его слова уходили в конец субтитров, хотя играет он первым.
   - **Исправление** (`cloud/plan.py`): если холодный старт лежит вне отрезка тела, субтитры идут по порядку проигрывания, как у перестановки (M59). Крючок внутри тела — как раньше.
   - Тест — `tests/test_m194_plan_fixes.py`.
2. **«Шов внутри слова»** (`disko_beach_p1` M4: «cut at 1019.252s splits 'сталкивания'»). Причина без данных не видна: окно режется посреди фразы 22.13, а не на её краю. Здесь только **замер** — что говорят Whisper, выравнивание и карта речи в этом месте. Правка — следующей задачей, по данным.
3. **«last word cut»** (`prew_isaev_danny` r01 в ab192). **Не ошибка кода.** Ручной клип кончается на слове, а по карте речи следующая речь начинается внутри этого слова, на 0,38 с раньше его конца. Выбор один из двух: сыграть кусок чужой речи или срезать слово. Инвариант 10 запрещает оба, поэтому рендер правильно отказывает. Автоматический путь такие концы уже переносит на фразу раньше (M167). Ручной клип размечается иначе. Здесь ничего не делаем.

Плюс `.gitignore`: `manifests/*.blocks.json`. Это файлы-спутники `arl blocks`: пишутся на каждом прогоне и никем не читаются. Старые файлы, уже лежащие в git, остаются.

Ассистент прогнал весь набор тестов: 2599 прошли. 9 упавших требуют ffmpeg или praat — их нет в его окружении, на Mac они проходят.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить.
2. Перед стартом не должно идти других `arl` и рендера: `pgrep -fl "autoreels|ffmpeg"`.
3. **НЕ МЕНЯТЬ** ничего, кроме того, что вносит патч. `config/` не трогать, в том числе `answer_start` — его включает владелец. Временные файлы — только в `handoff/m194/`. Рендер — только в гейт `m194`. Без `--install`.
4. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.
5. Итог — «IMPLEMENTED, MEASURED». Гейт не объявлять.

## Часть 0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m194; bash handoff/bin/take.sh m191 >/dev/null
```
Ожидается: ветка `main`, рабочая копия чистая (кроме `handoff/` и untracked `manifests/*.blocks.json`), последний коммит — M193 (`9333af5`) или новее.

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git apply --check handoff/m194/m194-plan-fixes.patch && git apply handoff/m194/m194-plan-fixes.patch && echo applied
.venv/bin/python -m pytest tests/test_m194_plan_fixes.py -q 2>&1 | tail -2
.venv/bin/python -m pytest -q 2>&1 | tail -2
git status -sb | head -6
git add .gitignore src/autoreels/cloud/plan.py tests/test_m194_plan_fixes.py
git commit -m "Plan (M194): a cold open from outside the body comes first in the subtitles too (play order) — m191 h:37.2 after the body was refused «last subtitle != planned last word»; .gitignore manifests/*.blocks.json"
git push; git log --oneline -1
```
Ожидается:
- `applied`;
- 1 passed;
- весь набор — прежнее число прошедших плюс 1, упавших нет;
- `git status` больше не показывает `manifests/*.blocks.json`;
- коммит запушен.

## Часть 2. Проверка на настоящем клипе (M6 эталона `prew_isaev_danny`)
**Зачем:** строка, которую в m191 пришлось закомментировать, теперь должна примениться и отрендериться.
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
mkdir -p handoff/m194/bak; touch handoff/m194/.t0; sleep 1
for g in reviews/prew_isaev_danny.review*; do [ -e "$g" ] && cp -p "$g" handoff/m194/bak/; done
{ head -5 handoff/m191/prew_isaev_danny_ref191.txt; grep '^M6 ' handoff/m191/prew_isaev_danny_ref191.txt | sed 's/^M6 /M1 /'; } > handoff/m194/danny_m6.txt
cat handoff/m194/danny_m6.txt | tail -1
arl blocks --apply handoff/m194/danny_m6.txt > handoff/m194/apply_m6.txt 2>&1; echo "код $?"
grep -E '^manifest →|\[ERROR\]|last subtitle' handoff/m194/apply_m6.txt
mv reviews/prew_isaev_danny.review.json reviews/prew_isaev_danny_m194.review.json
find reviews -maxdepth 1 -name "prew_isaev_danny.review.*" -newer handoff/m194/.t0 -type f | while read -r g; do mv "$g" "${g/.review./_m194.review.}"; done
for g in handoff/m194/bak/*; do [ -e "$g" ] && cp -p "$g" reviews/; done
arl render --manifest reviews/prew_isaev_danny_m194.review.json --gate m194 --reels 1 --encoder hevc_videotoolbox 2>&1 | tail -5
ls -la reels-out/prew_isaev_danny/_gate/m194/
.venv/bin/python -c "
import json; r=json.load(open('reviews/prew_isaev_danny_m194.review.json'))['reels'][0]
s=[w['word'] for w in r['subtitles']]; print('субтитры:', ' '.join(s[:8]), '…', ' '.join(s[-4:]))"
find reviews manifests -newer handoff/m194/.t0 -type f | sort
```
Ожидается:
- `код 0` и строка `manifest → … (1 reels …)`; нет `[ERROR]` про последний субтитр;
- `r01.mp4` в `_gate/m194/` (не `.ERROR.mp4`);
- субтитры начинаются словами крючка («Ты не поломан…») и кончаются последним словом тела («…идти.»);
- изменено только `reviews/prew_isaev_danny_m194.review*`.

## Часть 3. Замер «шва внутри слова» (`disko_beach_p1` M4 эталона)
**Зачем:** увидеть, какой источник времени расходится в месте разреза.
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
touch handoff/m194/.t1; sleep 1
for g in reviews/disko_beach_p1.review*; do [ -e "$g" ] && cp -p "$g" handoff/m194/bak/; done
{ head -5 handoff/m191/disko_beach_p1_ref191.txt; grep -E '^(#! )?M4 ' handoff/m191/disko_beach_p1_ref191.txt | sed -E 's/^(#! )?M4 /M1 /; s/  ← apply:.*$//'; } > handoff/m194/p1_m4.txt
tail -1 handoff/m194/p1_m4.txt
arl blocks --apply handoff/m194/p1_m4.txt > handoff/m194/apply_m4.txt 2>&1; echo "код $?"
grep -nE 'seam inside word|\[ERROR\]|window|cold open|hook' handoff/m194/apply_m4.txt | head -20
find reviews -maxdepth 1 -name "disko_beach_p1.review*" -newer handoff/m194/.t1 -type f -delete
for g in handoff/m194/bak/disko_beach_p1.review*; do [ -e "$g" ] && cp -p "$g" reviews/; done
.venv/bin/python handoff/m194/diag_seam.py disko_beach_p1 1012 1027 2>&1 | tee handoff/m194/diag_seam.txt
find reviews manifests -newer handoff/m194/.t1 -type f | sort
```
Ожидается:
- `apply_m4.txt` воспроизводит отказ: `[ERROR] r01: seam inside word — cut at …s splits '…' [a, b] (window k)`. Строку `[ERROR]` выписать в отчёт **целиком**, вместе с номером окна;
- `diag_seam.txt`: слова 1012–1027 с четырьмя временами каждое, речь без текста, интервалы энергии;
- в `reviews/` ничего не осталось изменённым.

Не воспроизвелось (`код 0`) — не СТОП: написать в отчёте и всё равно выполнить `diag_seam.py`.

## Отчёт
`handoff/m194/REPORT.md`:
```
M194 — IMPLEMENTED, MEASURED
Коммит: <хэш>; pytest: N passed (было M), test_m194: 1 passed; .gitignore: blocks.json больше не в git status — да/нет
Часть 2 (M6 danny): apply код <к>; рендер r01.mp4 — да/нет (ERROR: …); субтитры: «первые слова … последние слова»
Часть 3 (M4 p1): <строка [ERROR] целиком> | не воспроизвелось
Пропущено/не совпало: …
```
```bash
bash handoff/bin/report.sh m194 apply_m6.txt apply_m4.txt diag_seam.txt danny_m6.txt p1_m4.txt
```
Владельцу в чат — 2 строки:
1. статус;
2. «крючок из другого места: клип собрался и отрендерился — да/нет; шов внутри слова: данные у ассистента».
