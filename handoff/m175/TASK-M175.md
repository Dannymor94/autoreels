# TASK M175 (окно MAIN, Mac): замер — почему общий черновик не проходит (86 → 60 клипов)

Файлы — ветка `handoff`, папка `handoff/m175/`: `TASK-M175.md`. Около 10 минут. Без правок кода и без рендера (кроме r11).

## Зачем
В m174 у 5 из 7 источников общий черновик не прошёл: строки разметки + сборки. Взят только черновик сборок, и клипов стало 60 вместо 86–88.
- prew_isaev_anna: 20 → 9;
- prew_isaev_danny: 26 → 10;
- day_yoga_p2: 13 → 9.

В m157 у prew_* общий черновик проходил. Нужна точная причина по каждому источнику, до правки.

## Правила
Ничего не коммитить. `reviews/*_answer*.txt`, `manifests/` не трогать. `reviews/<S>.review.json` сохраняется и возвращается. Шаг упал → СТОП с выводом.

## Шаг 1. Причины отказа
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; bash handoff/bin/take.sh m175; mkdir -p handoff/m175
for S in disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny; do
  R="reviews/$S.review.json"; B="handoff/m175/$S.before"; rm -f "$B"; [ -f "$R" ] && cp "$R" "$B"
  L="reviews/${S}_auto.txt"; C="reviews/${S}_auto_all_m174.txt"
  echo "=== $S"
  echo "  черновик разметки: $( [ -f "$L" ] && echo "есть, строк с оценкой $(grep -cE '^[0-9x]+ +[0-9]' "$L"), строк M $(grep -c '^M' "$L"), изменён $(stat -f %Sm -t %F "$L")" || echo НЕТ)"
  echo "  общий: строк M $(grep -c '^M' "$C" 2>/dev/null)"
  arl blocks --apply "$C" --labeler auto > "handoff/m175/apply.$S.txt" 2>&1; echo "  rc=$?"
  grep -E "\[ERROR\]|^error|label used twice|fingerprint" "handoff/m175/apply.$S.txt" | sort | uniq -c | sort -rn | head -12
  arl blocks --apply "$L" --labeler auto > "handoff/m175/label.$S.txt" 2>&1; echo "  только разметка: rc=$? клипов $(.venv/bin/python -c "import json;print(len(json.load(open('$R'))['reels']))" 2>/dev/null)"
  grep -E "\[ERROR\]|^error" "handoff/m175/label.$S.txt" | sed -E 's/r[0-9]+/rNN/; s/[0-9]+\.[0-9]+/N/g' | sort | uniq -c | sort -rn | head -6
  if [ -f "$B" ]; then cp "$B" "$R"; else rm -f "$R"; fi
done 2>&1 | tee handoff/m175/why.txt
grep -c "" handoff/m175/why.txt
```

## Шаг 2. r11 prew_isaev_danny («whoosh pass failed»)
```bash
arl render --manifest reviews/prew_isaev_danny_m174.review.json --reels 11 --gate m174 --encoder hevc_videotoolbox 2>&1 | grep -B2 -A12 -iE "whoosh|ERROR" | tail -30 | tee handoff/m175/r11.txt
```
Если получилось без ERROR — так и написать: клип в гейте.

## Шаг 3. Отчёт
`handoff/m175/REPORT.md`: `why.txt` целиком и `r11.txt`. Затем `bash handoff/bin/report.sh m175 why.txt r11.txt apply.*.txt label.*.txt`.
Владельцу — одна строка: «замер причин готов, ассистент делает правку».

Статус: замер.
