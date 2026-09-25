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
# Подменю «Настройки рендера» (пункт 8): профиль / палитра / музыка / звук. Цикл до «Назад».
# Один и тот же CRLF-фикс, что и в _ar_menu: чистим захват --resolve-setting и введённые цифры.
_ar_settings() {
    while true; do
        _ar_cli menu --settings
        printf "Настройка [цифра, Enter — назад]: "
        read -r _s || return 0          # EOF (пайп исчерпан) → назад, не крутить пустой цикл
        _s="$(printf '%s' "$_s" | tr -d '\r')"
        _sact="$(_ar_cli menu --resolve-setting "$_s" | tr -d '\r\n')"
        case "$_sact" in
            profile)
                _ar_cli menu --profiles
                printf "Профиль (цифра): [1] hevc [2] hevc_hq [3] h264 [4] h264_hq [5] hevc_sw [6] av1, Enter — отмена: "
                read -r _p; _p="$(printf '%s' "$_p" | tr -d '\r')"
                case "$_p" in
                    1|hevc)     _ar_cli menu --set-profile hevc ;;
                    2|hevc_hq)  _ar_cli menu --set-profile hevc_hq ;;
                    3|h264)     _ar_cli menu --set-profile h264 ;;
                    4|h264_hq)  _ar_cli menu --set-profile h264_hq ;;
                    5|hevc_sw)  _ar_cli menu --set-profile hevc_sw ;;
                    6|av1)      _ar_cli menu --set-profile av1 ;;
                    "")         echo "отменено" ;;
                    *)          echo "  неизвестный выбор: $_p" ;;
                esac
                ;;
            palette)
                _ar_cli menu --palettes
                printf "Палитра (цифра): [1] neutral [2] vivid [3] soft [4] sharp, Enter — отмена: "
                read -r _pal; _pal="$(printf '%s' "$_pal" | tr -d '\r')"
                case "$_pal" in
                    1|neutral)  _ar_cli menu --set-palette neutral ;;
                    2|vivid)    _ar_cli menu --set-palette vivid ;;
                    3|soft)     _ar_cli menu --set-palette soft ;;
                    4|sharp)    _ar_cli menu --set-palette sharp ;;
                    "")         echo "отменено" ;;
                    *)          echo "  неизвестный выбор: $_pal" ;;
                esac
                ;;
            music)
                _ar_cli menu --music-tracks
                printf "Музыка: имя трека из списка, [off] выключить, Enter — отмена: "
                read -r _mus; _mus="$(printf '%s' "$_mus" | tr -d '\r')"
                [ -n "$_mus" ] && _ar_cli menu --set-music "$_mus"
                ;;
            audio)
                printf "Нормализация громкости [on/off], Enter — отмена: "
                read -r _au; _au="$(printf '%s' "$_au" | tr -d '\r')"
                case "$_au" in
                    on|off)     _ar_cli menu --set-audio "$_au" ;;
                    "")         echo "отменено" ;;
                    *)          echo "  введите on или off" ;;
                esac
                ;;
            back|"") return 0 ;;
            *) [ -n "$_s" ] && echo "  неизвестный пункт: $_s" ;;
        esac
        printf "\n[Enter] — к настройкам… "; read -r _
    done
}

_ar_menu() {
    while true; do
        _ar_cli menu
        printf "Выбор [цифра, Enter — обновить]: "
        read -r _choice || break        # EOF (пайп исчерпан) → выйти, не крутить пустой цикл
        # Windows Git Bash: Python-stdout приходит с CRLF; $() срезает только \n, оставляя \r —
        # тогда $_action = "palette\r" и НИ ОДНА ветка case не матчится (меню «ничего не делает»).
        # tr -d '\r' убирает CR → токен чистый на всех платформах. Так же чистим введённую цифру.
        _choice="$(printf '%s' "$_choice" | tr -d '\r')"
        _action="$(_ar_cli menu --resolve "$_choice" | tr -d '\r\n')"
        case "$_action" in
            go)        arl go ;;
            go_render) arl run --render ;;
            render)
                printf "Рендер: [Enter] — все рилы  или spec (r03 / 3 / 3-5): "
                read -r _reels_spec; _reels_spec="$(printf '%s' "$_reels_spec" | tr -d '\r')"
                if [ -z "$_reels_spec" ]; then
                    arl r
                else
                    arl r --reels "$_reels_spec"
                fi
                ;;
            status)    arl s ;;
            calibrate) arl c ;;
            resnap)    arl rs ;;
            diagnose)  arl dc ;;
            dumpclips) arl dump-clips ;;
            review_export)
                # Список манифестов (без сайдкаров) → пользователь выбирает номер
                _manifests=()
                while IFS= read -r _mf; do
                    [ -n "$_mf" ] && _manifests+=("$_mf")
                done < <(find "$_AR_ROOT/manifests" -maxdepth 1 -name "*.json" 2>/dev/null \
                    | grep -v '\.\(blocks\|discarded\|topk_cut\)\.' | sort)
                if [ "${#_manifests[@]}" -eq 0 ]; then
                    echo "manifests/ пуст — сначала запустите анализ (пункт 1)"
                else
                    for _i in "${!_manifests[@]}"; do
                        printf "  %d) %s\n" "$((_i+1))" "$(basename "${_manifests[$_i]}")"
                    done
                    printf "Выбери манифест [1-%d], Enter — отмена: " "${#_manifests[@]}"
                    read -r _n; _n="$(printf '%s' "$_n" | tr -d '\r')"
                    if [ -z "$_n" ]; then echo "отменено — назад в меню"; continue; fi
                    _idx=$((_n - 1))
                    if [ "$_idx" -ge 0 ] && [ "$_idx" -lt "${#_manifests[@]}" ]; then
                        printf "Формат: [1] подробный (редактор)  [2] компактный (вставить в чат): "
                        read -r _fmt; _fmt="$(printf '%s' "$_fmt" | tr -d '\r')"
                        case "$_fmt" in
                            2|compact) _ar_cli blocks "${_manifests[$_idx]}" --review --compact ;;
                            *)         _ar_cli blocks "${_manifests[$_idx]}" --review ;;
                        esac
                    else
                        echo "  неизвестный номер: $_n"
                    fi
                fi
                ;;
            review_apply)
                # Список review-файлов → пользователь выбирает номер → apply + install
                _reviews=()
                while IFS= read -r _rf; do
                    [ -n "$_rf" ] && _reviews+=("$_rf")
                done < <(find "$_AR_ROOT/reviews" -maxdepth 1 -name "*.review.md" 2>/dev/null | sort)
                if [ "${#_reviews[@]}" -eq 0 ]; then
                    echo "reviews/ пуст — сначала экспортируйте (пункт 14)"
                else
                    for _i in "${!_reviews[@]}"; do
                        printf "  %d) %s\n" "$((_i+1))" "$(basename "${_reviews[$_i]}")"
                    done
                    printf "Выбери файл ревью [1-%d], Enter — отмена: " "${#_reviews[@]}"
                    read -r _n; _n="$(printf '%s' "$_n" | tr -d '\r')"
                    if [ -z "$_n" ]; then echo "отменено — назад в меню"; continue; fi
                    _idx=$((_n - 1))
                    if [ "$_idx" -ge 0 ] && [ "$_idx" -lt "${#_reviews[@]}" ]; then
                        _ar_cli blocks --apply "${_reviews[$_idx]}" --install
                    else
                        echo "  неизвестный номер: $_n"
                    fi
                fi
                ;;
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
            settings)  _ar_settings ;;
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
#   arl doctor    → преflight окружения: .env, ключи, провайдеры, ffmpeg, git, каталоги
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
