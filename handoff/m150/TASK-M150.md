# TASK M150 (окно MAIN, Mac): «переделать» незаконченные мысли PXL r06 и IMG_6848 r06 — копией файла ответа

Файлы — ветка `handoff`, папка `handoff/m150/`: `TASK-M150.md`, `endcheck.py`. Выполнять **после M149** (одна задача за раз). Около 20 минут, два клипа рендера, без платных моделей, без патча.

## Зачем
У двух клипов владельца явный `e:` стоит на незаконченном предложении. Код такой конец не двигает (инвариант 10), только предупреждает (`open_thought`). Владелец 2026-10-26 об этих клипах: «переделать». Правка — продлить `e:` до предложения, которым говорящий закрывает мысль. **Оригиналы `reviews/*_answer.txt` не меняются**: правится копия `reviews/<T>_answer_m150.txt`, применяется как гейт, владелец сравнивает и решает сам (переносит правку в свой файл или на листе ревью).

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. `reviews/*_answer.txt` только читаются (проверка `shasum` в начале и в конце). `--install`, `arl auto` не запускать. `reviews/<S>.review.json` сохраняется и возвращается. Манифест `manifests/PXL_20260729_085910095_34f06abf.json` не трогать: только читается при `--apply`.
3. Рендер один за раз.

## Шаг 1. Найти файлы и строки
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m150; mkdir -p handoff/m150
ls reviews/*PXL_20260729*_answer.txt reviews/IMG_6848*_answer.txt
shasum reviews/*PXL_20260729*_answer.txt reviews/IMG_6848*_answer.txt | tee handoff/m150/answers.sha
```
Для каждого из двух файлов (`T` — имя без `_answer.txt`, `S` — стем из строки `# source:`):
```bash
A="reviews/${T}_answer.txt"; S=$(basename "$(grep -m1 '^# source:' "$A" | sed 's/^# source: *//')" .json)
R="reviews/$S.review.json"; B="handoff/m150/$S.review.json.before"; rm -f "$B"; [ -f "$R" ] && cp "$R" "$B"
arl blocks --apply "$A" > "handoff/m150/apply.$T.orig.txt" 2>&1; echo "rc=$?"; cp "$R" "reviews/${S}_m150a.review.json"
grep -n "incomplete\|open_thought" "handoff/m150/apply.$T.orig.txt" | head
```
Найти строку клипа r06. В предупреждении `e: ends on incomplete sentence ('…')` у r06 — последние четыре слова. В файле ответа есть строка оценки с `| e:N`: под ней (или в выгрузке блока) предложение `[N]` кончается этими словами. Записать номер строки файла `L` и `N`.

## Шаг 2. Копия с продлённым `e:`, применение, проверка
Копия: та же строка `L`, `e:N` → `e:N+1`. Если предложение `[N+1]` помечено `…→` или не кончается на `.`, `!`, `?`, взять `N+2`. Дальше `+2` не продлевать: тогда записать «не нашлось законченного предложения в пределах двух» и для этого файла перейти к шагу 3 без рендера. Больше ничего в копии не менять.
```bash
cp "$A" "reviews/${T}_answer_m150.txt"
# правка строки L в копии (пример для N=7 → 8): sed -i '' "${L}s/| e:7\b/| e:8/" "reviews/${T}_answer_m150.txt"
diff "$A" "reviews/${T}_answer_m150.txt"      # ровно одна изменённая строка
arl blocks --apply "reviews/${T}_answer_m150.txt" > "handoff/m150/apply.$T.m150.txt" 2>&1; echo "rc=$?"
cp "$R" "reviews/${S}_m150.review.json"
if [ -f "$B" ]; then cp "$B" "$R" && cmp "$B" "$R" && echo "review.json возвращён"; else rm -f "$R" && echo "review.json не было — убран"; fi
.venv/bin/python handoff/m150/endcheck.py "reviews/${S}_m150a.review.json" "reviews/${S}_m150.review.json" r06 | tee "handoff/m150/end.$T.txt"
grep -c "\[ERROR\]" "handoff/m150/apply.$T.m150.txt"
```
Ожидается: `diff` — одна строка; `rc=0`; «review.json возвращён»; в `end.$T.txt` у «стало» `open_thought=False` (или None), строка «добавлено: …» с законченной фразой; `[ERROR]` — 0. Если ошибка `--apply` (например, следом реплика ведущего или стык блоков) — не СТОП: записать текст ошибки, рендер этого клипа не делать.

## Шаг 3. Рендер r06 из копии
```bash
arl render --manifest "reviews/${S}_m150.review.json" --reels r06 --gate m150 --encoder hevc_videotoolbox 2>&1 | tail -3
ls "reels-out/$S/_gate/m150/"
```
Ожидается один клип без `[ERROR]`. Сравнивать владелец будет с текущим клипом `reels-out/$S/` того же номера.

## Шаг 4. Отчёт
```bash
shasum reviews/*PXL_20260729*_answer.txt reviews/IMG_6848*_answer.txt | diff handoff/m150/answers.sha - && echo "оригиналы не тронуты"
```
`handoff/m150/REPORT.md`: для каждого файла строка `L`, `e:N → e:M`, `end.$T.txt` целиком, пути клипов, «оригиналы не тронуты».
`bash handoff/bin/report.sh m150 end.*.txt`
Владельцу — по строке на клип: «r06 <источник>: добавлено “…” (+X с) — reels-out/<S>/_gate/m150/; нравится — перенеси `e:M` в свой файл ответа (строка L) или поправь на листе ревью».

Статус: IMPLEMENTED, GATE PENDING.
