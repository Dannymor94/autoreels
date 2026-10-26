# TASK M162 (окно MAIN, Mac): новые видео — сценаристом до листа ревью, рендер на Mac

Владелец 2026-10-26: «запускаем рендер на Mac всех видео со сценаристом — тех, что ещё не рендерили». Семь известных источников уже прошли m154/m157, поэтому сначала находятся видео, которых нет ни в одном манифесте (по содержимому). Потом они идут через `arl auto`: расшифровка Groq, карта, сценарист, проверки и посты на Sonnet (промо до 02.11), рендер на Mac, лист ревью.

## Правила
1. Шаг упал → **СТОП**: шаг, команда, последние 40 строк.
2. `--install` не запускать; `manifests/` меняется только `arl run` для новых видео (новые манифесты), старые не трогать; `reviews/*_answer*.txt` не трогать.
3. Рендер один; pytest во время рендера не запускать.

## Шаг 1. Какие видео новые
```bash
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m162
.venv/bin/python handoff/m162/find_new.py 2>&1 | tee handoff/m162/find.txt
```
Ожидается строка `=== новых видео: N`.
- **N = 0** — СТОП (не ошибка): владельцу «новых видео нет в inputs/, inputs-archive/ и папках прежних исходников (список из find.txt); где лежат новые?». Если какая-то папка «нет папки (диск не подключён?)» — назвать её.
- **N > 0** — список в отчёт и дальше.

## Шаг 2. Прогон (в фоне)
```bash
mapfile -t NEW < handoff/m162/new.txt 2>/dev/null || IFS=$'\n' read -d '' -r -a NEW < handoff/m162/new.txt
printf '%s\n' "${NEW[@]}"
nohup .venv/bin/python -m autoreels auto "${NEW[@]}" --gate m162 --tag m162 --encoder hevc_videotoolbox > handoff/m162/auto.txt 2>&1 &
echo "pid $!"
```
В начале `auto.txt`: «карта, судьи и посты — sonnet (до 2026-11-02 включительно)» и «ролики пишет сценарист (sonnet, платно)». Проверять раз в 10 минут (`tail -5 handoff/m162/auto.txt`) до `=== auto: итог`. Расшифровка новых видео идёт через Groq и может ждать лимитов — это не СТОП.

## Шаг 3. Сводка
```bash
sed -n '/=== auto: итог/,$p' handoff/m162/auto.txt | tee handoff/m162/itog.txt
grep -hE "Claude .*≈ \\$" handoff/m162/auto.txt | awk -F'≈ \\$' '{s+=$2} END {printf "ИТОГО ≈ $%.2f\n", s}' | tee handoff/m162/cost.txt
for d in reels-out/*/_gate/m162; do echo "$d: $(ls "$d"/r*.mp4 2>/dev/null | wc -l) клипов, лист: $([ -f "$d/_review.html" ] && echo есть || echo НЕТ)"; done | tee handoff/m162/clips.txt
```

## Шаг 4. Отчёт
`handoff/m162/REPORT.md`: `find.txt`, `itog.txt`, `clips.txt`, `cost.txt`.
`bash handoff/bin/report.sh m162 find.txt itog.txt clips.txt cost.txt`
Владельцу — по строке на новое видео: клипов и путь листа `reels-out/<ист>/_gate/m162/_review.html`; стоимость.

Статус: IMPLEMENTED, GATE PENDING.
