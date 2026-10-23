# TASK M136 (окно MAIN, Mac): перекрытые вырезы ломали `--apply` черновика Pxl (регрессия M126)

Файлы — ветка `handoff`, папка `handoff/m136/`: `TASK-M136.md`, `m136-overlap.patch`. Около 20 минут.

## Зачем
В m134 `--apply` черновика Pxl упал с `reel r13: segment 1 empty/reversed [1690.978, 1688.880]`, поэтому в замере было 3 клипа вместо 16. Это не «было раньше»: в m125 тот же черновик давал 16 клипов. Причина воспроизведена тестом. Вырез паразита (M126) и длинная пауза перед ним (M79) покрывают одну тишину. Обе ≥ `long_pause_sec`, длинная пауза обходит правила интервала, поэтому оставались обе, и кусок между ними выходил перевёрнутым. Патч: вырез, перекрывающий уже взятый, не берётся. Тест `test_m136_*` в `tests/test_filler_cut.py`, запись в REEL_SPEC.

## Правила
Как в m134: СТОП при несовпадении; `review.json` сохранить и вернуть; `config/r0.yaml` в конце как в коммите; `--install`, `arl auto` не запускать; pytest только в шаге 1.

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
git apply --check handoff/m136/m136-overlap.patch && git apply handoff/m136/m136-overlap.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests docs && git commit -m "Plan (M136): a cut that overlaps a kept one is never kept (a filler cut and the long pause next to it reversed Pxl 112938952 r13; m134 --apply failed)" && git push && git log --oneline -1
```
Ожидается: `applied`; pytest — все прошли; коммит запушен.

## Шаг 2. Pxl целиком: применяется, и замер m134 заново (флаг выключен / включён)
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m136
S="Pxl 20260621 112938952"; D="reviews/${S}_auto_m123-scen.txt"
R="reviews/$S.review.json"; B="handoff/m136/$S.review.json.before"; rm -f "$B"; [ -f "$R" ] && cp "$R" "$B"
for J in false true; do
  sed -i '' "s/^  join_heard: .*/  join_heard: $J/" config/r0.yaml
  arl blocks --apply "$D" --labeler auto > "handoff/m136/apply.$J.txt" 2>&1; echo "$J rc=$?"
  cp "$R" "reviews/${S}_m136$([ $J = true ] && echo on || echo off).review.json"
done
if [ -f "$B" ]; then cp "$B" "$R" && cmp "$B" "$R" && echo "review.json возвращён"; else rm -f "$R" && echo "review.json не было — убран"; fi
git checkout config/r0.yaml; git diff --stat config/r0.yaml
.venv/bin/python - <<'PY' | tee handoff/m136/joins.txt
import json
S = "Pxl 20260621 112938952"
off = {r["id"]: r for r in json.load(open(f"reviews/{S}_m136off.review.json"))["reels"]}
on = {r["id"]: r for r in json.load(open(f"reviews/{S}_m136on.review.json"))["reels"]}
jo = {f: sum(1 for l in open(f"handoff/m136/apply.{f}.txt") if "go straight on" in l) for f in ("false", "true")}
er = {f: sum(1 for l in open(f"handoff/m136/apply.{f}.txt") if "[ERROR]" in l or "error:" in l) for f in ("false", "true")}
print(f"clips off/on {len(off)}/{len(on)}; joins off/on {jo['false']}/{jo['true']}; errors off/on {er['false']}/{er['true']}")
for rid in sorted(set(off) | set(on)):
    a, b = off.get(rid), on.get(rid)
    na = len(a.get("segments") or []) if a else None
    nb = len(b.get("segments") or []) if b else None
    print(f"- {rid}: windows {na} → {nb}" + ("" if na == nb else "  ← изменилось"))
PY
```
Ожидается: оба `rc=0`; клипов 16 и 16 (если меньше — `apply.*.txt` назовёт причину, это СТОП); `review.json возвращён`; `git diff --stat config/r0.yaml` пуст; в `joins.txt` по строке на клип.

## Шаг 3. Гейт для глаз
Отрендерить r13 и клипы со «← изменилось» из `reviews/${S}_m136on.review.json`:
```bash
L="<13 и номера изменившихся через запятую>"
arl render --manifest "reviews/${S}_m136on.review.json" --reels "$L" --gate m136 --encoder hevc_videotoolbox 2>&1 | tail -6
ls "reels-out/$S/_gate/m136/"r*.mp4
```

## Шаг 4. Отчёт
`handoff/m136/REPORT.md`: коммит, pytest, `joins.txt` целиком, пути клипов.
```bash
bash handoff/bin/report.sh m136 joins.txt
```
Владельцу — две строки: «Pxl снова применяется целиком (16 клипов); join_heard: стыков ушло N»; «смотреть: reels-out/Pxl 20260621 112938952/_gate/m136/ — r13 (там была пауза + «ну»), и rNN, где ушёл стык».

Статус: IMPLEMENTED, GATE PENDING.
