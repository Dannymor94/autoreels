# TASK M150 (окно MAIN, Mac): «переделать» незаконченные мысли PXL r06 и IMG_6848 r06 — копией файла ответа

Файлы — ветка `handoff`, папка `handoff/m150/`: `TASK-M150.md`, `find_src.py`, `endcheck.py`. Выполнять **после M149b** (одна задача за раз). Около 20 минут, два клипа рендера, без платных моделей, без патча.

## Зачем
У двух клипов владельца явный `e:` стоит на незаконченном предложении. Код такой конец не двигает (инвариант 10), только предупреждает (`open_thought`). Владелец 2026-10-26 об этих клипах: «переделать». Правка — продлить `e:` до предложения, которым говорящий закрывает мысль. **Оригиналы `reviews/*_answer.txt` не меняются**: правится копия `reviews/<T>_m150.txt`, применяется как гейт, владелец сравнивает и решает сам (переносит правку в свой файл или на листе ревью).

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. `reviews/*_answer.txt` только читаются (проверка `shasum` в начале и в конце). `--install`, `arl auto` не запускать. `reviews/<S>.review.json` сохраняется и возвращается. Манифест `manifests/PXL_20260729_085910095_34f06abf.json` не трогать: только читается при `--apply`.
3. Рендер один за раз.

## Шаг 1. Найти, из какого файла установлен r06
В m149 старые файлы ответов не совпали с ручными манифестами: `PXL_review_answer.txt` к манифесту PXL — `rc=1`, `img6848_answer.txt` — 25 % совпадения. Значит, r06 мог быть установлен из другой версии разметки (рядом лежат `*_answer_2026-10-02.txt`, `*_answer_montage*.txt`, `*_review.txt`). `find_src.py` применяет каждую версию к манифесту и ищет клип, совпадающий с r06 манифеста.
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m150; mkdir -p handoff/m150
shasum reviews/*_answer*.txt | tee handoff/m150/answers.sha
.venv/bin/python handoff/m150/find_src.py "PXL_20260729_085910095_34f06abf" 'reviews/PXL_review*.txt' 'reviews/PXL_20260729*answer*.txt' 2>&1 | tee handoff/m150/find.PXL.txt
.venv/bin/python handoff/m150/find_src.py "IMG_6848" 'reviews/img6848*.txt' 'reviews/IMG_6848*answer*.txt' 2>&1 | tee handoff/m150/find.IMG.txt
```
Ожидается: первая строка — «манифест r06: …», у r06 есть предупреждение `e: ends on incomplete sentence` или `open_thought=True`. Дальше по строке на файл. Подходящий файл — тот, где `rc=0` и «r06 манифеста ↔ rNN open_thought=True». Его имя — `A`, номер клипа в нём — `RID` (обычно r06). **СТОП с обоими `find.*.txt`**, если у источника подходящего файла нет или у r06 манифеста нет предупреждения о незаконченной мысли.

Для каждого источника (`S`, `A`, `RID`; `T` — имя `A` без `.txt`):
```bash
R="reviews/$S.review.json"; B="handoff/m150/$S.review.json.before"; rm -f "$B"; [ -f "$R" ] && cp "$R" "$B"
arl blocks "manifests/$S.json" --apply "$A" > "handoff/m150/apply.$T.orig.txt" 2>&1; echo "rc=$?"; cp "$R" "reviews/${S}_m150a.review.json"
grep -n "incomplete\|open_thought" "handoff/m150/apply.$T.orig.txt" | head
```
Найти строку клипа `RID`. В его предупреждении `e: ends on incomplete sentence ('…')` — последние четыре слова. В файле `A` есть строка оценки с `| e:N`, и предложение `[N]` под ней (или в выгрузке блока) кончается этими словами. Записать номер строки файла `L` и `N`.

## Шаг 2. Копия с продлённым `e:`, применение, проверка
Копия: та же строка `L`, `e:N` → `e:N+1`. Если предложение `[N+1]` помечено `…→` или не кончается на `.`, `!`, `?`, взять `N+2`. Дальше `+2` не продлевать: тогда записать «не нашлось законченного предложения в пределах двух» и для этого файла перейти к шагу 3 без рендера. Больше ничего в копии не менять.
```bash
cp "$A" "reviews/${T}_m150.txt"
L=…; N=…; M=…   # строка файла, было e:N, стало e:M
.venv/bin/python - "reviews/${T}_m150.txt" "$L" "$N" "$M" <<'PY'
import re, sys
f, L, N, M = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
ls = open(f, encoding="utf-8").read().split("\n")
new = re.sub(rf"(\|\s*e:){N}(?!\d)", rf"\g<1>{M}", ls[L - 1], count=1)
assert new != ls[L - 1], f"в строке {L} нет e:{N}"
ls[L - 1] = new; open(f, "w", encoding="utf-8").write("\n".join(ls))
PY
diff "$A" "reviews/${T}_m150.txt"      # ровно одна изменённая строка
arl blocks "manifests/$S.json" --apply "reviews/${T}_m150.txt" > "handoff/m150/apply.$T.m150.txt" 2>&1; echo "rc=$?"
cp "$R" "reviews/${S}_m150.review.json"
if [ -f "$B" ]; then cp "$B" "$R" && cmp "$B" "$R" && echo "review.json возвращён"; else rm -f "$R" && echo "review.json не было — убран"; fi
.venv/bin/python handoff/m150/endcheck.py "reviews/${S}_m150a.review.json" "reviews/${S}_m150.review.json" "$RID" | tee "handoff/m150/end.$T.txt"
grep -c "\[ERROR\]" "handoff/m150/apply.$T.m150.txt"
```
Ожидается: `diff` — одна строка; `rc=0`; «review.json возвращён»; в `end.$T.txt` у «стало» `open_thought=False` (или None), строка «добавлено: …» с законченной фразой; `[ERROR]` — 0. Если ошибка `--apply` (например, следом реплика ведущего или стык блоков) — не СТОП: записать текст ошибки, рендер этого клипа не делать.

## Шаг 3. Рендер r06 из копии
```bash
arl render --manifest "reviews/${S}_m150.review.json" --reels "$RID" --gate m150 --encoder hevc_videotoolbox 2>&1 | tail -3
ls "reels-out/$S/_gate/m150/"
```
Ожидается один клип без `[ERROR]`. Сравнивать владелец будет с текущим клипом `reels-out/$S/` того же номера.

## Шаг 4. Отчёт
```bash
shasum -c -q handoff/m150/answers.sha && echo "оригиналы не тронуты"
```
`handoff/m150/REPORT.md`: для каждого файла строка `L`, `e:N → e:M`, `end.$T.txt` целиком, пути клипов, «оригиналы не тронуты».
`bash handoff/bin/report.sh m150 end.*.txt`
Владельцу — по строке на клип: «r06 <источник>: добавлено “…” (+X с) — reels-out/<S>/_gate/m150/; нравится — перенеси `e:M` в свой файл ответа (строка L) или поправь на листе ревью».

Статус: IMPLEMENTED, GATE PENDING.
