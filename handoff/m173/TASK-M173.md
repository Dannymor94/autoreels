# TASK M173 (окно MAIN, Mac): без скачков кадра + посты от «я» + сетка

Файлы — ветка `handoff`, папка `handoff/m173/`: `TASK-M173.md`, `m173-shots-posts.patch`, `measure_shots.py`, `grid.py`. Около часа: посты 86 клипов пишет Sonnet (промо-кредиты, окно до 2026-11-02).

## Зачем
Владелец 2026-10-28:
1. disko_beach_p3 r01: «нужно отталкиваться от алгоритма, чтобы таких скачков кадра не возникало». О m172: стало плавно, но на 6-й секунде один кадр «стреляет» масштабом — «бьёт по глазам».
2. «Текст постов нужно делать от „я“, так как видео публикует сам автор на своём канале». Сетка — таблица: дата (когда), что и куда, текст поста.

Патч:
- **Короткий план** (`config/r0.yaml short_shot_sec`, 0 = выкл.). План между двумя сменами картинки короче порога даёт предупреждение «short shot». Смена картинки — начало клипа, шов, вырезка, переключение общий↔крупный. Крючок и последний план не считаются.
  - Автоматический клип монтажа с коротким планом отклоняется при `--apply`. Проверка строки автомонтажа/сценариста выбрасывает фразы этого плана (тот самый обрывок 0,7 с) и проверяет строку снова.
  - Клип владельца получает только предупреждение (инвариант 5).
- **Без вспышек внутри куска.** Внутри одного куска нет общего или крупного плана короче порога: переключение сдвигается, секунды звука не меняются. Это против кадра, который «стреляет».
- **Посты от «я»** (`post.voice: author`; `reader` — как раньше). Промпт: первое лицо, род как в речи. Проверка отклоняет «автор», «спикер», «рассказчик», «он рассказывает»… и пост без «я»; затем один повтор с причиной.
- Тесты: `tests/test_m173_short_shot.py` (9), `tests/test_m174_post_voice.py` (4); правка фикстуры в `tests/test_postcopy.py`.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. `--install` и `arl auto` не запускать. `reviews/*_answer*.txt` и `manifests/` не трогать. `reviews/<S>.review.json` сохраняется и возвращается. Производственные клипы (`_gate/m163`, `_gate/m157`) не перерендеривать. Посты (`*.post.txt`) в них переписываются — это и есть задача.
3. Рендер один за раз; pytest — не во время рендера.

## Шаг 1. Патч, тесты, коммит
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m173; mkdir -p handoff/m173
git apply --check handoff/m173/m173-shots-posts.patch && git apply handoff/m173/m173-shots-posts.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests config && git commit -m "Plan (M173): no shot under short_shot_sec between two picture changes — reported, an automatic montage clip drops that shot's sentences, no wide/close flash inside a piece; posts in the author's first person (post.voice)" && git push && git log --oneline -1
```
Ожидается: `applied`. pytest: всё прошло, кроме известных пяти (`test_run_dispatch_*` ×4, `test_r0_output_parsing_survives_lower_max_tokens`) — перечислить. Коммит запушен.

## Шаг 2. Замер: короткие планы и вспышки в производственных клипах (как отрендерены)
```bash
.venv/bin/python handoff/m173/measure_shots.py reviews/{disko_beach_p1,disko_beach_p2,disko_beach_p3,day_yoga_p1,day_yoga_p2}_m163.review.json reviews/{prew_isaev_anna,prew_isaev_danny}_m157.review.json reviews/disko_beach_p3_m172.review.json > handoff/m173/before.txt
tail -1 handoff/m173/before.txt; grep -A3 "disko_beach_p3_m172" handoff/m173/before.txt | head -5
```
Ожидается: у `disko_beach_p3_m172` r01 есть `SLIVER` около out 6 с (тот кадр) или короткий план там же. Если ни того ни другого около 6 с — это в отчёт: причина вспышки не в плане, а в рендере, и патч её не лечит. Шаг не СТОП.

## Шаг 3. Черновики заново с новым кодом (без рендера) и замер после
Тот же выбор черновика, что в m172: общий, а если он не применяется или даёт другое число клипов — черновик автомонтажа.
```bash
declare -A G=([disko_beach_p1]=m163 [disko_beach_p2]=m163 [disko_beach_p3]=m163 [day_yoga_p1]=m163 [day_yoga_p2]=m163 [prew_isaev_anna]=m157 [prew_isaev_danny]=m157)
n() { .venv/bin/python -c "import json,sys;print(len(json.load(open(sys.argv[1]))['reels']))" "$1"; }
for S in "${!G[@]}"; do g=${G[$S]}; O="reviews/${S}_$g.review.json"; R="reviews/$S.review.json"; B="handoff/m173/$S.before"
  rm -f "$B"; [ -f "$R" ] && cp "$R" "$B"
  D="reviews/${S}_auto_all_$g.txt"; arl blocks --apply "$D" > "handoff/m173/apply.$S.txt" 2>&1; rc=$?
  if [ $rc != 0 ] || [ "$(n "$R")" != "$(n "$O")" ]; then D="reviews/${S}_auto_$g.txt"; arl blocks --apply "$D" > "handoff/m173/apply.$S.txt" 2>&1; rc=$?; fi
  echo "$S: $D rc=$rc"; [ $rc = 0 ] && cp "$R" "reviews/${S}_m173.review.json"
  if [ -f "$B" ]; then cp "$B" "$R"; else rm -f "$R"; fi
done 2>&1 | tee handoff/m173/apply.txt
.venv/bin/python handoff/m173/measure_shots.py reviews/*_m173.review.json > handoff/m173/after.txt; tail -1 handoff/m173/after.txt
```
Ожидается:
- `rc=0` у всех 7;
- в `after.txt` `SLIVER 0`;
- у disko_beach_p3 r01 есть строка `! short shot … whole sentences s…@780.290` (или близкое время).

Короткие планы с «inside a sentence» перечислить в отчёте (источник, клип): их автоматика не исправит выбрасыванием фразы, строка будет отклонена.

## Шаг 4. disko_beach_p3 r01 — как сделает автоматика
Автоматика выбросит обрывок 17.7. Чтобы не гнать сценариста заново, это делается рукой в копии черновика.
```bash
S=disko_beach_p3; D=$(grep -o "reviews/[^ ]*" handoff/m173/apply.txt | grep "$S" | head -1); grep -n "^M1 " "$D"
cp "$D" reviews/${S}_m173b.txt && sed -i '' -E '/^M1 /s/\| *17\.7 +18\.1-9 *\|/| 18.1-9 |/' reviews/${S}_m173b.txt && grep -n "^M1 " reviews/${S}_m173b.txt
R="reviews/$S.review.json"; B="handoff/m173/$S.before"; rm -f "$B"; [ -f "$R" ] && cp "$R" "$B"
arl blocks --apply reviews/${S}_m173b.txt --labeler auto > handoff/m173/apply.b.txt 2>&1; echo "rc=$?"; grep -E "short shot|ERROR" handoff/m173/apply.b.txt | head
cp "$R" reviews/${S}_m173b.review.json; if [ -f "$B" ]; then cp "$B" "$R"; else rm -f "$R"; fi
arl render --manifest reviews/${S}_m173b.review.json --reels 1 --gate m173 --encoder hevc_videotoolbox 2>&1 | tail -6 | tee handoff/m173/render.txt
.venv/bin/python handoff/m173/measure_shots.py reviews/${S}_m173b.review.json | head -4
```
Ожидается:
- строка `M1` после правки без `17.7`;
- у r01 нет `short shot`. `--labeler auto` может отказать из-за других строк черновика: тогда повторить без `--labeler auto` и сказать об этом;
- рендер без `[ERROR]`.

Если правка `sed` не сработала (строка `M1` другая), исправить в копии вручную: убрать из первого куска только предложение 17.7.

## Шаг 5. Посты от «я» для всех 86 клипов
```bash
for SG in "disko_beach_p1|m163" "disko_beach_p2|m163" "disko_beach_p3|m163" "day_yoga_p1|m163" "day_yoga_p2|m163" "prew_isaev_anna|m157" "prew_isaev_danny|m157"; do
  S="${SG%|*}"; g="${SG#*|}"; arl describe "$S" --gate "$g" --force --llm sonnet 2>&1 | grep -E "^describe|пропущен|не принято"
done | tee handoff/m173/describe.txt
```
Ожидается: 7 строк `describe … описаний N из N`, в сумме 86. Пропуски (`не принято`) — в отчёт с причиной: у таких клипов остаётся прежний пост в третьем лице.

## Шаг 6. Выгрузка и сетка
```bash
mkdir -p ~/.Trash/autoreels-m173/export
for SG in "disko_beach_p1|m163" "disko_beach_p2|m163" "disko_beach_p3|m163" "day_yoga_p1|m163" "day_yoga_p2|m163" "prew_isaev_anna|m157" "prew_isaev_danny|m157"; do
  S="${SG%|*}"; G="${SG#*|}"; d="reels-out/$S/_gate/$G"
  mv "export/crosspost/$S" "export/crosspost/${S}_$G.csv" ~/.Trash/autoreels-m173/export/ 2>/dev/null
  R=$(ls "$d"/r[0-9]*.mp4 | grep -v ERROR | xargs -n1 basename | sed 's/\.mp4$//' | paste -sd, -)
  arl crosspost "$S" --gate "$G" --reels "$R" 2>&1 | grep -E "клипов|пропущ"
done | tee handoff/m173/export.txt
.venv/bin/python handoff/m173/grid.py && .venv/bin/python handoff/m171/check_grid.py
cp export/crosspost/grid.csv handoff/m173/grid.csv; head -c 1500 export/crosspost/grid.csv
```
Ожидается:
- 7 строк «клипов N», в сумме 86;
- `grid.csv: 86 строк`; `в третьем лице: 0`;
- `check_grid` — OK;
- в начале `grid.csv` колонки `Дата;Время;Что;Куда;Заголовок;Текст поста`, посты от «я»; «Куда» — Telegram, VK Клипы, Instagram Reels, Дзен, MAX, YouTube Shorts (владелец 2026-10-28).

## Шаг 7. Отчёт
`handoff/m173/REPORT.md`:
- коммит, pytest;
- итоги `before.txt` и `after.txt` (строки ВСЕГО) и что у disko_beach_p3 r01 около 6 с;
- короткие планы «inside a sentence»;
- шаг 4;
- `describe.txt`, `export.txt`, вывод `grid.py`;
- три первых поста из `grid.csv` целиком.

`bash handoff/bin/report.sh m173 before.txt after.txt apply.txt render.txt describe.txt export.txt grid.csv`

Владельцу — три строки:
- «сравни reels-out/disko_beach_p3/_gate/m173/r01.mp4 с _gate/m172/r01.mp4 — скачка и вспышки на 6-й секунде нет?»;
- «вспышек (план в 1–5 кадров) было X во всех клипах, после правки 0; коротких планов Y — их исправит перепрогон автоматики»;
- «посты переписаны от „я“, сетка — export/crosspost/grid.csv».

Статус: IMPLEMENTED, GATE PENDING.
