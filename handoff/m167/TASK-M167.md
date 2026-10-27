# TASK M167 (окно MAIN, Mac): правка по m166 — время слова одно для плана и проверки рендера

Замер m166 по трём клипам m163, отброшенным рендером:
- **11h42 r02 («first word cut»).** Начало планового клипа стоит на пред-ролле от начала слова по выравниванию (125.381). Рендер сверял его с сырой картой речи (125.180), а карта отдала склеенное начало предыдущему слову. Ошибка проверки: она смотрела не на то время слова, что план. Патч: план записывает в клип начало первого слова по своему промежутку (`head_first_word_start`), рендер сверяет с ним.
- **10h59 r13, r15 («last word cut»).** Конец последнего слова по выравниванию (1681.339 / 341.424) позже начала следующей речи (1680.830 / 341.050). Сыграть слово целиком и при этом кончить до следующей речи нельзя (инвариант 10), план это предупреждал («no room after last word»). Это не ложное срабатывание. Патч: автоматический клип с таким концом отклоняется при `--apply`, проверка строки автомонтажа берёт другой конец. У клипа владельца — по-прежнему предупреждение (инвариант 5).
- Тесты `tests/test_m166_edges.py` (3), REEL_SPEC.

## Правила
1. Шаг упал → **СТОП**.
2. pytest — без рендера на Mac. Черновики m163 двух источников пересоздаются тем же тегом. Ответ сценариста берётся из кэша, так что платно только судьи и посты, центы.

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels (auto|render)" || echo "свободно"
bash handoff/bin/take.sh m167
git apply --check handoff/m167/m167-edges.patch && git apply handoff/m167/m167-edges.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests docs && git commit -m "Plan/render (M166): the first word checked by the plan's own span; an automatic clip with no room after its last word is refused at --apply (m163 10h59 r13/r15, 11h42 r02)" && git push && git log --oneline -1
```

## Шаг 2. Два источника заново в тот же гейт m163
```bash
for S in "2026-08-08 10h 59m 38s" "2026-08-08 11h 42m 49s"; do mkdir -p "$HOME/.Trash/autoreels-m167/$S"; mv "reels-out/$S/_gate/m163" "$HOME/.Trash/autoreels-m167/$S/"; done
.venv/bin/python -m autoreels auto "2026-08-08 10h 59m 38s" "2026-08-08 11h 42m 49s" --gate m163 --tag m163 --encoder hevc_videotoolbox > handoff/m167/auto.txt 2>&1
sed -n '/=== auto: итог/,$p' handoff/m167/auto.txt | tee handoff/m167/itog.txt
grep -nE "\[ERROR\]|no room|automatic clip needs another end" handoff/m167/auto.txt | head -20 | tee handoff/m167/errors.txt
for S in "2026-08-08 10h 59m 38s" "2026-08-08 11h 42m 49s"; do d="reels-out/$S/_gate/m163"; echo "$S: клипов $(ls "$d"/r*.mp4 2>/dev/null | grep -vc ERROR), с ошибкой $(ls "$d"/*ERROR* 2>/dev/null | wc -l | tr -d ' '), постов $(ls "$d"/r*.post.txt 2>/dev/null | wc -l | tr -d ' ')"; done | tee handoff/m167/clips.txt
```
Ожидается: у обоих источников «с ошибкой 0». Строки «automatic clip needs another end» возможны — так проверка строки отклоняет клип без места после слова, и он заменяется. Если `ERROR.mp4` остались — СТОП, `errors.txt` в отчёт.

## Шаг 3. Отчёт
`handoff/m167/REPORT.md`: коммит, pytest, `itog.txt`, `errors.txt`, `clips.txt`.
`bash handoff/bin/report.sh m167 itog.txt errors.txt clips.txt`
Владельцу — одна строка: «10h59 и 11h42 пересобраны без клипов с ошибкой; листы на прежних местах (_gate/m163)».
