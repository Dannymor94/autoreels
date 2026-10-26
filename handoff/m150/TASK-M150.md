# TASK M150 v2 (окно MAIN, Mac): «переделать» r06 PXL и IMG_6848 — разметка в текущей нумерации блоков

Файлы — ветка `handoff`, папка `handoff/m150/`: `TASK-M150.md`, `endcheck.py`. Около 30 минут, до пяти клипов рендера, без платных моделей, без патча.

## Что выяснил первый проход (find.*.txt)
- **PXL r06**, 862.58–903.51, `open_thought=True`. Начинается на «Но» (dangling start), кончается «…но именно для него это нужно было.», вплотную к следующей речи. Старый `PXL_review_answer.txt` к текущему манифесту не применяется: r09 — «starts mid-sentence».
- **IMG_6848 r06**, 1405.69–1441.33, `open_thought=False`. Начинается на «Но», кончается законченной фразой. Старый `img6848_answer.txt` не даёт такого клипа.

Старые файлы не годятся. Поэтому делается свежая выгрузка блоков текущего манифеста и маленькие разметки на один клип с тем же отрезком, что r06. Варианты:
- `a` — как сейчас (`s:N0 e:N1`);
- `b` — конец продлён до законченной фразы (только PXL);
- `c` — начало на одно предложение раньше, чтобы было понятно, чему возражает «Но»; у PXL — вместе с продлённым концом.

Старые файлы ответов и манифесты не трогаются, всё идёт как гейт. Выбирает владелец.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. `reviews/*_answer*.txt` не трогать (проверка `shasum -c` в конце). Манифесты только читаются. `--install`, `arl auto` не запускать. `reviews/<S>.review.json` сохраняется и возвращается.
3. Рендер один за раз.

## Шаг 1. Выгрузки и r06 манифестов
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m150; mkdir -p handoff/m150
shasum reviews/*_answer*.txt > handoff/m150/answers.sha
for S in PXL_20260729_085910095_34f06abf IMG_6848; do
  .venv/bin/python - "$S" <<'PY' | tee "handoff/m150/r06.$S.txt"
import json, sys
S = sys.argv[1]
r = {x["id"]: x for x in json.load(open(f"manifests/{S}.json"))["reels"]}["r06"]
print(f"r06 {r['start']:.2f}–{r['end']:.2f} open_thought={r.get('open_thought')}")
print(" ".join(w["word"] for w in r.get("subtitles") or []))
PY
  arl blocks "manifests/$S.json" --review --out "handoff/m150/$S.export.txt" 2>&1 | tail -1
  head -3 "handoff/m150/$S.export.txt"
done
```
Ожидается: в `r06.*.txt` отрезки 862–903 и 1405–1441 и текст клипов. Выгрузки начинаются со строк `# source:` и `# fingerprint:`.

## Шаг 2. Разметки на один клип
По тексту `r06.$S.txt` найти в выгрузке блок или блоки, покрывающие отрезок r06. Нумерация предложений сквозная через склейку (R0_SPEC §11). Определить:
- `N0` — первое предложение r06, обычно на «Но»;
- `N1` — последнее предложение r06.

Каждая разметка — копия выгрузки. Оценка `5` стоит только на блоке r06; если r06 захватывает соседний блок — склейка `+`, или `-`, если нужен предыдущий блок для `c`. Все остальные строки оценок пустые, как в выгрузке. Меняются только поля:

| файл | поля |
|---|---|
| `reviews/<S>_m150a.txt` | `s:N0 e:N1` |
| `reviews/<S>_m150b.txt` (только PXL) | `s:N0 e:N2` |
| `reviews/<S>_m150c.txt` | PXL: `s:N0-1 e:N2`; IMG: `s:N0-1 e:N1` |

Здесь `N2` — `N1+1`. Если `[N1+1]` помечено `…→` или не кончается на `.`, `!`, `?`, то `N2` = `N1+2`. Дальше не продлевать: тогда написать «нет законченной фразы в пределах двух», `b` не делать, у `c` оставить `e:N1`.

Если `[N0-1]` сам начинается на «Но / И / А / То есть / Это / Вот», `c` не делать и записать это.

```bash
for S in PXL_20260729_085910095_34f06abf IMG_6848; do
  R="reviews/$S.review.json"; B="handoff/m150/$S.review.json.before"; rm -f "$B"; [ -f "$R" ] && cp "$R" "$B"
  for V in a b c; do
    [ -f "reviews/${S}_m150$V.txt" ] || continue
    arl blocks --apply "reviews/${S}_m150$V.txt" > "handoff/m150/apply.$S.$V.txt" 2>&1; rc=$?; echo "$S $V rc=$rc"
    rm -f "reviews/${S}_m150$V.review.json"; [ $rc = 0 ] && cp "$R" "reviews/${S}_m150$V.review.json"
  done
  if [ -f "$B" ]; then cp "$B" "$R" && cmp "$B" "$R" && echo "review.json возвращён"; else rm -f "$R" && echo "review.json не было — убран"; fi
  for V in b c; do
    [ -f "reviews/${S}_m150$V.review.json" ] && .venv/bin/python handoff/m150/endcheck.py "reviews/${S}_m150a.review.json" "reviews/${S}_m150$V.review.json" r01 > "handoff/m150/end.$S.$V.txt" && cat "handoff/m150/end.$S.$V.txt"
  done
  grep -c "\[ERROR\]" handoff/m150/apply.$S.*.txt
done
```
Ожидается:
- `rc=0` у `a` и, по возможности, у остальных; «review.json возвращён» дважды; `[ERROR]` — 0.
- У `a` начало и конец около r06 манифеста.
- У PXL `b` — `open_thought` False/None и строка «добавлено: …».
- У `c` начало раньше. `endcheck` покажет «начало или середина тоже изменились» — так и должно быть.

Ошибка `--apply` у `b` или `c` — не СТОП: текст ошибки в отчёт, этот вариант не рендерить. Ошибка у `a` — СТОП.

## Шаг 3. Рендер
```bash
for S in PXL_20260729_085910095_34f06abf IMG_6848; do
  for V in a b c; do
    [ -f "reviews/${S}_m150$V.review.json" ] || continue
    arl render --manifest "reviews/${S}_m150$V.review.json" --reels r01 --gate m150$V --encoder hevc_videotoolbox 2>&1 | tail -1
  done
done
ls reels-out/*/_gate/m150?/r*.mp4 | tee handoff/m150/clips.txt
shasum -c -q handoff/m150/answers.sha && echo "оригиналы не тронуты"
```
Ожидается: по клипу на каждый вариант, без `[ERROR]`; «оригиналы не тронуты».

## Шаг 4. Отчёт
`handoff/m150/REPORT.md`: по источнику — блоки, `N0`/`N1`/`N2`, тексты добавленных предложений (`[N2]`, `[N0-1]`), `end.*.txt`, `clips.txt`.
`bash handoff/bin/report.sh m150 r06.*.txt end.*.txt clips.txt`
Владельцу — по строке на источник: «r06 <источник>: a — как сейчас, b — + “…” в конце, c — + “…” в начале; reels-out/<S>/_gate/m150a|b|c — скажи букву».

Статус: IMPLEMENTED, GATE PENDING.
