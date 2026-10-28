# TASK M174 (окно MAIN, Mac): короткие планы внутри фразы + перепрогон всего в производство + сетка

Файлы — ветка `handoff`, папка `handoff/m174/`: `TASK-M174.md`, `m174-lengthen.patch`, `grid2.py`. Долго: перепрогон 7 источников с рендером (в фоне, около 1,5–2 ч). Сценарист берётся из кэша; посты и судьи — Sonnet из промо-кредитов, окно до 2026-11-02.

## Зачем
По m173 владелец: «вроде норм» (r01 без скачка — гейт закрывает только он). Осталось:
- **61 короткий план**, из них 53 «inside a sentence». Это вырезка паузы через секунду после шва или другой вырезки. Выбросом фразы такое не исправить: строка автоматики была бы отклонена, и клип пропал бы.
  - Патч: такой кусок удлиняется тишиной соседней вырезки. Вырезка оставляет больше паузы с короткой стороны, но не меньше `min_cut_sec`, и только тишину — ни слова, ни нерасшифрованного звука.
  - Тишины не хватает — вырезка не делается, пауза играет.
  - Кусок из целых фраз оставлен проверке строки: она выбрасывает фразы (как 17.7 в r01).
  - Вырезка слова-паразита (M126) не двигается, только снимается: слово возвращается на экран вместе со звуком.
  - `short_shot_sec: 0` = прежние вырезки (тест).
  - Тесты `tests/test_m174_lengthen_short.py` (4).
- **Перепрогон** всех 7 источников в новый гейт `m174`, чтобы правила m173/m174 вошли в производство. Старые гейты m163/m157 остаются до слова владельца.
- **Сетка заново** под новые клипы, тот же смысловой порядок (`grid2.py`). Заголовки без хэштегов: в m173 они попали из подписи рендера. Три поста, не принятые в m173, — повтор.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. `--install` не запускать. `reviews/*_answer*.txt` и `manifests/` не трогать. Гейты `m163`, `m157`, `m172`, `m173` не трогать и не удалять.
3. Рендер один за раз; pytest — не во время рендера.

## Шаг 1. Патч, тесты, коммит
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m174; mkdir -p handoff/m174
git apply --check handoff/m174/m174-lengthen.patch && git apply handoff/m174/m174-lengthen.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests && git commit -m "Plan (M174): a short piece inside a sentence takes silence from the neighbouring cut, else the cut is dropped (m173: 53 short shots inside a sentence)" && git push && git log --oneline -1
```
Ожидается: `applied`. pytest: всё прошло, кроме известных пяти (`test_run_dispatch_*` ×4, `test_r0_output_parsing_survives_lower_max_tokens`) — перечислить. Коммит запушен.

## Шаг 2. Замер до рендера: черновики m163/m157 с новым кодом
Тот же цикл, что шаг 3 m173, только в `_m174pre`:
```bash
declare -A G=([disko_beach_p1]=m163 [disko_beach_p2]=m163 [disko_beach_p3]=m163 [day_yoga_p1]=m163 [day_yoga_p2]=m163 [prew_isaev_anna]=m157 [prew_isaev_danny]=m157)
n() { .venv/bin/python -c "import json,sys;print(len(json.load(open(sys.argv[1]))['reels']))" "$1"; }
for S in "${!G[@]}"; do g=${G[$S]}; O="reviews/${S}_$g.review.json"; R="reviews/$S.review.json"; B="handoff/m174/$S.before"
  rm -f "$B"; [ -f "$R" ] && cp "$R" "$B"
  D="reviews/${S}_auto_all_$g.txt"; arl blocks --apply "$D" > "handoff/m174/apply.$S.txt" 2>&1; rc=$?
  if [ $rc != 0 ] || [ "$(n "$R")" != "$(n "$O")" ]; then D="reviews/${S}_auto_$g.txt"; arl blocks --apply "$D" > "handoff/m174/apply.$S.txt" 2>&1; rc=$?; fi
  echo "$S: $D rc=$rc"; [ $rc = 0 ] && cp "$R" "reviews/${S}_m174pre.review.json"
  if [ -f "$B" ]; then cp "$B" "$R"; else rm -f "$R"; fi
done 2>&1 | tee handoff/m174/apply.txt
.venv/bin/python handoff/m173/measure_shots.py reviews/*_m174pre.review.json > handoff/m174/pre.txt; tail -1 handoff/m174/pre.txt
grep -c "inside a sentence" handoff/m174/pre.txt; grep -c "whole sentences" handoff/m174/pre.txt
```
Ожидается:
- `rc=0` у всех 7;
- в `pre.txt` SLIVER 0;
- «inside a sentence» намного меньше 53 (m173);
- остальные короткие — «whole sentences»: их уберёт перепрогон.

Оставшиеся «inside a sentence» перечислить в отчёте (источник, клип, `src`). Это не СТОП.

## Шаг 3. Перепрогон всего в гейт m174 (в фоне)
```bash
S7=(disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny)
nohup .venv/bin/python -m autoreels auto "${S7[@]}" --gate m174 --tag m174 --encoder hevc_videotoolbox > handoff/m174/auto.txt 2>&1 &
echo "pid $!"
```
Проверять раз в 10 минут (`tail -5 handoff/m174/auto.txt`) до строки `=== auto: итог`.

Сценарист должен взяться из кэша: в `auto.txt` нет новых строк о стоимости сценариста. Если сценарист пошёл в модель заново (строки «сценарист … ≈ $»), это не СТОП: в отчёт с суммой.

## Шаг 4. Замер после, посты, выгрузка, сетка
```bash
sed -n '/=== auto: итог/,$p' handoff/m174/auto.txt | tee handoff/m174/itog.txt
.venv/bin/python handoff/m173/measure_shots.py reviews/*_m174.review.json > handoff/m174/after.txt; tail -1 handoff/m174/after.txt
for S in "${S7[@]}"; do d="reels-out/$S/_gate/m174"
  for k in 1 2; do miss=$(for f in "$d"/r[0-9]*.mp4; do b=$(basename "$f" .mp4); [ -f "$d/$b.post.txt" ] || echo "$b"; done | paste -sd, -)
    [ -z "$miss" ] && break; arl describe "$S" --gate m174 --reels "$miss" --force --llm sonnet 2>&1 | grep -E "^describe|не принято"; done
  echo "$S: клипов $(ls "$d"/r[0-9]*.mp4 | wc -l), без поста: $(for f in "$d"/r[0-9]*.mp4; do b=$(basename "$f" .mp4); [ -f "$d/$b.post.txt" ] || echo "$b"; done | paste -sd, -)"
done | tee handoff/m174/posts.txt
mkdir -p ~/.Trash/autoreels-m174/export && mv export/crosspost/* ~/.Trash/autoreels-m174/export/ && cp ~/.Trash/autoreels-m174/export/schedule.csv export/crosspost/
for S in "${S7[@]}"; do d="reels-out/$S/_gate/m174"; R=$(ls "$d"/r[0-9]*.mp4 | grep -v ERROR | xargs -n1 basename | sed 's/\.mp4$//' | paste -sd, -)
  arl crosspost "$S" --gate m174 --reels "$R" 2>&1 | grep -E "клипов|пропущ"; done | tee handoff/m174/export.txt
.venv/bin/python handoff/m174/grid2.py m174 | tee handoff/m174/grid.txt
cp export/crosspost/grid.csv handoff/m174/grid.csv
```
Ожидается:
- в `after.txt` SLIVER 0. Короткие планы — только в клипах без автоматического исправления: перечислить. Ноль — хорошо;
- у каждого источника «без поста:» пусто, иначе перечислить;
- 7 строк «клипов N»;
- `grid.txt`: «выпали» и «новые» перечислены; «в третьем лице: 0»; «с хэштегом в заголовке: 0».

Новые клипы `grid2.py` ставит в конец. Если новых больше 0: прочитать их посты и переставить каждый в `export/crosspost/schedule.csv` на место по смыслу (рядом с близким по теме), заполнить «связь». Потом `python handoff/m174/grid2.py m174 --from m174`: даты лягут заново, клипы сопоставятся сами с собой (у каждого «на месте», выпавших 0).

## Шаг 5. Отчёт
`handoff/m174/REPORT.md`:
- коммит, pytest;
- итоги `pre.txt`, `after.txt` (строки ВСЕГО и оставшиеся короткие);
- `itog.txt`: клипов m174 против m163/m157 по источникам;
- `posts.txt`, `export.txt`, `grid.txt`;
- сколько клипов совпало с прежними и какие новые.

`bash handoff/bin/report.sh m174 apply.txt pre.txt after.txt itog.txt posts.txt export.txt grid.txt grid.csv`

Владельцу — три строки:
- «перепрогон готов: N клипов в _gate/m174 (было 86), листы reels-out/<источник>/_gate/m174/_review.html»;
- «скачков: вспышек 0, коротких планов X (было 128)»;
- «сетка обновлена — export/crosspost/grid.csv; старые гейты m163/m157 можно убрать после твоего „да“».

Статус: IMPLEMENTED, GATE PENDING.
