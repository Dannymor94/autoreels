#!/usr/bin/env bash
# M148: старые гейты закрыты владельцем 2026-10-26 → в Корзину (~/.Trash/autoreels-m148/).
# Остаются только непросмотренные: m146a, m146b, m147 (и всё, что моложе суток — идущая задача).
#   bash handoff/m148/gates.sh        # показать
#   bash handoff/m148/gates.sh --do   # сделать
set -euo pipefail
DO=0; [ "${1:-}" = "--do" ] && DO=1
ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"
TRASH="$HOME/.Trash/autoreels-m148"
KEEP_RE='^(m146a|m146b|m147)$'
if pgrep -f "autoreels render|autoreels auto|arl r( |$)" >/dev/null 2>&1; then echo "идёт рендер — стоп"; exit 1; fi
n=0; tot=0
for g in reels-out/*/_gate/*/; do
  [ -d "$g" ] || continue
  g="${g%/}"; name="$(basename "$g")"
  [[ "$name" =~ $KEEP_RE ]] && { echo "  оставлен: $g"; continue; }
  [ -n "$(find "$g" -maxdepth 0 -mmin -1440)" ] && { echo "  оставлен (моложе суток): $g"; continue; }
  kb=$(du -sk "$g" | cut -f1); tot=$((tot+kb)); n=$((n+1))
  echo "  $g  $((kb/1024)) МБ"
  if [ $DO = 1 ]; then mkdir -p "$TRASH/$(dirname "$g")"; mv "$g" "$TRASH/$g"; fi
done
echo "  всего: $n гейтов, $((tot/1024)) МБ"
[ $DO = 1 ] && echo "СДЕЛАНО. Корзина: $TRASH" || echo "DRY RUN — ничего не изменено"
