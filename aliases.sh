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
        # Windows Git Bash: Python-stdout приходит с CRLF; $() срезает только \n, оставляя \r —
        # тогда $_action = "palette\r" и НИ ОДНА ветка case не матчится (меню «ничего не делает»).
        # tr -d '\r' убирает CR → токен чистый на всех платформах. Так же чистим введённую цифру.
        _choice="$(printf '%s' "$_choice" | tr -d '\r')"
        _action="$(_ar_cli menu --resolve "$_choice" | tr -d '\r\n')"
        case "$_action" in
            go)        arl go ;;
            render)    arl r ;;
            status)    arl s ;;
            calibrate) arl c ;;
            resnap)    arl rs ;;
            diagnose)  arl dc ;;
            path)
                printf "Вставь ссылку (URL / Яндекс.Диск / YouTube) или путь к файлу: "
                read -r _src
                if [ -z "$_src" ]; then echo "отменено — назад в меню"; continue; fi
                _ar_cli menu --classify "$_src"     # покажет, что распознано
                arl run "$_src"
                ;;
            transcribe)
                printf "Что транскрибировать — ссылка (URL / Яндекс.Диск) или путь к файлу: "
                read -r _src
                if [ -z "$_src" ]; then echo "отменено — назад в меню"; continue; fi
                _ar_cli menu --classify "$_src"     # покажет, что распознано
                arl t "$_src"
                ;;
            resume)    _ar_cli resume ;;
            profile)
                _ar_cli menu --profiles
                printf "Профиль (имя или цифра): [1] hevc [2] hevc_hq [3] h264 [4] h264_hq [5] hevc_sw [6] av1, Enter — отмена: "
                read -r _p
                case "$_p" in
                    1|hevc)     _ar_cli menu --set-profile hevc ;;
                    2|hevc_hq)  _ar_cli menu --set-profile hevc_hq ;;
                    3|h264)     _ar_cli menu --set-profile h264 ;;
                    4|h264_hq)  _ar_cli menu --set-profile h264_hq ;;
                    5|hevc_sw)  _ar_cli menu --set-profile hevc_sw ;;
                    6|av1)      _ar_cli menu --set-profile av1 ;;
                    "") echo "отменено — назад в меню"; continue ;;
                    *) echo "  неизвестный выбор: $_p"; continue ;;
                esac
                ;;
            palette)
                _ar_cli menu --palettes
                printf "Палитра (имя или цифра): [1] neutral [2] vivid [3] soft [4] sharp, [p] превью-сравнение, Enter — отмена: "
                read -r _pal
                case "$_pal" in
                    1|neutral) _ar_cli menu --set-palette neutral ;;
                    2|vivid)   _ar_cli menu --set-palette vivid ;;
                    3|soft)    _ar_cli menu --set-palette soft ;;
                    4|sharp)   _ar_cli menu --set-palette sharp ;;
                    p|preview)
                        printf "Манифест (имя/стем, Enter — первый): "
                        read -r _mf
                        printf "Палитры через запятую (Enter — все пресеты): "
                        read -r _pals
                        if [ -n "$_pals" ]; then arl preview "$_mf" --palettes "$_pals"; else arl preview "$_mf"; fi
                        ;;
                    "") echo "отменено — назад в меню"; continue ;;
                    *) echo "  неизвестный выбор: $_pal"; continue ;;
                esac
                ;;
            help)      arl h ;;
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

# arl: активировать venv проекта (если ещё не активен), затем диспетчер команд.
# Mac/Linux: .venv/bin/activate   Windows Git Bash: .venv/Scripts/activate
#
# КОРОТКИЕ КОМАНДЫ:
#   arl           → интерактивное меню (цифрами)
#   arl menu      → то же меню
#   arl go        → run всех видео + git push манифестов (Mac, нужен Groq; git pull перед стартом)
#   arl go --no-push → run без git push
#   arl r         → render (git pull внутри; блокирует рендер устаревшего кропа) (системник)
#   arl pv [ман] [--palettes n,v,s] → preview: короткий фрагмент в нескольких палитрах (подбор цветокора)
#   arl rc [вид]  → recrop: обновить кроп в манифесте по свежей калибровке (без пересчёта R0)
#   arl s         → status
#   arl c         → calibrate --all (пушит калибровки → на Mac arl run)
#   arl rs [видео]   → resnap: пересчитать границы клипов из R0-границ (snap/padding, без LLM)
#   arl dc [--rerun] → diagnose-cuts: проверка обрывов фраз (CLEAN/SOFT/HARD + причина)
#   arl t <ист>   → transcribe (видео/аудио/url → текст для контента)
#   arl h         → help
#   arl <...>     → передать в autoreels напрямую
arl() {
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
            # arl / arl menu → интерактивное меню
            _ar_menu
            ;;
        go)
            # arl go [--no-push]: run всех видео. Каждый успешный манифест коммитится+пушится
            # СРАЗУ (per-video, внутри Python) — упади прогон на середине, уже готовые
            # манифесты уже на системнике. --no-push отключает. Push-логика — в cmd_run,
            # не здесь: раньше shell-push в конце терялся при любом упавшем видео (|| return).
            shift
            _ar_cli run "$@"
            ;;
        r)
            # arl r: render (git pull делается ВНУТРИ render — подтягивает свежие манифесты
            # и блокирует рендер устаревшего кропа). Энкодер из config/render.yaml.
            shift
            _ar_cli render "$@"
            ;;
        pv)
            # arl pv [манифест] [--palettes n,v,s]: короткий фрагмент в нескольких палитрах
            # (подбор цветокора без полного рендера всех клипов) → reels-out/_preview/
            shift
            _ar_cli preview "$@"
            ;;
        s)
            _ar_cli status
            ;;
        c)
            _ar_cli calibrate --all
            ;;
        rc)
            # arl rc [видео]: обновить кроп в манифесте по свежей калибровке (без пересчёта R0)
            shift
            _ar_cli recrop "$@"
            ;;
        rs)
            # arl rs [видео]: пересчитать границы клипов из R0-границ (snap/padding, без LLM)
            shift
            _ar_cli resnap "$@"
            ;;
        dc)
            # arl dc [видео] [--rerun]: диагностика обрывов фраз по клипам
            shift
            _ar_cli diagnose-cuts "$@"
            ;;
        t)
            # arl t <видео|аудио|url>: транскрибация для контента
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
