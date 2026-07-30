#!/bin/bash
# macOS: двойной клик в Finder → Terminal с активированным окружением autoreels + меню.
# После выхода из меню интерактивный shell остаётся с командами ar (rcfile + -i).
cd "$(dirname "$0")" && exec bash --rcfile ./start.sh -i
