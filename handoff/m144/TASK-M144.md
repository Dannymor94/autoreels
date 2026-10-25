# TASK M144 (окно MAIN, Mac): клип не начинается «склеенным» с речью перед ним

Файлы — ветка `handoff`, папка `handoff/m144/`: `TASK-M144.md`, `m144-glued.patch`, `drafts_glued.py`. Нужны `handoff/m138/owner_drafts.py` и `handoff/m138b/topk.py`. Около 30 минут, без платных моделей.

## Зачем
m143: у 11 из 12 клипов черновика IMG_6848 (m126) перед первым словом нет паузы (медиана 0–0.04 с). Речь до него идёт вплотную к резу, и первая согласная теряется. Владелец: «не слышно первой буквы». У его собственных клипов так 27 из 66, то есть он чаще начинает после паузы. Воздух M142 рез сдвинуть не мог. Просадка громкости loudnorm в начале вторична (−2.4 dB у IMG, у Pxl нет).
Тишину вставлять при рендере не нужно: она не вернёт срезанную согласную. Надо выбирать начало после паузы. Патч:
- `autocut.start_pause_min` (0 = выкл): первый звук клипа (начало и холодный старт) требует столько слышимой тишины перед собой;
- склеенное начало чинится теми же шагами, что начало, непонятное без предыдущего: мысль перед как контекст, более поздняя фраза, другая мысль;
- у сценариста — до двух фраз раньше (если идут подряд), иначе позже, иначе ролик уходит; склеенный крючок не берётся;
- тесты `tests/test_m144_glued.py` (4), запись в REEL_SPEC.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. pytest только в шаге 1, рендера нет до шага 3. Новые файлы в `reviews/` — только `*_auto_m144-*.txt`; `config/r0.yaml` меняется только по правилу шага 3.

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m144
git apply --check handoff/m144/m144-glued.patch && git apply handoff/m144/m144-glued.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests config docs && git commit -m "Autocut (M144): a clip's first sound needs silence heard before it (start_pause_min, off) — m143: 11 of 12 IMG_6848 starts glued, the first consonant lost" && git push && git log --oneline -1
```
Ожидается: `applied`; pytest — все прошли; коммит запушен.

## Шаг 2. Черновики: правило выключено / 0.15 с (как сейчас по умолчанию: добор включён)
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
for mp in manifests/*.json; do
  S=$(basename "$mp" .json)
  case "$S" in *.blocks*|*.discarded*|PXL_20260729_copy) continue;; esac
  [ -f "transcripts/$S.map.json" ] || continue
  arl autocut "$S" --llm none --out "reviews/${S}_auto_m144-off.txt" > "handoff/m144/run-$S-off.txt" 2>&1; echo "$S off rc=$?"
  arl autocut "$S" --llm none --ac start_pause_min=0.15 --out "reviews/${S}_auto_m144-on.txt" > "handoff/m144/run-$S-on.txt" 2>&1; echo "$S on rc=$?"
done
.venv/bin/python handoff/m144/drafts_glued.py m144-off m144-on 2>&1 | tee handoff/m144/glued.txt | tail -4
.venv/bin/python handoff/m138/owner_drafts.py m144-off m144-on 2>&1 | tee handoff/m144/cover.txt | tail -3
.venv/bin/python handoff/m138b/topk.py m144-off m144-on 2>&1 | tee handoff/m144/topk.txt | tail -3
git status --short | grep -v "^??"
```
Ожидается: по две строки `rc=0` на источник; `glued.txt` — «начал N, склеено K; крючков …» для off и on; `cover.txt` и `topk.txt` с `=== ВСЕГО`; `git status` без изменений в отслеживаемых.

## Шаг 3. Решение и гейт (агент применяет сам)
- **Включить** `start_pause_min: 0.15` в `config/r0.yaml`, если у `m144-on` склеенных начал хотя бы вдвое меньше, чем у off, а покрытие (`cover.txt`) упало не больше чем на 3 клипа из 66. Коммит `Autocut (M144): start_pause_min 0.15 on (m144: glued starts off/on …, covered …)`, push.
- Затем гейт для ушей на IMG_6848. Черновик сценариста m126 (платный) не пересоздаётся, берётся автомонтаж `m144-on`:
  ```bash
  R=reviews/IMG_6848.review.json; B=handoff/m144/IMG_6848.review.json.before; rm -f "$B"; [ -f "$R" ] && cp "$R" "$B"
  arl blocks --apply reviews/IMG_6848_auto_m144-on.txt --labeler auto > handoff/m144/apply.txt 2>&1; echo "rc=$?"
  cp "$R" reviews/IMG_6848_m144.review.json
  if [ -f "$B" ]; then cp "$B" "$R" && cmp "$B" "$R" && echo "review.json возвращён"; else rm -f "$R" && echo "review.json не было — убран"; fi
  N=$(.venv/bin/python -c "import json;print(len(json.load(open('reviews/IMG_6848_m144.review.json'))['reels']))"); echo "клипов: $N"
  arl render --manifest reviews/IMG_6848_m144.review.json --reels 1-$N --gate m144 --encoder hevc_videotoolbox 2>&1 | tail -6
  arl review-sheet IMG_6848 --review reviews/IMG_6848_auto_m144-on.txt --manifest-file reviews/IMG_6848_m144.review.json --gate m144 --preview none 2>&1 | tail -2
  ```
- Правило не выполнено — ничего не включать и не рендерить, написать, чего не хватило.

## Шаг 4. Отчёт
`handoff/m144/REPORT.md`: коммиты, pytest, `glued.txt`, итоги `cover.txt` и `topk.txt`, решение, путь листа.
`bash handoff/bin/report.sh m144 glued.txt cover.txt topk.txt`
Владельцу — две строки: «склеенных начал было N, стало M»; «слушать: reels-out/IMG_6848/_gate/m144/_review.html — первая буква слышна? можно отметить кнопками на листе и скачать решения».

Статус: IMPLEMENTED, GATE PENDING.
