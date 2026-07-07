# autoreels shell aliases
# Один раз: добавь в ~/.zshrc (Mac) или ~/.bashrc (Windows Git Bash):
#   source /путь/к/autoreels/aliases.sh
# Или запусти: autoreels install-aliases
# Дальше алиасы обновляются через git pull — правь здесь, коммить, пулли.

# Корень проекта — папка с этим файлом (работает при source с абсолютным путём).
# BASH_SOURCE[0] в bash; $0 в zsh при source.
_AR_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)"

# ar: активировать venv проекта (если ещё не активен), затем вызвать autoreels.
# Mac/Linux: .venv/bin/activate   Windows Git Bash: .venv/Scripts/activate
ar() {
    if [ -z "$VIRTUAL_ENV" ] || [ "$VIRTUAL_ENV" != "$_AR_ROOT/.venv" ]; then
        if [ -f "$_AR_ROOT/.venv/bin/activate" ]; then
            # shellcheck source=/dev/null
            source "$_AR_ROOT/.venv/bin/activate"
        elif [ -f "$_AR_ROOT/.venv/Scripts/activate" ]; then
            # shellcheck source=/dev/null
            source "$_AR_ROOT/.venv/Scripts/activate"
        fi
    fi
    autoreels "$@"
}
