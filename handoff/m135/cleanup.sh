#!/usr/bin/env bash
# M135: уборка папки проекта (по ревью m133). Без флага — только показывает (dry run); с --do — делает.
# Ничего невосстановимого: гейты и .bak уходят в Корзину (~/.Trash/autoreels-m135/), место освобождается,
# когда владелец очистит Корзину. Удаляются насовсем только пустые .render.lock старше суток и .DS_Store.
#   bash handoff/m135/cleanup.sh            # показать
#   bash handoff/m135/cleanup.sh --do       # сделать
set -euo pipefail
DO=0; [ "${1:-}" = "--do" ] && DO=1
ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"
TRASH="$HOME/.Trash/autoreels-m135"
# гейты, которые остаются: свежие задачи и старые, которые владелец ещё не смотрел (PLAN «ждут владельца»)
KEEP_RE='^(m18_final|m88|m94|m101|m102|m105|m112|m115|m126|m131|m134)'
AGE_DAYS=14

say() { printf '%s\n' "$*"; }
move_to_trash() {   # путь относительно ROOT
  local rel="$1" dst="$TRASH/$1"
  if [ $DO = 1 ]; then mkdir -p "$(dirname "$dst")"; mv "$rel" "$dst"; fi
}

if pgrep -f "autoreels render|autoreels auto|arl r( |$)" >/dev/null 2>&1; then
  say "ВНИМАНИЕ: идёт рендер — замки моложе суток не трогаются в любом случае"
fi

# гейты выбираются ДО остальной уборки: удаление замка или .DS_Store обновляет время папки
GATES=()
for g in reels-out/*/_gate/*/; do
  [ -d "$g" ] || continue
  name="$(basename "$g")"
  if [[ "$name" =~ $KEEP_RE ]]; then continue; fi
  if [ -z "$(find "$g" -maxdepth 0 -mtime +$AGE_DAYS)" ]; then continue; fi
  if [ -n "$(find "$g" -name '.render.lock' -mtime -1 2>/dev/null)" ]; then say "  пропуск гейта (свежий замок): $g"; continue; fi
  GATES+=("${g%/}")
done

say "== 1. Пустые .render.lock старше суток"
n=0
while IFS= read -r -d '' f; do
  say "  $f"; n=$((n+1)); [ $DO = 1 ] && rm -f "$f"
done < <(find reels-out -name '.render.lock' -size 0 -mtime +0 -print0 2>/dev/null)
say "  всего: $n"

say "== 2. .DS_Store"
n=0
while IFS= read -r -d '' f; do
  n=$((n+1)); [ $DO = 1 ] && rm -f "$f"
done < <(find . \( -path ./.git -o -path ./.venv -o -path ./reviews/.git \) -prune -o -name '.DS_Store' -print0)
say "  всего: $n"

say "== 3. .bak / .orig → Корзина"
n=0
while IFS= read -r -d '' f; do
  f="${f#./}"; say "  $f"; n=$((n+1)); move_to_trash "$f"
done < <(find . \( -path ./.git -o -path ./.venv -o -path ./reviews/.git \) -prune -o \( -name '*.bak' -o -name '*.orig' \) -type f -print0)
say "  всего: $n"

say "== 4. Гейты старше $AGE_DAYS дней (кроме $KEEP_RE) → Корзина"
tot=0
for g in "${GATES[@]+"${GATES[@]}"}"; do
  kb=$(du -sk "$g" | cut -f1); tot=$((tot+kb))
  say "  $g  $((kb/1024)) МБ"
  move_to_trash "$g"
done
say "  всего: ${#GATES[@]} гейтов, $((tot/1024/1024)) ГБ"

[ $DO = 1 ] && say "СДЕЛАНО. Корзина: $TRASH (место освободится после очистки Корзины)" || say "DRY RUN — ничего не изменено"
