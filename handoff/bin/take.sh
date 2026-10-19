#!/usr/bin/env bash
# Забрать задачу ассистента из ветки origin/handoff:   bash handoff/bin/take.sh m109
# Файлы ложатся в handoff/<задача>/ рабочей копии (в main папка handoff/ не коммитится — она в .gitignore).
set -euo pipefail
T="${1:?укажи задачу, например m109}"
cd "$(git rev-parse --show-toplevel)"
git fetch -q origin +refs/heads/handoff:refs/remotes/origin/handoff
if ! git cat-file -e "origin/handoff:handoff/$T" 2>/dev/null; then
  echo "в ветке handoff нет handoff/$T — ассистент её ещё не выложил"
  exit 1
fi
git restore --source=origin/handoff --worktree -- handoff/bin "handoff/$T"
echo "задача $T: handoff/$T/"
ls -1 "handoff/$T"
