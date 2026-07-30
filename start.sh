# autoreels — bootstrap одной командой: venv + короткие команды + меню.
#
# ЗАПУСКАТЬ ЧЕРЕЗ SOURCE, чтобы venv и команды ar остались в текущем shell:
#     source start.sh          (или коротко:  . start.sh)
# Через ./start.sh тоже работает (меню откроется), но после выхода окружение
# не сохранится — активация venv живёт только в sourced-шелле.
#
# Первый запуск (нет .venv) → создаёт окружение и ставит autoreels (разово).
# Дальше → быстро активирует и открывает меню.
#
# Кроссплатформенно: macOS/Linux (.venv/bin) и Windows Git Bash (.venv/Scripts).

# Корень проекта = каталог этого скрипта. BASH_SOURCE в bash, $0 в zsh при source.
# Тело в круглых скобках → cd в субшелле, рабочий каталог вызывающего не меняем.
_start_root() ( cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd )

# Путь к activate внутри venv: Mac/Linux bin/ приоритетнее, иначе Windows Scripts/.
# Печатает пустую строку, если venv нет.
_start_venv_activate() {
    local root="$1"
    if [ -f "$root/.venv/bin/activate" ]; then
        printf '%s\n' "$root/.venv/bin/activate"
    elif [ -f "$root/.venv/Scripts/activate" ]; then
        printf '%s\n' "$root/.venv/Scripts/activate"
    fi
}

# Первый доступный интерпретатор (проект требует 3.11+; python3.13 закреплён).
_start_python() {
    local p
    for p in python3.13 python3 python; do
        if command -v "$p" >/dev/null 2>&1; then
            printf '%s\n' "$p"
            return 0
        fi
    done
    return 1
}

# Скрипт запущен через source (окружение сохранится) или как ./start.sh (нет)?
_start_is_sourced() {
    if [ -n "${BASH_SOURCE:-}" ]; then
        [ "${BASH_SOURCE[0]}" != "${0}" ]
        return
    fi
    case "${ZSH_EVAL_CONTEXT:-}" in
        *:file*) return 0 ;;
    esac
    return 1
}

_start_main() {
    local root act py
    root="$(_start_root)"

    if ! _start_is_sourced; then
        echo "⚠ запущено без source — окружение не сохранится после выхода из меню."
        echo "  для постоянных команд ar:  source start.sh"
        echo
    fi

    act="$(_start_venv_activate "$root")"
    if [ -z "$act" ]; then
        echo "первый запуск: создаю виртуальное окружение и ставлю autoreels…"
        py="$(_start_python)" || { echo "ошибка: не найден python (python3.13/python3/python)"; return 1; }
        "$py" -m venv "$root/.venv" || { echo "ошибка: не удалось создать .venv"; return 1; }
        act="$(_start_venv_activate "$root")"
        # shellcheck source=/dev/null
        . "$act"
        echo "ставлю зависимости (разово, ~минуту)…"
        python -m pip install -q -e "$root" || { echo "ошибка установки зависимостей"; return 1; }
        echo "✓ готово — окружение создано."
        echo
    else
        # shellcheck source=/dev/null
        . "$act"
    fi

    # Короткие команды ar + функция меню.
    # shellcheck source=/dev/null
    . "$root/aliases.sh"

    # GROQ_API_KEY нужен для run/transcribe (Groq). Для render — нет. Только предупреждаем.
    if [ ! -f "$root/.env" ] || ! grep -q '^GROQ_API_KEY=..*' "$root/.env" 2>/dev/null; then
        echo "⚠ .env без GROQ_API_KEY — run/transcribe (Groq) не сработают."
        echo "  впиши ключ в $root/.env (см. .env.example). Для render ключ не нужен."
        echo
    fi

    # Меню само рисует шапку-состояние (inputs/манифесты/готово) и работает до «Выход».
    _ar_menu
}

# Библиотечный режим (тесты): только определения функций, без запуска.
if [ -z "${AUTOREELS_START_LIB:-}" ]; then
    _start_main
fi
