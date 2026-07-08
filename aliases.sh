# autoreels shell aliases
# Один раз: autoreels install-aliases  (или вручную добавь в ~/.zshrc / ~/.bashrc):
#   source /путь/к/autoreels/aliases.sh
# Дальше алиасы обновляются через git pull — правь здесь, коммить, пулли.

# Корень проекта — папка с этим файлом (работает при source с абсолютным путём).
# BASH_SOURCE[0] в bash; $0 в zsh при source.
_AR_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)"

# ar: активировать venv проекта (если ещё не активен), затем диспетчер команд.
# Mac/Linux: .venv/bin/activate   Windows Git Bash: .venv/Scripts/activate
#
# КОРОТКИЕ КОМАНДЫ:
#   ar           → status + подсказка следующего шага
#   ar go        → run всех видео + git push манифестов (Mac, нужен Groq)
#   ar go --no-push → run без git push
#   ar r         → git pull + render (системник)
#   ar s         → status
#   ar c         → calibrate --all
#   ar h         → help
#   ar <...>     → передать в autoreels напрямую
ar() {
    # Активация venv
    if [ -z "$VIRTUAL_ENV" ] || [ "$VIRTUAL_ENV" != "$_AR_ROOT/.venv" ]; then
        if [ -f "$_AR_ROOT/.venv/bin/activate" ]; then
            # shellcheck source=/dev/null
            source "$_AR_ROOT/.venv/bin/activate"
        elif [ -f "$_AR_ROOT/.venv/Scripts/activate" ]; then
            # shellcheck source=/dev/null
            source "$_AR_ROOT/.venv/Scripts/activate"
        fi
    fi

    # Диспетчер
    case "$1" in
        "")
            # ar без аргумента → status + подсказка следующего шага
            autoreels
            ;;
        go)
            # ar go [--no-push]: run всех видео → git push манифестов
            shift
            local _no_push=0
            for _arg in "$@"; do
                [ "$_arg" = "--no-push" ] && _no_push=1
            done
            autoreels run || return 1
            if [ "$_no_push" -eq 0 ]; then
                git -C "$_AR_ROOT" add manifests/ && \
                git -C "$_AR_ROOT" commit -m "manifests: run $(date '+%Y-%m-%d %H:%M')" && \
                git -C "$_AR_ROOT" push && \
                echo "" && \
                echo "✓ манифесты отправлены → на системнике: ar r"
            fi
            ;;
        r)
            # ar r: git pull → render (энкодер из config/render.yaml)
            git -C "$_AR_ROOT" pull && autoreels render
            ;;
        s)
            autoreels status
            ;;
        c)
            autoreels calibrate --all
            ;;
        h)
            autoreels help
            ;;
        *)
            # Всё остальное — передать в autoreels как есть
            autoreels "$@"
            ;;
    esac
}
