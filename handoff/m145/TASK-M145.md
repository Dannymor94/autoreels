# TASK M145 (окно MAIN, Mac): склеенное начало — чинить, но не выбрасывать клип

Файлы — ветка `handoff`, папка `handoff/m145/`: `TASK-M145.md`, `m145-soft.patch`. Нужны `handoff/m144/drafts_glued.py`, `handoff/m138/owner_drafts.py`, `handoff/m138b/topk.py` и черновики `reviews/*_auto_m144-off.txt`. Около 25 минут, без платных моделей.

## Зачем
m144: правило «перед первым звуком пауза» убрало все склеенные начала (59 → 0), но выбросило клипы, у которых починить начало нечем. Покрытие клипов владельца упало с 40 до 27 из 66. Патч делает правило мягким. Клип, у которого начало само по себе понятное и только склеено, сначала чинится как раньше (мысль перед, более поздняя фраза). Если не вышло, он остаётся со своим началом и пометкой «исправить нельзя, оставлено». У сценариста — фраза-две раньше, иначе остаётся как есть. Тест `test_m145_*`, запись в REEL_SPEC. Флаг тот же: `start_pause_min`, выключен.

## Правила
Как в m144: СТОП при несовпадении; pytest только в шаге 1; новые файлы в `reviews/` — только `*_auto_m145-*.txt` и `IMG_6848_m145.review.json`; `review.json` сохранить и вернуть; `config/r0.yaml` — только по правилу шага 3.

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m145
git apply --check handoff/m145/m145-soft.patch && git apply handoff/m145/m145-soft.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests docs && git commit -m "Autocut (M145): a glued start with no repair keeps its clip, noted (m144: dropping them cut the covered owner clips 40 → 27)" && git push && git log --oneline -1
```
Ожидается: `applied`; pytest — все прошли; коммит запушен.

## Шаг 2. Черновики с мягким правилом (0.15 и 0.10 с) против `m144-off`
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
for mp in manifests/*.json; do
  S=$(basename "$mp" .json)
  case "$S" in *.blocks*|*.discarded*|PXL_20260729_copy) continue;; esac
  [ -f "reviews/${S}_auto_m144-off.txt" ] || continue
  for T in 15 10; do
    arl autocut "$S" --llm none --ac start_pause_min=0.$T --out "reviews/${S}_auto_m145-p$T.txt" > "handoff/m145/run-$S-p$T.txt" 2>&1; echo "$S p$T rc=$?"
  done
done
.venv/bin/python handoff/m144/drafts_glued.py m144-off m145-p15 m145-p10 2>&1 | tee handoff/m145/glued.txt | tail -5
.venv/bin/python handoff/m138/owner_drafts.py m144-off m145-p15 m145-p10 2>&1 | tee handoff/m145/cover.txt | tail -4
.venv/bin/python handoff/m138b/topk.py m144-off m145-p15 m145-p10 2>&1 | tee handoff/m145/topk.txt | tail -4
git status --short | grep -v "^??"
```
Ожидается: строки `rc=0`; итоги `=== ВСЕГО` в трёх файлах; `git status` без изменений в отслеживаемых.

## Шаг 3. Решение и гейт (агент применяет сам)
Из двух порогов взять тот, у которого меньше склеенных начал при покрытии (`cover.txt`) не ниже `m144-off` больше чем на 2.
- Если у него склеенных начал хотя бы на треть меньше, чем у off: `start_pause_min: <0.15|0.10>` в `config/r0.yaml`, коммит `Autocut (M145): start_pause_min <x> on (m145: glued off/on …, covered …)`, push. Затем гейт IMG_6848 для ушей:
  ```bash
  P=<15|10>
  R=reviews/IMG_6848.review.json; B=handoff/m145/IMG_6848.review.json.before; rm -f "$B"; [ -f "$R" ] && cp "$R" "$B"
  arl blocks --apply reviews/IMG_6848_auto_m145-p$P.txt --labeler auto > handoff/m145/apply.txt 2>&1; echo "rc=$?"
  cp "$R" reviews/IMG_6848_m145.review.json
  if [ -f "$B" ]; then cp "$B" "$R" && cmp "$B" "$R" && echo "review.json возвращён"; else rm -f "$R" && echo "review.json не было — убран"; fi
  N=$(.venv/bin/python -c "import json;print(len(json.load(open('reviews/IMG_6848_m145.review.json'))['reels']))"); echo "клипов: $N"
  arl render --manifest reviews/IMG_6848_m145.review.json --reels 1-$N --gate m145 --encoder hevc_videotoolbox 2>&1 | tail -6
  arl review-sheet IMG_6848 --review reviews/IMG_6848_auto_m145-p$P.txt --manifest-file reviews/IMG_6848_m145.review.json --gate m145 --preview none 2>&1 | tail -2
  ```
- Иначе ничего не включать и не рендерить, написать цифры.

## Шаг 4. Отчёт
`handoff/m145/REPORT.md`: коммиты, pytest, итоги трёх файлов, решение, путь листа.
`bash handoff/bin/report.sh m145 glued.txt cover.txt topk.txt`
Владельцу — две строки: «склеенных начал off → on, покрыто …»; «слушать: reels-out/IMG_6848/_gate/m145/_review.html — первая буква слышна? отметь кнопками и скачай решения».

Статус: IMPLEMENTED, GATE PENDING.
