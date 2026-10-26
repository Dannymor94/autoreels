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
- **N = 0** — СТОП (не ошибка): владельцу «новых видео нет в inputs/, inputs-archive/ и папках прежних исходников (список из find.txt); где лежат новые?». Если какая-то папка «нет папки (диск не подключён?)» — назвать её. Шаг 3б (посты для m157) сделать и при N = 0. Шаг 3б (посты для m157) сделать и при N = 0.
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

## Шаг 3б. Пост у каждого клипа (владелец: «у каждого видео должен быть пост») — m157 и m162
Пост — `<клип>.post.txt` рядом с клипом (`arl describe`, M94). `arl auto` пишет посты сам, но ответ, не прошедший проверку, файла не даёт. Поэтому — счёт и дозапись недостающих (готовые не перезаписываются):
```bash
for d in reels-out/*/_gate/m157 reels-out/*/_gate/m162; do
  [ -d "$d" ] || continue; S=$(basename "$(dirname "$(dirname "$d")")"); g=$(basename "$d")
  n=$(ls "$d"/r*.mp4 2>/dev/null | wc -l | tr -d ' '); p=$(ls "$d"/r*.post.txt 2>/dev/null | wc -l | tr -d ' ')
  if [ "$p" -lt "$n" ]; then .venv/bin/python -m autoreels describe "$S" --gate "$g" --llm sonnet > "handoff/m162/describe.$S.$g.txt" 2>&1; fi
  p2=$(ls "$d"/r*.post.txt 2>/dev/null | wc -l | tr -d ' ')
  echo "$S/$g: клипов $n, постов было $p, стало $p2"
  for f in "$d"/r*.mp4; do [ -f "${f%.mp4}.post.txt" ] || echo "   без поста: $(basename "$f")"; done
done | tee handoff/m162/posts.txt
```
Ожидается: у каждого клипа есть пост. Если пост так и не появился («без поста: …»), назвать в отчёте вместе с причиной из `describe.*.txt` (обычно ответ модели не прошёл проверку: слова не из ролика, хэштег не из речи). Это не СТОП.

## Шаг 3б. Мини-пост у каждого клипа — m157 и m162
Владелец: «у каждого видео — полноценный мини-пост о чём видео». Это `<клип>.post.txt` рядом с клипом (`arl describe`, M94): 3–5 предложений о содержании словами самого ролика и хэштеги из сказанного. `arl auto` пишет посты сам, но ответ, не прошедший проверку, файла не даёт. Поэтому здесь — счёт и дозапись недостающих; готовые посты не перезаписываются.
```bash
for d in reels-out/*/_gate/m157 reels-out/*/_gate/m162; do
  [ -d "$d" ] || continue; S=$(basename "$(dirname "$(dirname "$d")")"); g=$(basename "$d")
  n=$(ls "$d"/r*.mp4 2>/dev/null | wc -l | tr -d ' '); p=$(ls "$d"/r*.post.txt 2>/dev/null | wc -l | tr -d ' ')
  if [ "$p" -lt "$n" ]; then .venv/bin/python -m autoreels describe "$S" --gate "$g" --llm sonnet > "handoff/m162/describe.$S.$g.txt" 2>&1; fi
  p2=$(ls "$d"/r*.post.txt 2>/dev/null | wc -l | tr -d ' ')
  echo "$S/$g: клипов $n, постов было $p, стало $p2"
  for f in "$d"/r*.mp4; do [ -f "${f%.mp4}.post.txt" ] || echo "   без поста: $(basename "$f")"; done
done | tee handoff/m162/posts.txt
f=$(ls reels-out/*/_gate/m157/r01.post.txt 2>/dev/null | head -1); echo "--- пример: $f"; cat "$f" | tee -a handoff/m162/posts.txt
```
Ожидается: у каждого клипа есть пост. Если пост так и не появился («без поста: …»), назвать его в отчёте с причиной из `describe.*.txt`; обычно ответ модели не прошёл проверку. Это не СТОП.

## Шаг 4. Отчёт
`handoff/m162/REPORT.md`: `find.txt`, `itog.txt`, `clips.txt`, `posts.txt`, `cost.txt`.
`bash handoff/bin/report.sh m162 find.txt itog.txt clips.txt posts.txt cost.txt`
Владельцу — по строке на новое видео: клипов и путь листа `reels-out/<ист>/_gate/m162/_review.html`; стоимость.

Статус: IMPLEMENTED, GATE PENDING.
