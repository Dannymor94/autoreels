# TASK M125 (окно MAIN, Mac): тексты постов к роликам сценариста; рендер сценариста по Pxl 20260621 112938952

Файлы — в ветке `handoff`, папка `handoff/m125/`: только `TASK-M125.md`. Кода нет.

**После M124** (не параллельно). Около 50 минут, из них ~35 — рендер. gamebox не нужен.

## Зачем
Владелец: «нужно реализовать текст поста — публикуется видео, а под ним небольшой текст о чём это видео». Это уже есть: `arl describe` (M94) пишет `<rid>.post.txt` рядом с каждым клипом — пост из 3–5 предложений словами ролика, с хэштегами из ролика. Лист ревью показывает его в карточке, `arl crosspost` берёт его в выгрузку. Но в гейтах m122/m123 описания не запускались, поэтому на листе была только короткая подпись рендера.

Ещё владелец просит взять для проверок второй источник — Pxl 20260621 112938952. Его черновик сценариста уже есть (m123, 16 сборок).

## Правила
1. Любой шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить.
2. Перед стартом не должно идти других `arl` и рендера. pytest не запускать.
3. Не трогать:
   - `reviews/*_answer.txt`, `reviews/verdicts.jsonl`, черновики, `manifests/`;
   - `reviews/<stem>.review.json` — только копия и возврат (шаг 2).

   Новые файлы:
   - `reviews/Pxl 20260621 112938952_m125.review.json`;
   - `reels-out/Pxl 20260621 112938952/_gate/m125/`;
   - `*.post.txt` в `_gate/m123/` и `_gate/m125/`.

   `arl auto`, `arl export`, `--install` не запускать.
4. Модель описаний — Claude Sonnet (`--llm sonnet`, названа явно): у него лучше русский. Цена — порядка $0,1.
5. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.

## Шаг 1. Посты к роликам сценариста IMG_6848 (`_gate/m123`) и лист заново
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m125
git status -sb | head -1; git log --oneline -1; pgrep -fl "arl " || echo "arl не запущен"
arl describe IMG_6848 --gate m123 --llm sonnet 2>&1 | tail -6 | tee handoff/m125/describe-img.txt
arl review-sheet IMG_6848 --review reviews/IMG_6848_auto_m123-scen.txt --manifest-file reviews/IMG_6848_m123.review.json --gate m123 --preview none 2>&1 | tail -2
ls reels-out/IMG_6848/_gate/m123/*.post.txt | wc -l; head -c 600 reels-out/IMG_6848/_gate/m123/r01.post.txt
```
Ожидается:
- `.post.txt` у всех 13 клипов (или названо, у каких нет и почему);
- лист обновлён;
- текст r01 — пост о ролике.

## Шаг 2. Рендер сценариста Pxl 20260621 112938952 в `_gate/m125/`, посты, лист
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
S="Pxl 20260621 112938952"; R="reviews/$S.review.json"; B="handoff/m125/pxl.review.json.before"
rm -f "$B"; [ -f "$R" ] && cp "$R" "$B"
arl blocks --apply "reviews/${S}_auto_m123-scen.txt" --labeler auto 2>&1 | tail -5
cp "$R" "reviews/${S}_m125.review.json"
if [ -f "$B" ]; then cp "$B" "$R" && cmp "$B" "$R" && echo "review.json возвращён"; else rm "$R" && echo "review.json не было — убран"; fi
N=$(.venv/bin/python -c "import json,sys;print(len(json.load(open(sys.argv[1]))['reels']))" "reviews/${S}_m125.review.json"); echo "клипов: $N"
arl render --manifest "reviews/${S}_m125.review.json" --reels 1-$N --gate m125 --encoder hevc_videotoolbox 2>&1 | tail -8
arl describe "$S" --gate m125 --llm sonnet 2>&1 | tail -6 | tee handoff/m125/describe-pxl.txt
arl review-sheet "$S" --review "reviews/${S}_auto_m123-scen.txt" --manifest-file "reviews/${S}_m125.review.json" --gate m125 --preview none 2>&1 | tail -2
for f in "reels-out/$S/_gate/m125/"r*.mp4; do printf "%s %s\n" "$(basename "$f")" "$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")"; done | tee handoff/m125/render.txt
git status --short
```
Ожидается:
- `review.json возвращён` (или «не было — убран»);
- `клипов: N` (16 по черновику; если меньше — `--apply` назовёт причину, это не СТОП);
- рендер без ошибок;
- `.post.txt` у клипов;
- лист `reels-out/Pxl 20260621 112938952/_gate/m125/_review.html`;
- новых строк в `git status` нет.

## Шаг 3. Отчёт в ветку
Записать `handoff/m125/REPORT.md`:
1. `describe-img.txt`, `describe-pxl.txt`.
2. Текст r01.post.txt обоих источников.
3. Возврат `review.json`, число клипов, `render.txt`, пути листов.

```bash
bash handoff/bin/report.sh m125 describe-img.txt describe-pxl.txt render.txt
```
Владельцу в чат — две строки, пути листов:
- `reels-out/IMG_6848/_gate/m123/_review.html` (теперь с постами);
- `reels-out/Pxl 20260621 112938952/_gate/m125/_review.html`.

Статус: GATE PENDING (просмотр владельцем).
