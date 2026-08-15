# autoreels — bootstrap одной командой: venv + короткие команды + меню.
#
# ЗАПУСКАТЬ ЧЕРЕЗ SOURCE, чтобы venv и команды arl остались в текущем shell:
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

# --- ffmpeg: разовая настройка машинного пути (системник Windows, ffmpeg вне PATH) ---

# ffmpeg доступен? PATH или типичные места (D:/C: на Windows, /usr/local, homebrew).
_start_find_ffmpeg() {
    if command -v ffmpeg >/dev/null 2>&1; then command -v ffmpeg; return 0; fi
    local c
    for c in "/d/ffmpeg/bin/ffmpeg.exe" "D:/ffmpeg/bin/ffmpeg.exe" \
             "/c/ffmpeg/bin/ffmpeg.exe" "C:/ffmpeg/bin/ffmpeg.exe" \
             "/usr/local/bin/ffmpeg" "/opt/homebrew/bin/ffmpeg" "/usr/bin/ffmpeg"; do
        [ -f "$c" ] && { printf '%s\n' "$c"; return 0; }
    done
    return 1
}

# render.local.yaml уже задаёт ffmpeg:?
_start_ffmpeg_in_local() {
    local f="$1/config/render.local.yaml"
    [ -f "$f" ] && grep -qE '^[[:space:]]*ffmpeg:[[:space:]]*[^[:space:]]' "$f"
}

# Записать ffmpeg-путь в render.local.yaml (создаёт файл; не трогает, если ffmpeg: уже есть).
_start_write_ffmpeg_local() {
    local root="$1" path="$2" f="$1/config/render.local.yaml"
    if [ -f "$f" ] && grep -qE '^[[:space:]]*ffmpeg:' "$f"; then return 0; fi
    printf 'ffmpeg: %s\n' "$path" >> "$f"
}

# Первый запуск: если ffmpeg не найден и не задан в render.local.yaml — спросить путь и зашить.
_start_ensure_ffmpeg() {
    local root="$1" path
    _start_ffmpeg_in_local "$root" && return 0        # уже настроен в render.local.yaml
    _start_find_ffmpeg >/dev/null 2>&1 && return 0     # есть в PATH/типичных местах
    echo "⚠ ffmpeg не найден (нет в PATH и типичных местах)."
    printf "  укажи путь к ffmpeg (напр. D:/ffmpeg/bin/ffmpeg.exe), Enter — пропустить: "
    read -r path
    if [ -n "$path" ]; then
        _start_write_ffmpeg_local "$root" "$path"
        echo "  ✓ записано в config/render.local.yaml (ffmpeg: $path) — разово."
    else
        echo "  пропущено. Позже: config/render.local.yaml → ffmpeg: <путь>  или  --ffmpeg."
    fi
}

# Предложить автозагрузку: дописать `source aliases.sh` в профиль shell, чтобы команды arl
# работали в ЛЮБОМ новом терминале без ручного `source start.sh`. Идемпотентно: если строка
# уже в одном из профилей — молчим. Иначе спрашиваем и зовём `autoreels install-aliases`.
_start_offer_autoload() {
    local root="$1" line prof _ans
    line="source $root/aliases.sh"
    for prof in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile"; do
        [ -f "$prof" ] && grep -qF "$line" "$prof" 2>/dev/null && return 0   # уже настроено
    done
    printf "Прописать автозагрузку команд arl в профиль shell (работали бы в любом терминале)? [д/н]: "
    read -r _ans
    case "$_ans" in
        д|Д|y|Y|yes) autoreels install-aliases --yes ;;
        *) echo "  пропущено. Позже разово: autoreels install-aliases" ;;
    esac
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
        echo "  для постоянных команд arl:  source start.sh"
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

    # Короткие команды arl + функция меню.
    # shellcheck source=/dev/null
    . "$root/aliases.sh"

    # Разово предложить автозагрузку (source aliases.sh в профиль) — чтобы arl работал сразу
    # в любом новом терминале, без ритуала `source start.sh`. Только если ещё не прописано.
    _start_offer_autoload "$root"

    # GROQ_API_KEY нужен для run/transcribe (Groq). Для render — нет. Только предупреждаем.
    if [ ! -f "$root/.env" ] || ! grep -q '^GROQ_API_KEY=..*' "$root/.env" 2>/dev/null; then
        echo "⚠ .env без GROQ_API_KEY — run/transcribe (Groq) не сработают."
        echo "  впиши ключ в $root/.env (см. .env.example). Для render ключ не нужен."
        echo
    fi

    # Разовая настройка ffmpeg на этой машине (системник Windows: ffmpeg часто вне PATH).
    _start_ensure_ffmpeg "$root"

    # Меню само рисует шапку-состояние (inputs/манифесты/готово) и работает до «Выход».
    _ar_menu
}

# Библиотечный режим (тесты): только определения функций, без запуска.
if [ -z "${AUTOREELS_START_LIB:-}" ]; then
    _start_main
fi
