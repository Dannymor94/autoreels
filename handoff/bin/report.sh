#!/usr/bin/env bash
# Отдать отчёт ассистенту через ветку handoff:   bash handoff/bin/report.sh m109 [файлы из handoff/m109 …]
# Кладёт handoff/<задача>/REPORT.md (и перечисленные файлы) в ветку handoff и пушит. main не трогает:
# работа идёт в отдельной рабочей копии ветки handoff во временной папке.
set -euo pipefail
T="${1:?укажи задачу, например m109}"; shift || true
ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"
[ -f "handoff/$T/REPORT.md" ] || { echo "нет handoff/$T/REPORT.md — сначала запиши отчёт"; exit 1; }
WT="${TMPDIR:-/tmp}/autoreels-handoff"
git fetch -q origin handoff
if git -C "$WT" rev-parse --git-dir >/dev/null 2>&1; then
  git -C "$WT" reset -q --hard && git -C "$WT" clean -fdq && git -C "$WT" checkout -q --detach origin/handoff
else
  rm -rf "$WT"; git worktree prune; git worktree add -q --detach "$WT" origin/handoff
fi
mkdir -p "$WT/handoff/$T"
cp "handoff/$T/REPORT.md" "$WT/handoff/$T/"
for f in "$@"; do cp "handoff/$T/$f" "$WT/handoff/$T/"; done
cd "$WT"
git add -f "handoff/$T"
if git diff --cached --quiet; then echo "отчёт $T уже в ветке handoff — нечего отправлять"; exit 0; fi
git commit -q -m "report $T"
for i in 1 2 3; do
  if git push -q origin HEAD:handoff; then echo "отчёт $T отправлен в ветку handoff"; exit 0; fi
  git fetch -q origin handoff && git rebase -q origin/handoff
done
echo "отчёт $T не отправлен (push не прошёл трижды) — сообщи владельцу"; exit 1
