# TASK M154 (окно MAIN, Mac): все источники — сценаристом через `arl auto`

Нужен M153 (сценарист по умолчанию). Платно: один запрос Sonnet на источник (ответ кэшируется). Долго: рендер всех клипов. Рендер один, pytest во время задачи не запускать.

## Источники
Семь: три лекции 2026-08-08, IMG_6848, оба Pxl 20260621 и **`PXL_20260729_copy`**. PXL теперь — сжатая копия; несжатого оригинала нет. Старый ручной манифест `PXL_20260729_085910095_34f06abf` **не брать**: его исходника нет, манифест не трогать.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. `--install` не запускать, `reviews/*_answer*.txt` и `manifests/` не трогать. Источник, остановленный на этапе, — не СТОП: итог `arl auto` его назовёт, остальные идут дальше.

## Шаг 1. Проверки и резервная копия review.json
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m154; mkdir -p handoff/m154/before
grep -n "^  auto_mode: scenario" config/r0.yaml || echo "НЕТ M153 — СТОП"
grep -q "ANTHROPIC_API_KEY" .env && echo "ключ Claude есть" || echo "КЛЮЧА НЕТ — СТОП"
cp reviews/*.review.json handoff/m154/before/ 2>/dev/null; ls handoff/m154/before | wc -l
git status --short manifests/ > handoff/m154/manifests.before
```
Ожидается: строка `auto_mode: scenario`, «ключ Claude есть».

## Шаг 2. Прогон (в фоне, долго)
```bash
nohup .venv/bin/python -m autoreels auto "2026-08-08 09h 33m 14s" "2026-08-08 10h 59m 38s" "2026-08-08 11h 42m 49s" \
  IMG_6848 "Pxl 20260621 112938952" "Pxl 20260621 122006193" PXL_20260729_copy \
  --gate m154 --encoder hevc_videotoolbox > handoff/m154/auto.txt 2>&1 &
echo "pid $!"
```
Проверять раз в 5–10 минут: `tail -5 handoff/m154/auto.txt`. Окончание — строка `=== auto: итог`, после неё ещё 7 строк. Не перезапускать, пока процесс жив (`pgrep -fl "autoreels auto"`).

Если прогон упал целиком (Traceback до итога) — СТОП. Готовые этапы при повторе пропускаются сами, ответ сценариста взят из кэша.

## Шаг 3. Сводка
```bash
sed -n '/=== auto: итог/,$p' handoff/m154/auto.txt | tee handoff/m154/itog.txt
grep -E "ролики пишет|сценарист не ответил|\\$|токен" handoff/m154/auto.txt | sort | uniq -c | tee handoff/m154/cost.txt
for d in reels-out/*/_gate/m154; do echo "$d: $(ls "$d"/r*.mp4 2>/dev/null | wc -l) клипов, лист: $([ -f "$d/_review.html" ] && echo есть || echo НЕТ)"; done | tee handoff/m154/clips.txt
git status --short manifests/ | diff handoff/m154/manifests.before - && echo "manifests без изменений"
```

## Шаг 4. Отчёт
`handoff/m154/REPORT.md`: `itog.txt` и `clips.txt` целиком, стоимость из `cost.txt`. Отдельным пунктом — источники, где сценарист не ответил и был взят автомонтаж.
`bash handoff/bin/report.sh m154 itog.txt cost.txt clips.txt`
Владельцу: по строке на источник — сколько клипов и путь листа `reels-out/<источник>/_gate/m154/_review.html`; итоговая стоимость.

Статус: IMPLEMENTED, GATE PENDING.
