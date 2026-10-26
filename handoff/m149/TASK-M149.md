# TASK M149 (окно MAIN, Mac): карта речи на всех источниках и флаг `speech_map`

Файлы — ветка `handoff`, папка `handoff/m149/`: `TASK-M149.md`, `smap_ab.py`. Выполнять **после M148**. Около 40 минут, без платных моделей, без патча.

## Зачем
План клипа (M1.7) берёт паузы и концы слов из карты речи `transcripts/<stem>.speechmap.json`, если она построена. Нет карты — берёт зазоры Whisper, а они бывают нулевые и перекрытые (инвариант 9). Флаг `render.yaml speech_map` (сейчас выключен) строит карту сам при `--apply` и рендере. Ещё он включает её для авторитма планов и тактов. Итоговый просмотр M1.8 владелец закрыл. Задача: построить карту всем источникам. Затем на всех файлах ответов владельца проверить, что флаг не добавляет ошибок, и по правилу включить его.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. `reviews/*_answer.txt` только читаются, `--install` и `arl auto` не запускать. `reviews/<S>.review.json` сохраняется до применения и возвращается после (как в m136). `manifests/` не меняется: проверка в конце шага 2.
3. `config/render.yaml` правится только командами задачи: во время замера возвращается `git checkout`, коммитится только по правилу шага 3.
4. pytest только в шаге 3. Рендер один за раз, во время рендера pytest не запускать.

## Шаг 1. Состояние «before» — как сейчас
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m149; mkdir -p handoff/m149
git status --short manifests/ > handoff/m149/manifests.before
grep -n '^speech_map:' config/render.yaml
.venv/bin/python handoff/m149/pairs.py 2>&1 | tee handoff/m149/pairs.log | grep -v "^  "
while IFS=$'\t' read -r T S; do
  echo "$T → $S; карта: $([ -f "transcripts/$S.speechmap.json" ] && echo есть || echo нет)"
done < handoff/m149/pairs.txt | tee handoff/m149/maps.before.txt
ab() {  # ab <state>: применить все файлы ответов, сохранить копии review.json
  while IFS=$'\t' read -r T S; do
    R="reviews/$S.review.json"; B="handoff/m149/$S.review.json.before"; rm -f "$B"; [ -f "$R" ] && cp "$R" "$B"
    arl blocks "manifests/$S.json" --apply "reviews/${T}_answer.txt" > "handoff/m149/apply.$1.$T.txt" 2>&1; rc=$?; echo "$1 $T rc=$rc"
    rm -f "reviews/${S}_m149$1.review.json"; [ $rc = 0 ] && [ -f "$R" ] && cp "$R" "reviews/${S}_m149$1.review.json"
    if [ -f "$B" ]; then cp "$B" "$R" && cmp -s "$B" "$R" || echo "!! $R не возвращён"; else rm -f "$R"; fi
  done < handoff/m149/pairs.txt
}
ab before
```
Файлы ответов старого формата, без строки `# source:`. `pairs.py` подбирает манифест сам. Кандидаты берутся по имени: img6848 → IMG_6848, lec0933 → «09h 33m», PXL_review → PXL_20260729…, pxl1129 → «…112938952». Для pxl0621 пробуются оба Pxl того дня, для lecture — все лекции. Файл применяется к каждому кандидату, и выбирается тот, чьи клипы совпадают с установленным ручным манифестом: у ≥ 60 % клипов манифеста есть клип с началом ±3 с. review.json каждый раз возвращается.

Ожидается: строка `speech_map: false`. В выводе `pairs.py` — «T: → S» или «T: пары нет» на каждый из 6 файлов, затем `=== пар: K`. «Пары нет» — не СТОП: файл в замер не идёт, в отчёте назвать его и строки кандидатов из `pairs.log`. Если `pairs.py` сам завершился «!! … не возвращён» — это СТОП. Дальше по строке «T → S; карта: есть/нет» и `before T rc=…` на каждую пару. `rc≠0` — не СТОП: такой файл в сравнение идёт как есть (часто старая разметка или изменились блоки, причину называет `apply.before.T.txt`). Строк «!! … не возвращён» быть не должно.

## Шаг 2. Карта всем, затем «off» и «on»
```bash
cut -f2 handoff/m149/pairs.txt | sort -u | while read -r S; do
  arl speech-map "manifests/$S.json" > "handoff/m149/smap.$S.txt" 2>&1; echo "$S smap rc=$? $([ -f "transcripts/$S.speechmap.json" ] && echo есть || echo НЕТ)"
done | tee handoff/m149/maps.after.txt
ab off
sed -i '' 's/^speech_map: .*/speech_map: true/' config/render.yaml; grep -n '^speech_map:' config/render.yaml
ab on
git checkout config/render.yaml; git diff --stat config/
git status --short manifests/ | diff handoff/m149/manifests.before - && echo "manifests без изменений"
.venv/bin/python handoff/m149/smap_ab.py 2>&1 | tee handoff/m149/ab.txt | tail -1
cat handoff/m149/render_list.txt
```
Ожидается: у каждого источника `smap rc=0 есть`. Если источника нет на диске, будет `НЕТ`: не СТОП, источник назвать в отчёте. Дальше `speech_map: true`, `git diff --stat config/` пуст, «manifests без изменений», строка `=== ВСЕГО`.

## Шаг 3. Решение (агент применяет сам)
**Включить** `speech_map: true`, если в `ab.txt` «источников хуже 0». Это значит: где `before` применялся, `on` даёт столько же клипов и не больше ошибок apply. Тогда:
```bash
sed -i '' 's/^speech_map: .*/speech_map: true/' config/render.yaml
sed -i '' 's/^# M1.8: energy-based speech map — off by default (Stage A). Stage B consumers behind this flag./# M1.8: energy-based speech map — on since M149 (built at --apply\/render when missing; consumers in plan, beats, two-shot)./' config/render.yaml
.venv/bin/python -m pytest -q 2>&1 | tail -3
```
pytest должен пройти. Если падает тест, который ждёт выключенный флаг по умолчанию, — СТОП, `git checkout config/render.yaml`, имя теста в отчёт. Прошёл:
```bash
git add config/render.yaml && git commit -m "Render (M149): speech_map on — maps built for all sources (m149: worse 0, changed before→on N of M clips)" && git push && git log --oneline -1
```
В PLAN (раздел M1.8, строка `speech_map`) записать: «включён M149: карта у всех источников, хуже 0» + числа из `ab.txt`. Коммит `Docs (M149): speech_map on`, push.
Правило не выполнено — ничего не включать, назвать источник и причину из `apply.on.*.txt`.

## Шаг 4. Гейт для ушей (только если включено и `render_list.txt` не пуст)
Клипы с наибольшим сдвигом: «до» с выключенным флагом в `_gate/m149b`, «после» в `_gate/m149`.
```bash
while IFS=$'\t' read -r S L; do
  arl render --manifest "reviews/${S}_m149on.review.json" --reels "$L" --gate m149 --encoder hevc_videotoolbox 2>&1 | tail -2
done < handoff/m149/render_list.txt
sed -i '' 's/^speech_map: .*/speech_map: false/' config/render.yaml
while IFS=$'\t' read -r S L; do
  arl render --manifest "reviews/${S}_m149before.review.json" --reels "$L" --gate m149b --encoder hevc_videotoolbox 2>&1 | tail -2
done < handoff/m149/render_list.txt
git checkout config/render.yaml; git diff --stat config/
ls reels-out/*/_gate/m149/r*.mp4 reels-out/*/_gate/m149b/r*.mp4 | tee handoff/m149/clips.txt
```
Ожидается: рендер без `[ERROR]`, `git diff --stat config/` пуст.

## Шаг 5. Отчёт
`handoff/m149/REPORT.md`: карты before/after (сколько было, сколько построено, каких источников нет), `ab.txt` целиком, решение и коммиты, pytest, `clips.txt`.
`bash handoff/bin/report.sh m149 ab.txt maps.before.txt maps.after.txt render_list.txt clips.txt`
Владельцу — две строки:
- «карта речи у N из M источников, флаг speech_map включён / не включён (причина)»;
- «по желанию: сравнить reels-out/<источник>/_gate/m149b (до) и _gate/m149 (после) — концы и паузы».

Статус: IMPLEMENTED, GATE PENDING.
