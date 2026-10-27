#!/usr/bin/env bash
# M169: в reels-out остаётся только то, что идёт в продакшн (владелец 2026-10-27): пять источников — m163,
# IMG_6848 и PXL_20260729_copy — m157 (без ведущего). Остальные гейты — в Корзину (~/.Trash/autoreels-m169/).
# Настоящие клипы reels-out/<источник>/r*.mp4 не трогаются.   bash … [--do]
set -euo pipefail
DO=0; [ "${1:-}" = "--do" ] && DO=1
ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"; TRASH="$HOME/.Trash/autoreels-m169"
keep() { case "$1/$2" in
  "2026-08-08 09h 33m 14s/m163"|"2026-08-08 10h 59m 38s/m163"|"2026-08-08 11h 42m 49s/m163"|\
  "Pxl 20260621 122006193/m163"|"Pxl 20260621 112938952/m163"|IMG_6848/m157|PXL_20260729_copy/m157) return 0;; esac; return 1; }
if pgrep -f "autoreels (render|auto)" >/dev/null 2>&1; then echo "идёт рендер — стоп"; exit 1; fi
n=0; tot=0
for g in reels-out/*/_gate/*/; do
  [ -d "$g" ] || continue; g="${g%/}"; name="$(basename "$g")"; stem="$(basename "$(dirname "$(dirname "$g")")")"
  if keep "$stem" "$name"; then echo "  оставлен: $g ($(ls "$g"/r*.mp4 2>/dev/null | grep -vc ERROR) клипов)"; continue; fi
  kb=$(du -sk "$g" | cut -f1); tot=$((tot+kb)); n=$((n+1)); echo "  в Корзину: $g  $((kb/1024)) МБ"
  [ $DO = 1 ] && { mkdir -p "$TRASH/$(dirname "$g")"; mv "$g" "$TRASH/$g"; }
done
echo "  всего: $n гейтов, $((tot/1024)) МБ"; [ $DO = 1 ] && echo "СДЕЛАНО. Корзина: $TRASH" || echo "DRY RUN"
