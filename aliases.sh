# autoreels shell aliases
# Один раз: autoreels install-aliases  (или вручную добавь в ~/.zshrc / ~/.bashrc):
#   source /путь/к/autoreels/aliases.sh
# Дальше алиасы обновляются через git pull — правь здесь, коммить, пулли.

# Корень проекта — папка с этим файлом (работает при source с абсолютным путём).
# BASH_SOURCE[0] в bash; $0 в zsh при source.
_AR_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)"

# Принудительно UTF-8 для Python-вывода (важно на Windows Git Bash, где дефолт — cp1251/cp866).
export PYTHONUTF8=1

# Интерпретатор для module-фолбэка: первый доступный python (после активации venv — venv-python).
_ar_python() {
    local p
    for p in python python3 python3.13; do
        if command -v "$p" >/dev/null 2>&1; then printf '%s\n' "$p"; return 0; fi
    done
    printf 'python\n'   # последняя надежда — пусть упадёт с внятной ошибкой
}

# Запуск CLI autoreels, устойчиво к платформе. Предпочитает прямой console-script
# `autoreels`; если тот отсутствует или не запускается (наблюдалось на Windows Python 3.14,
# где entry-point .exe не кладётся в PATH / не стартует) — падает на `python -m autoreels`.
# Режим определяется один раз за сессию shell и кэшируется в _AR_CLI_MODE.
_ar_cli() {
    if [ -z "${_AR_CLI_MODE:-}" ]; then
        if command -v autoreels >/dev/null 2>&1 && autoreels --help >/dev/null 2>&1; then
            _AR_CLI_MODE="direct"
        else
            _AR_CLI_MODE="module"
        fi
    fi
    if [ "$_AR_CLI_MODE" = "direct" ]; then
        autoreels "$@"
    else
        "$(_ar_python)" -m autoreels "$@"
    fi
}

# Интерактивное меню (цикл в bash, «мозги» — autoreels menu на Python).
# Рисует адаптивное меню, читает цифру, запускает пункт, возвращается — до «Выход».
_ar_menu() {
    while true; do
        _ar_cli menu
        printf "Выбор [цифра, Enter — обновить]: "
        read -r _choice
        _action="$(_ar_cli menu --resolve "$_choice")"
        case "$_action" in
            go)        ar go ;;
            render)    ar r ;;
            status)    ar s ;;
            calibrate) ar c ;;
            path)
                printf "Вставь ссылку (URL / Яндекс.Диск / YouTube) или путь к файлу: "
                read -r _src
                if [ -z "$_src" ]; then echo "отменено — назад в меню"; continue; fi
                _ar_cli menu --classify "$_src"     # покажет, что распознано
                ar run "$_src"
                ;;
            transcribe)
                printf "Что транскрибировать — ссылка (URL / Яндекс.Диск) или путь к файлу: "
                read -r _src
                if [ -z "$_src" ]; then echo "отменено — назад в меню"; continue; fi
                _ar_cli menu --classify "$_src"     # покажет, что распознано
                ar t "$_src"
                ;;
            resume)    _ar_cli resume ;;
            help)      ar h ;;
            quit)      echo "пока!"; return 0 ;;
            *)
                # Пустой ввод или мусор → просто перерисовать меню, без паузы.
                [ -n "$_choice" ] && echo "  неизвестный пункт: $_choice"
                continue
                ;;
        esac
        printf "\n[Enter] — назад в меню… "
        read -r _
    done
}

# ar: активировать venv проекта (если ещё не активен), затем диспетчер команд.
# Mac/Linux: .venv/bin/activate   Windows Git Bash: .venv/Scripts/activate
#
# КОРОТКИЕ КОМАНДЫ:
#   ar           → интерактивное меню (цифрами)
#   ar menu      → то же меню
#   ar go        → run всех видео + git push манифестов (Mac, нужен Groq)
#   ar go --no-push → run без git push
#   ar r         → git pull + render (системник)
#   ar s         → status
#   ar c         → calibrate --all
#   ar t <ист>   → transcribe (видео/аудио/url → текст для контента)
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
        ""|menu)
            # ar / ar menu → интерактивное меню
            _ar_menu
            ;;
        go)
            # ar go [--no-push]: run всех видео. Каждый успешный манифест коммитится+пушится
            # СРАЗУ (per-video, внутри Python) — упади прогон на середине, уже готовые
            # манифесты уже на системнике. --no-push отключает. Push-логика — в cmd_run,
            # не здесь: раньше shell-push в конце терялся при любом упавшем видео (|| return).
            shift
            _ar_cli run "$@"
            ;;
        r)
            # ar r: git pull → render (энкодер из config/render.yaml)
            git -C "$_AR_ROOT" pull && _ar_cli render
            ;;
        s)
            _ar_cli status
            ;;
        c)
            _ar_cli calibrate --all
            ;;
        t)
            # ar t <видео|аудио|url>: транскрибация для контента
            shift
            _ar_cli transcribe "$@"
            ;;
        h)
            _ar_cli help
            ;;
        *)
            # Всё остальное — передать в autoreels как есть
            _ar_cli "$@"
            ;;
    esac
}
