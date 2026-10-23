# TASK M134 (окно MAIN, Mac): «кусок идёт подряд» — по слышимой паузе, а не по зазору Whisper (M1.8)

Файлы — ветка `handoff`, папка `handoff/m134/`: `TASK-M134.md`, `m134.patch`, `measure_blocks.py`.
Около 25 минут, из них ~15 — рендер. Без модели и gamebox.

## Зачем
Владелец взял «карту речи для границ блоков и вырезания пауз». Ассистент сначала замерил (IMG_6848, 10h59):
- **Границы блоков по звуку** (`measure_blocks.py`): из 72 границ IMG_6848 совпали бы 13, у 10h59 — 19 из 92. Сломались бы нумерация `B.k`, отпечатки `*_answer.txt`, карты и черновики. Нарезка блоков — это нумерация, а не решение о клипе, поэтому **отложено**, запись в PLAN.
- **Вырезание пауз** в клипах по плану (ручной путь, автомонтаж) уже идёт по звуку (`plan.py`).
- **Найдено реальное место на зазорах Whisper:** монтаж решает, что кусок «идёт подряд» за предыдущим и играется без стыка (M58), по зазору Whisper `0 ≤ gap ≤ join_gap_sec`. У 65 из 345 концов предложений IMG_6848 зазор отрицательный (слова перекрываются), поэтому такие куски получали лишний стык. Всего решение меняется у 90 из 345 концов (10h59: у 107 из 462).

Патч: флаг `montage.join_heard` (в коде выключен, в `r0.yaml` пока `false`). Пауза считается по карте речи и выравниванию, незаписанная речь считается речью; слово между предложениями означает «не подряд». В патче также записи в PLAN, REEL_SPEC и PROJECT_STRUCTURE (`tools/`, `benchmarks/`).

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить.
2. Других `arl` и рендера во время задачи нет; pytest — только в шаге 1. Если упал только `test_menu_bash.py::test_menu_settings_profile_picker_and_cancel`, перезапустить его один раз.
3. `reviews/<stem>.review.json` до `--apply` сохранить и после вернуть (как в m126). `*_answer.txt`, `manifests/`, чужие гейты не трогать. `--install`, `arl auto`, `arl export` не запускать.
4. `config/r0.yaml` правится только командами из задачи; в конце шага 2 вернуть его как в коммите (`git diff config/r0.yaml` пусто).

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -1; git log --oneline -1; pgrep -fl "arl " || echo "arl не запущен"
git apply --check handoff/m134/m134.patch && git apply handoff/m134/m134.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add -A src tests config docs PLAN.md PROJECT_STRUCTURE.md
git commit -m "Montage (M134): «a piece goes straight on» by the pause heard, not the Whisper gap (montage.join_heard, off); block cutting stays on Whisper by measure (13 of 72 boundaries would move)"
git push; git log --oneline -1
```
Ожидается: `applied`; pytest — все прошли (5 новых в `tests/test_montage_heard_join.py`); коммит запушен.

## Шаг 2. Замер: тот же черновик, флаг выключен и включён
Для двух черновиков сценариста: `IMG_6848` → `reviews/IMG_6848_auto_m126-scen.txt`, `Pxl 20260621 112938952` → `reviews/Pxl 20260621 112938952_auto_m123-scen.txt`.
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m134
.venv/bin/python handoff/m134/measure_blocks.py 2>&1 | tee handoff/m134/blocks.txt | grep -E "^## |boundaries same|skipped"
for S in "IMG_6848" "Pxl 20260621 112938952"; do
  case "$S" in IMG_6848) D="reviews/IMG_6848_auto_m126-scen.txt";; *) D="reviews/${S}_auto_m123-scen.txt";; esac
  R="reviews/$S.review.json"; B="handoff/m134/$S.review.json.before"; rm -f "$B"; [ -f "$R" ] && cp "$R" "$B"
  for J in false true; do
    sed -i '' "s/^  join_heard: .*/  join_heard: $J/" config/r0.yaml
    arl blocks --apply "$D" --labeler auto > "handoff/m134/$S.apply.$J.txt" 2>&1; echo "$S $J rc=$?"
    cp "$R" "reviews/${S}_m134$([ $J = true ] && echo on || echo off).review.json"
  done
  if [ -f "$B" ]; then cp "$B" "$R" && cmp "$B" "$R" && echo "review.json возвращён"; else rm -f "$R" && echo "review.json не было — убран"; fi
done
git checkout config/r0.yaml; git diff --stat config/r0.yaml
.venv/bin/python - <<'PY' | tee handoff/m134/joins.txt
import json, re
for S in ("IMG_6848", "Pxl 20260621 112938952"):
    off = {r["id"]: r for r in json.load(open(f"reviews/{S}_m134off.review.json"))["reels"]}
    on = {r["id"]: r for r in json.load(open(f"reviews/{S}_m134on.review.json"))["reels"]}
    jo = {f: sum(1 for l in open(f"handoff/m134/{S}.apply.{f}.txt") if "go straight on" in l) for f in ("false", "true")}
    er = {f: sum(1 for l in open(f"handoff/m134/{S}.apply.{f}.txt") if "[ERROR]" in l) for f in ("false", "true")}
    print(f"## {S}: clips off/on {len(off)}/{len(on)}; joins off/on {jo['false']}/{jo['true']}; errors off/on {er['false']}/{er['true']}")
    for rid in sorted(set(off) | set(on)):
        a, b = off.get(rid), on.get(rid)
        na = len(a.get("segments") or []) if a else None
        nb = len(b.get("segments") or []) if b else None
        if na != nb:
            print(f"- {rid}: windows {na} → {nb}")
PY
```
Ожидается:
- `blocks.txt`: на всех источниках с транскриптом совпадает меньшинство границ (подтверждение «отложить»); источник без данных — `skipped`, это не СТОП;
- 4 строки `rc=0`, оба `review.json возвращён` (или «убран»), `git diff --stat config/r0.yaml` пуст;
- `joins.txt`: число клипов одинаковое, ошибок с флагом не больше, чем без него; список клипов, где изменилось число окон.

**Правило решения (агент применяет сам):** если с флагом ошибок не больше, клипов столько же, а окон нигде не стало больше, чем без флага плюс один, — включить `join_heard: true` в `config/r0.yaml`, коммит `Montage (M134): join_heard on (m134: joins off/on …, windows …)` с числами из `joins.txt`, push. Иначе флаг не трогать и написать в отчёт, где правило не выполнилось.

## Шаг 3. Гейт для глаз (только если флаг включён)
Взять источник, где изменилось больше клипов, и отрендерить только эти клипы:
```bash
S="<источник>"; L="<номера через запятую, напр. 2,5,9>"   # из joins.txt: rNN → NN
arl render --manifest "reviews/${S}_m134on.review.json" --reels "$L" --gate m134 --encoder hevc_videotoolbox 2>&1 | tail -6
ls "reels-out/$S/_gate/m134/"r*.mp4
```
Если `--reels` не принимает список — рендерить диапазон, покрывающий их, и так и написать. Лист ревью не нужен.

## Шаг 4. Отчёт
`handoff/m134/REPORT.md`: коммит(ы), строка pytest, `blocks.txt` (сводные строки), `joins.txt` целиком, решение по правилу, пути клипов гейта.
```bash
bash handoff/bin/report.sh m134 blocks.txt joins.txt
```
Владельцу — две строки: включён ли `join_heard` и сколько стыков ушло; «смотреть: reels-out/<источник>/_gate/m134/ — клипы rNN: на месте прежнего стыка между соседними предложениями теперь должна быть сплошная речь».

Статус: IMPLEMENTED, GATE PENDING.
