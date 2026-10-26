# TASK M157 (окно MAIN, Mac): всё на Sonnet, пока есть промо-кредиты, — карты заново и второй прогон всех источников

Файлы — ветка `handoff`, папка `handoff/m157/`: `TASK-M157.md`, `m157-paid-window.patch`. Долго: семь карт на Sonnet и рендер всех клипов. Платно, но из промо-кредитов.

## Зачем
Владелец 2026-10-26: «все остальные так же прогоним через промо-кредиты». В Console 95,96 $ промо, они истекают 03.11.2026 и тратятся на API раньше карты. В m154 на Sonnet шли только сценарист и судьи, карта мыслей и посты — на бесплатных моделях.

Патч:
- `autocut.paid_llm: sonnet`, `autocut.paid_until: "2026-11-02"`. До этой даты `arl auto` без `--llm` ведёт карту, судей и посты на Sonnet. После неё `arl auto` бесплатный, сценарист — только по `--mode scenario`: после промо платная модель шла бы с карты через автопополнение. Явный `--llm` главнее.
- `arl auto --tag <имя>` — черновики и review.json прогона под своими именами. Черновики листов m154 и их файлы решений (строка `# review:`) не перезаписываются.
- Тесты `tests/test_m157_paid_window.py` (7), `_stub` в `tests/test_auto.py` выключает окно (иначе тесты зависят от даты). Документация — README, PLAN, CLAUDE.md.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. `--install` не запускать, `reviews/*_answer*.txt` и `manifests/` не трогать. Черновики m154 (`reviews/<ист>_auto_m56.txt`, `_auto_all.txt`) не трогать: прогон идёт с `--tag m157`.
3. pytest — только когда на Mac не идёт рендер. Старый ручной манифест `PXL_20260729_085910095_34f06abf` не брать (его исходника нет).

## Шаг 1. Патч, тесты, коммит
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m157; mkdir -p handoff/m157/maps_before
git apply --check handoff/m157/m157-paid-window.patch && git apply handoff/m157/m157-paid-window.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests config README.md PLAN.md CLAUDE.md && git commit -m "Auto (M157): the paid window — until autocut.paid_until (promo credits) arl auto runs map, judges and posts on paid_llm, free after it; --tag keeps an earlier sheet's drafts" && git push && git log --oneline -1
```
Ожидается: `applied`, pytest — все прошли, коммит запушен.

## Шаг 2. Карты мыслей заново на Sonnet
```bash
S7=("2026-08-08 09h 33m 14s" "2026-08-08 10h 59m 38s" "2026-08-08 11h 42m 49s" IMG_6848 "Pxl 20260621 112938952" "Pxl 20260621 122006193" PXL_20260729_copy)
for S in "${S7[@]}"; do cp "transcripts/$S.map.json" handoff/m157/maps_before/ 2>/dev/null; done; ls handoff/m157/maps_before | wc -l
for S in "${S7[@]}"; do
  arl map "$S" --force --llm sonnet > "handoff/m157/map.$S.txt" 2>&1; echo "$S map rc=$?"; grep -E "мысл|тем|Claude|✗|неполн" "handoff/m157/map.$S.txt" | tail -3
done 2>&1 | tee handoff/m157/maps.txt
```
Ожидается: `rc=0` у каждого. Если карта неполна (`rc=3`), запустить `arl map "$S" --llm sonnet` ещё раз без `--force`: дозапросит недостающее. Опять неполна — источник в отчёт, прогон шага 3 для него всё равно идёт (`arl auto` остановится на «map» и назовёт причину).

## Шаг 3. Прогон всех источников (в фоне)
```bash
nohup .venv/bin/python -m autoreels auto "${S7[@]}" --gate m157 --tag m157 --encoder hevc_videotoolbox > handoff/m157/auto.txt 2>&1 &
echo "pid $!"
```
В начале `auto.txt` должны быть строки «карта, судьи и посты — sonnet (до 2026-11-02 включительно)» и «ролики пишет сценарист (sonnet, платно)». Проверять раз в 5–10 минут (`tail -5 handoff/m157/auto.txt`) до строки `=== auto: итог`.

## Шаг 4. Сводка
```bash
sed -n '/=== auto: итог/,$p' handoff/m157/auto.txt | tee handoff/m157/itog.txt
grep -hE "Claude .*≈ \\$" handoff/m157/map.*.txt handoff/m157/auto.txt | tee handoff/m157/cost.txt | awk -F'≈ \\$' '{s+=$2} END {printf "ИТОГО ≈ $%.2f\n", s}' | tee -a handoff/m157/cost.txt
for d in reels-out/*/_gate/m157; do echo "$d: $(ls "$d"/r*.mp4 2>/dev/null | wc -l) клипов (m154: $(ls "${d%m157}m154"/r*.mp4 2>/dev/null | wc -l)), лист: $([ -f "$d/_review.html" ] && echo есть || echo НЕТ)"; done | tee handoff/m157/clips.txt
ls reviews/*_auto_all.txt reviews/*_auto_m56.txt | head -20 > /dev/null && echo "черновики m154 на месте"
```

## Шаг 5. Отчёт
`handoff/m157/REPORT.md`: коммит, pytest, `maps.txt`, `itog.txt`, `clips.txt`, `cost.txt` (итог в $).
`bash handoff/bin/report.sh m157 maps.txt itog.txt clips.txt cost.txt`
Владельцу — по строке на источник (клипов m157 против m154, путь листа `reels-out/<ист>/_gate/m157/_review.html`) и итоговая стоимость.

Статус: IMPLEMENTED, GATE PENDING.
