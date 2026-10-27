# TASK M168 (окно MAIN, Mac): строку без места после последнего слова — укоротить, а не выбросить

m167 правильно отклоняет автоматический клип, у которого последнее слово кончается позже начала следующей речи. Но строка сценариста при этом выбрасывается целиком: у 10h59 было 13 клипов, стало 8 (ушли r13 и r15 и ещё строки с тем же концом). Патч: такая строка кончается на одну фразу раньше — до двух раз, пока клип не короче `min_sec` — и проверяется заново. Крючок, ключевые слова и крупный план на убранной фразе уходят вместе с ней. Тест в `tests/test_m166_edges.py`, REEL_SPEC.

## Правила
1. Шаг упал → **СТОП**.
2. pytest — без рендера на Mac. Ответ сценариста — из кэша, платно только судьи и посты (центы).

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels (auto|render)" || echo "свободно"
bash handoff/bin/take.sh m168
git apply --check handoff/m168/m168-shorten.patch && git apply handoff/m168/m168-shorten.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests docs && git commit -m "Autocut (M168): a line with no room after its last word ends one sentence earlier (twice at most, ≥ min_sec) and is checked again — not dropped (m167: 10h59 13 → 8 clips)" && git push && git log --oneline -1
```

## Шаг 2. 10h59 и 11h42 заново в тот же гейт m163
```bash
for S in "2026-08-08 10h 59m 38s" "2026-08-08 11h 42m 49s"; do mkdir -p "$HOME/.Trash/autoreels-m168/$S"; mv "reels-out/$S/_gate/m163" "$HOME/.Trash/autoreels-m168/$S/"; done
.venv/bin/python -m autoreels auto "2026-08-08 10h 59m 38s" "2026-08-08 11h 42m 49s" --gate m163 --tag m163 --encoder hevc_videotoolbox > handoff/m168/auto.txt 2>&1
sed -n '/=== auto: итог/,$p' handoff/m168/auto.txt | tee handoff/m168/itog.txt
grep -nE "кончается фразой раньше|no room|\[ERROR\]" handoff/m168/auto.txt | head -20 | tee handoff/m168/short.txt
for S in "2026-08-08 10h 59m 38s" "2026-08-08 11h 42m 49s"; do d="reels-out/$S/_gate/m163"; echo "$S: клипов $(ls "$d"/r*.mp4 2>/dev/null | grep -vc ERROR), с ошибкой $(ls "$d"/*ERROR* 2>/dev/null | wc -l | tr -d ' '), постов $(ls "$d"/r*.post.txt 2>/dev/null | wc -l | tr -d ' ')"; done | tee handoff/m168/clips.txt
```
Ожидается: «с ошибкой 0»; клипов у 10h59 больше 8, у 11h42 не меньше 6; в `short.txt` — строки «кончается фразой раньше».

## Шаг 3. Отчёт
`handoff/m168/REPORT.md`: коммит, pytest, `itog.txt`, `short.txt`, `clips.txt`.
`bash handoff/bin/report.sh m168 itog.txt short.txt clips.txt`
Владельцу — одна строка: «10h59: было 8, стало N клипов, 11h42: M; ошибок 0».
