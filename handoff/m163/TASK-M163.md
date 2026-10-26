# TASK M163 (окно MAIN, Mac): новые сценарии для пяти источников, рендер на Mac, пост у каждого клипа, уборка reels-out

Владелец 2026-10-26:
- по пяти источникам (три лекции 2026-08-08, оба Pxl 20260621) — **новые сценарии заново** и рендер;
- у каждого клипа — **мини-пост о чём видео**;
- у IMG_6848 и PXL_20260729_copy оставить только m157;
- все лишние гейты и прогоны из reels-out — удалить.

Сценарист кэширует ответ по запросу (`data/cache/scenario/<ист>.<ключ>.txt`), поэтому в m157 сюжеты повторились. Здесь кэш пяти источников уводится в сторону, и сценарист пишет заново. Платно, из промо (до 02.11): около $1.

## Правила
1. Шаг упал → **СТОП**: шаг, команда, последние 40 строк.
2. `--install` не запускать. `manifests/`, `reviews/*_answer*.txt` и настоящие клипы `reels-out/<ист>/r*.mp4` не трогать.
3. Уборка (шаг 5) — только после успешного прогона (шаг 2), так что до него наборы m157 остаются. Рендер один; pytest не нужен.

## Шаг 1. Кэш сценариста пяти источников — в сторону
```bash
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m163; mkdir -p handoff/m163/scen_cache_before
S5=("2026-08-08 09h 33m 14s" "2026-08-08 10h 59m 38s" "2026-08-08 11h 42m 49s" "Pxl 20260621 122006193" "Pxl 20260621 112938952")
for S in "${S5[@]}"; do for f in data/cache/scenario/"$S".*.txt; do [ -f "$f" ] && mv "$f" handoff/m163/scen_cache_before/; done; done
ls handoff/m163/scen_cache_before | wc -l; for S in "${S5[@]}"; do ls data/cache/scenario/"$S".*.txt 2>/dev/null; done; echo "кэш убран"
```
Ожидается: число убранных файлов > 0; строк с путями после него нет; «кэш убран».

## Шаг 2. Прогон (в фоне)
```bash
nohup .venv/bin/python -m autoreels auto "${S5[@]}" --gate m163 --tag m163 --encoder hevc_videotoolbox > handoff/m163/auto.txt 2>&1 &
echo "pid $!"
```
В начале `auto.txt` должны быть строки «карта, судьи и посты — sonnet (до 2026-11-02 включительно)» и «ролики пишет сценарист (sonnet, платно)». В расходах у каждого источника — запрос сценариста (`запросов 1`, ответ тысячи токенов). Если вместо этого он взят из кэша — СТОП. Проверять раз в 10 минут (`tail -5`) до `=== auto: итог`.

## Шаг 3. Мини-пост у каждого клипа m163
Пост — `<клип>.post.txt` (3–5 предложений о содержании словами ролика + хэштеги из сказанного; `arl auto` пишет сам). Недостающие — дописать, готовые не перезаписываются.
```bash
for S in "${S5[@]}"; do d="reels-out/$S/_gate/m163"
  n=$(ls "$d"/r[0-9]*.mp4 2>/dev/null | grep -vc ERROR); p=$(ls "$d"/r*.post.txt 2>/dev/null | wc -l | tr -d ' ')
  [ "$p" -lt "$n" ] && .venv/bin/python -m autoreels describe "$S" --gate m163 --llm sonnet > "handoff/m163/describe.$S.txt" 2>&1
  echo "$S: клипов $n, постов $(ls "$d"/r*.post.txt 2>/dev/null | wc -l | tr -d ' ')"
  for f in "$d"/r*.mp4; do case "$f" in *ERROR*) echo "   РЕНДЕР С ОШИБКОЙ: $(basename "$f")";; *) [ -f "${f%.mp4}.post.txt" ] || echo "   без поста: $(basename "$f")";; esac; done
done | tee handoff/m163/posts.txt
grep -nE "\[ERROR\]" handoff/m163/auto.txt | head -20 | tee handoff/m163/errors.txt
```
Ожидается: у каждого клипа без ошибки есть пост. Клипы `*.ERROR.mp4` (рендер не прошёл проверку) — с причиной из `errors.txt` в отчёт.

## Шаг 4. Сводка
```bash
sed -n '/=== auto: итог/,$p' handoff/m163/auto.txt | tee handoff/m163/itog.txt
grep -hE "Claude .*≈ \\$" handoff/m163/auto.txt handoff/m163/describe.*.txt 2>/dev/null | awk -F'≈ \\$' '{s+=$2} END {printf "ИТОГО ≈ $%.2f\n", s}' | tee handoff/m163/cost.txt
```

## Шаг 5. Уборка reels-out (после успешного шага 2)
Остаётся по одному набору: пять источников — m163, IMG_6848 и PXL_20260729_copy — m157. Остальные гейты уходят в Корзину (`~/.Trash/autoreels-m163/`). Настоящие клипы не трогаются.
```bash
bash handoff/m163/gates.sh | tee handoff/m163/gates.txt | tail -12
bash handoff/m163/gates.sh --do | tail -2
ls -d reels-out/*/_gate/*/
ssh gamebox 'ls -d /mnt/data/autoreels/reels-out/*/_gate/*/ 2>/dev/null; rm -rf /mnt/data/autoreels/reels-out/*/_gate/*; echo "gamebox: пробные гейты удалены"'
```
Ожидается: в `ls` ровно 7 папок — пять `m163` и две `m157`. На gamebox удалены только пробные рендеры m156–m161 (там они ничьи).

## Шаг 6. Отчёт
`handoff/m163/REPORT.md`: `itog.txt`, `posts.txt`, `errors.txt`, `cost.txt`, `gates.txt` (сколько МБ ушло в Корзину), итоговый список папок.
`bash handoff/bin/report.sh m163 itog.txt posts.txt errors.txt cost.txt gates.txt`
Владельцу — по строке на источник: клипов и путь листа `reels-out/<ист>/_gate/m163/_review.html` (для IMG_6848 и PXL_copy — `_gate/m157`); стоимость; сколько освободится после очистки Корзины.

Статус: IMPLEMENTED, GATE PENDING.
