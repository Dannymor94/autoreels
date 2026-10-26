# TASK M149b (окно MAIN, Mac): проверить `speech_map` на настоящем сравнении

Файлы — ветка `handoff`, папка `handoff/m149b/`: `TASK-M149B.md`, `ab2.py`. Около 30 минут, без патча и без платных моделей.

## Зачем
В m149 флаг включён по правилу «источников хуже 0». Но сравнивать было нечего: ни один старый файл ответа не дал пары, сравнено 0 клипов. Правило выполнилось вхолостую. Ошибка в задаче (не проверено, что сравнение непустое), не у агента. Карты у всех 8 источников построены — это остаётся. Теперь сравнение на черновиках автомонтажа `reviews/<S>_auto_m144-on.txt`: они в текущем формате, со строкой `# source:`. Каждый черновик применяется с флагом выключенным и включённым. `ab2.py` при пустом сравнении завершается с кодом 2.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. `--install`, `arl auto` не запускать. `reviews/<S>.review.json` сохраняется и возвращается. `config/render.yaml` во время замера возвращается `git checkout`.
3. Рендер один за раз, pytest не нужен (кроме шага 3, если флаг выключается).

## Шаг 1. Черновики: флаг выключен / включён
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m149b; mkdir -p handoff/m149b; : > handoff/m149b/pairs.txt
grep -n '^speech_map:' config/render.yaml
for D in reviews/*_auto_m144-on.txt; do S=$(basename "$D" _auto_m144-on.txt); [ "$S" = PXL_20260729_copy ] && continue; printf '%s\t%s\n' "$S" "$S" >> handoff/m149b/pairs.txt; done
cat handoff/m149b/pairs.txt
ab() {  # ab <state>
  while IFS=$'\t' read -r T S; do
    R="reviews/$S.review.json"; B="handoff/m149b/$S.review.json.before"; rm -f "$B"; [ -f "$R" ] && cp "$R" "$B"
    arl blocks --apply "reviews/${S}_auto_m144-on.txt" --labeler auto > "handoff/m149b/apply.$1.$T.txt" 2>&1; rc=$?; echo "$1 $T rc=$rc"
    rm -f "reviews/${S}_m149b$1.review.json"; [ $rc = 0 ] && [ -f "$R" ] && cp "$R" "reviews/${S}_m149b$1.review.json"
    if [ -f "$B" ]; then cp "$B" "$R" && cmp -s "$B" "$R" || echo "!! $R не возвращён"; else rm -f "$R"; fi
  done < handoff/m149b/pairs.txt
}
sed -i '' 's/^speech_map: .*/speech_map: false/' config/render.yaml; ab before
git checkout config/render.yaml; grep -n '^speech_map:' config/render.yaml; ab on
git diff --stat config/
.venv/bin/python handoff/m149b/ab2.py 2>&1 | tee handoff/m149b/ab.txt | tail -2; echo "ab2 rc=${PIPESTATUS[0]}"
cat handoff/m149b/render_list.txt
```
Ожидается: в `pairs.txt` 6–7 источников. Перед `ab on` — `speech_map: true` (с M149). `rc=0` в обоих состояниях у каждого. Строк «!! не возвращён» нет, `git diff --stat config/` пуст. `ab2 rc=0`, в строке `=== ВСЕГО` клипов > 0.

## Шаг 2. Решение (агент применяет сам)
Флаг **остаётся включённым**, если одновременно:
- `ab2 rc=0`;
- сравнено не меньше 4 источников;
- «источников хуже 0»: с флагом не меньше клипов и не больше ошибок apply.

Иначе флаг выключается (шаг 3).

## Шаг 3. Только если правило не выполнено
```bash
sed -i '' 's/^speech_map: .*/speech_map: false/' config/render.yaml
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add config/render.yaml && git commit -m "Render (M149b): speech_map off again — m149b drafts off/on: <причина>; maps stay built" && git push && git log --oneline -1
```
В PLAN, в строке `speech_map`, заменить запись M149 на «выключен снова (m149b: причина); карты у всех источников построены». Коммит `Docs (M149b): …`, push.

## Шаг 4. Гейт для ушей (если флаг остался и `render_list.txt` не пуст)
```bash
while IFS=$'\t' read -r S L; do
  arl render --manifest "reviews/${S}_m149bon.review.json" --reels "$L" --gate m149 --encoder hevc_videotoolbox 2>&1 | tail -2
done < handoff/m149b/render_list.txt
sed -i '' 's/^speech_map: .*/speech_map: false/' config/render.yaml
while IFS=$'\t' read -r S L; do
  arl render --manifest "reviews/${S}_m149bbefore.review.json" --reels "$L" --gate m149off --encoder hevc_videotoolbox 2>&1 | tail -2
done < handoff/m149b/render_list.txt
git checkout config/render.yaml; git diff --stat config/
ls reels-out/*/_gate/m149/r*.mp4 reels-out/*/_gate/m149off/r*.mp4 | tee handoff/m149b/clips.txt
```
Ожидается: рендер без `[ERROR]`, `git diff --stat config/` пуст.

## Шаг 5. Отчёт
`handoff/m149b/REPORT.md`: `ab.txt` целиком, решение (с числами), коммиты, `clips.txt`.
`bash handoff/bin/report.sh m149b ab.txt render_list.txt clips.txt`
Владельцу — две строки:
- «speech_map: оставлен / выключен — сравнено N источников, M клипов, изменилось K»;
- «по желанию: _gate/m149off (без флага) и _gate/m149 (с флагом)».

Статус: IMPLEMENTED, GATE PENDING.
