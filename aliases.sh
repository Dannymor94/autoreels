# autoreels shell aliases
# Один раз: autoreels install-aliases  (или вручную добавь в ~/.zshrc / ~/.bashrc):
#   source /путь/к/autoreels/aliases.sh
# Дальше алиасы обновляются через git pull — правь здесь, коммить, пулли.

# Корень проекта — папка с этим файлом (работает при source с абсолютным путём).
# BASH_SOURCE[0] в bash; $0 в zsh при source.
_AR_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)"

# Интерактивное меню (цикл в bash, «мозги» — autoreels menu на Python).
# Рисует адаптивное меню, читает цифру, запускает пункт, возвращается — до «Выход».
_ar_menu() {
    while true; do
        autoreels menu
        printf "Выбор [цифра, Enter — обновить]: "
        read -r _choice
        _action="$(autoreels menu --resolve "$_choice")"
        case "$_action" in
            go)        ar go ;;
            render)    ar r ;;
            status)    ar s ;;
            calibrate) ar c ;;
            path)
                printf "Вставь ссылку (URL / Яндекс.Диск / YouTube) или путь к файлу: "
                read -r _src
                if [ -z "$_src" ]; then echo "отменено — назад в меню"; continue; fi
                autoreels menu --classify "$_src"     # покажет, что распознано
                ar run "$_src"
                ;;
            transcribe)
                printf "Что транскрибировать — ссылка (URL / Яндекс.Диск) или путь к файлу: "
                read -r _src
                if [ -z "$_src" ]; then echo "отменено — назад в меню"; continue; fi
                autoreels menu --classify "$_src"     # покажет, что распознано
                ar t "$_src"
                ;;
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
        t)
            # ar t <видео|аудио|url>: транскрибация для контента
            shift
            autoreels transcribe "$@"
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
