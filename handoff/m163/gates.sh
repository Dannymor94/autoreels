#!/usr/bin/env bash
# M163: в reels-out остаётся по одному набору на источник (владелец 2026-10-26), остальные гейты — в Корзину
# (~/.Trash/autoreels-m163/). Настоящие клипы reels-out/<источник>/r*.mp4 не трогаются.
#   bash handoff/m163/gates.sh        # показать
#   bash handoff/m163/gates.sh --do   # сделать
set -euo pipefail
DO=0; [ "${1:-}" = "--do" ] && DO=1
ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"
TRASH="$HOME/.Trash/autoreels-m163"
keep_for() {
  case "$1" in
    "2026-08-08 09h 33m 14s"|"2026-08-08 10h 59m 38s"|"2026-08-08 11h 42m 49s"|"Pxl 20260621 122006193"|"Pxl 20260621 112938952") echo m163 ;;
    IMG_6848|PXL_20260729_copy) echo m157 ;;
    *) echo "" ;;
  esac
}
if pgrep -f "autoreels (render|auto)" >/dev/null 2>&1; then echo "идёт рендер — стоп"; exit 1; fi
n=0; tot=0
for g in reels-out/*/_gate/*/; do
  [ -d "$g" ] || continue
  g="${g%/}"; name="$(basename "$g")"; stem="$(basename "$(dirname "$(dirname "$g")")")"; k="$(keep_for "$stem")"
  # m147 (громкость по источнику) ещё не прослушан владельцем — пара m146b/m147 остаётся до его решения
  if [ "$stem" = IMG_6848 ] && { [ "$name" = m146b ] || [ "$name" = m147 ]; }; then echo "  оставлен (ждёт прослушивания громкости): $g"; continue; fi
  if [ -n "$k" ] && [ "$name" = "$k" ]; then echo "  оставлен: $g ($(ls "$g"/r*.mp4 2>/dev/null | wc -l | tr -d ' ') клипов)"; continue; fi
  kb=$(du -sk "$g" | cut -f1); tot=$((tot+kb)); n=$((n+1))
  echo "  в Корзину: $g  $((kb/1024)) МБ"
  if [ $DO = 1 ]; then mkdir -p "$TRASH/$(dirname "$g")"; mv "$g" "$TRASH/$g"; fi
done
echo "  всего: $n гейтов, $((tot/1024)) МБ"
[ $DO = 1 ] && echo "СДЕЛАНО. Корзина: $TRASH" || echo "DRY RUN — ничего не изменено"
