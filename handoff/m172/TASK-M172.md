# TASK M172 (окно MAIN, Mac; после m171): короткий кусок у стыка не даёт скачка плана

Файлы — ветка `handoff`, папка `handoff/m172/`: `TASK-M172.md`, `m172-short-piece.patch`, `compare_reels.py`. Около 20 минут.

## Зачем
Владелец о disko_beach_p3 (бывш. `2026-08-08 09h 33m 14s`) m163 r01: «в начале скачок плана… такие скачки — плохо». Из плана клипа:
- крючок 820.92–826.12;
- затем кусок 780.29–781.04: одно предложение 17.7, 0,7 с;
- пауза 2,3 с вырезана, дальше 783.34–809.11 (18.1…).

Строка черновика: `M1 95 | 17.7 18.1-9 | h:18.8! …`. 17.7 и 18.1 идут в источнике подряд. Но правило M58 склеивает соседние куски только при паузе не больше `montage.join_gap_sec` (2,0 с), а здесь 2,3 с. Получается шов через 0,7 с после смены плана крючком.

Патч:
- кусок, который звучит меньше `montage.join_short_sec`, склеивается с соседним по источнику через паузу до `montage.join_short_gap_sec`. Длительность берётся по звуку (выравнивание или карта), с тем же условием «между ними нет другого слова»;
- пауза проигрывается; вырезка пауз может её укоротить внутри окна, по своим правилам маскировки;
- 0 = выкл. = прежнее правило M58 (тест). В `config/r0.yaml` включено: 2,0 и 4,0;
- тесты `tests/test_m172_short_piece_join.py` (7).

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. `--install` и `arl auto` не запускать. `reviews/*_answer*.txt` и `manifests/` не трогать. `reviews/<S>.review.json` сохраняется и возвращается. Производственные клипы (`_gate/m163`, `_gate/m157`) не перерендеривать.
3. Рендер один за раз; pytest — не во время рендера.

## Шаг 1. Патч, тесты, коммит
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m172; mkdir -p handoff/m172
git apply --check handoff/m172/m172-short-piece.patch && git apply handoff/m172/m172-short-piece.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests config && git commit -m "Montage (M172): a piece speaking under montage.join_short_sec joins its straight-on neighbour across a pause up to join_short_gap_sec (09h33 m163 r01: hook, 0.7 s, jump)" && git push && git log --oneline -1
```
Ожидается: `applied`. pytest: всё прошло, кроме известных пяти (`test_run_dispatch_*` ×4, `test_r0_output_parsing_survives_lower_max_tokens`) — перечислить. Коммит запушен.

## Шаг 2. Что меняется во всех производственных черновиках (без рендера)
Если m171 ещё не выполнен — имена старые: в списке ниже заменить новые имена на старые по таблице m171.
```bash
declare -A G=([disko_beach_p1]=m163 [disko_beach_p2]=m163 [disko_beach_p3]=m163 [day_yoga_p1]=m163 [day_yoga_p2]=m163 [prew_isaev_anna]=m157 [prew_isaev_danny]=m157)
for S in "${!G[@]}"; do g=${G[$S]}
  D="reviews/${S}_auto_all_$g.txt"; O="reviews/${S}_$g.review.json"
  [ -f "$O" ] || { echo "$S: нет $O"; continue; }
  R="reviews/$S.review.json"; B="handoff/m172/$S.before"; rm -f "$B"; [ -f "$R" ] && cp "$R" "$B"
  arl blocks --apply "$D" > "handoff/m172/apply.$S.txt" 2>&1; rc=$?
  if [ $rc != 0 ] || ! cmp -s <(.venv/bin/python -c "import json,sys;print(len(json.load(open(sys.argv[1]))['reels']))" "$R") <(.venv/bin/python -c "import json,sys;print(len(json.load(open(sys.argv[1]))['reels']))" "$O"); then
    D="reviews/${S}_auto_$g.txt"; arl blocks --apply "$D" > "handoff/m172/apply.$S.txt" 2>&1; rc=$?
  fi
  echo "$S: $D rc=$rc"; [ $rc = 0 ] && cp "$R" "reviews/${S}_m172.review.json"
  if [ -f "$B" ]; then cp "$B" "$R"; else rm -f "$R"; fi
  [ $rc = 0 ] && .venv/bin/python handoff/m172/compare_reels.py "$O" "reviews/${S}_m172.review.json" > "handoff/m172/cmp.$S.txt"
  grep -h "go straight on" "handoff/m172/apply.$S.txt" | head -20
  tail -1 "handoff/m172/cmp.$S.txt"; grep -c "\[ERROR\]" "handoff/m172/apply.$S.txt"
done 2>&1 | tee handoff/m172/summary.txt
```
Логика: сначала берётся общий черновик. Если он не применяется или даёт другое число клипов, чем производственный review.json (так было в m163 из-за «label used twice»), берётся черновик автомонтажа — тот, из которого собраны производственные клипы.

Ожидается:
- `rc=0` у каждого источника;
- `[ERROR]` — 0;
- у disko_beach_p3 в `cmp` клип 01 помечен `≠`: вместо `780.29-781.04 783.34-809.11` одно окно от 780.29;
- в `apply` есть строка «pieces 17-17 + 18.1-9 go straight on» или похожая.

Остальные `≠` — в отчёт списком (источник: номера). Число клипов не должно меняться: изменилось — в отчёт.

## Шаг 3. Рендер изменившихся клипов disko_beach_p3 для сравнения
```bash
S=disko_beach_p3; N=$(tail -1 handoff/m172/cmp.$S.txt | sed 's/changed: //'); echo "клипы: $N"
arl render --manifest "reviews/${S}_m172.review.json" --reels "$N" --gate m172 --encoder hevc_videotoolbox 2>&1 | tail -15 | tee handoff/m172/render.txt
for f in reels-out/$S/_gate/m172/r*.mp4; do b=$(basename "$f"); echo "$b m172 $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f") m163 $(ffprobe -v error -show_entries format=duration -of csv=p=0 "reels-out/$S/_gate/m163/$b" 2>/dev/null)"; done | tee handoff/m172/probe.txt
```
Ожидается: `[ERROR]` нет. В `probe.txt` r01 длиннее m163 примерно на длину сохранённой паузы (до 2,3 с, меньше, если вырезка пауз её укоротила).

## Шаг 4. Отчёт
`handoff/m172/REPORT.md`: коммит, pytest, `summary.txt`, все `cmp.*.txt`, где есть `≠`, `render.txt`, `probe.txt`.
`bash handoff/bin/report.sh m172 summary.txt render.txt probe.txt cmp.*.txt`

Владельцу — две строки:
- «посмотри reels-out/disko_beach_p3/_gate/m172/r01.mp4 против _gate/m163/r01.mp4 — скачка в начале больше нет?»;
- «правка меняет ещё N клипов в других источниках (список); перерендерить их в производство — после твоего „да“».

Статус: IMPLEMENTED, GATE PENDING.
