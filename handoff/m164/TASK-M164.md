# TASK M164 (окно MAIN; выполнить ДО m163): карта речи, этап C — убрать точечную звуковую пробу хвоста

Владелец: «этап C — сделать сейчас». Инвариант 9: время берётся из звука, после M1.8 — только из карты. В рендере осталась старая проба `_tail_find_word_end` (silencedetect вокруг последнего слова). Она работала у клипов без плана, когда карты нет или флаг `speech_map` выключен. С M149 флаг включён и карты есть у всех источников, так что проба, по расчёту, уже не срабатывает.

Патч удаляет пробу. Без карты клип сохраняет конец из разметки, рендер печатает предупреждение «нет карты речи». Тест `tests/test_m164_stage_c.py`, PLAN, REEL_SPEC.

По правилу «структурное изменение сначала доказывает, что старые данные дают тот же результат» — сначала замер, потом правка, потом сравнение рендера до и после.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. Рендер — только на gamebox (`--remote`), Mac свободен; pytest — без рендера на Mac.

## Шаг 1. Замер: кому нужна проба сейчас
```bash
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m164
.venv/bin/python handoff/m164/probe_count.py 2>&1 | tee handoff/m164/count.txt | tail -6
```
Ожидается: `speech_map … True`, строка `=== … с пробой хвоста N`.
- **N = 0** — правка ничего не меняет для нынешних данных, дальше.
- **N > 0** — СТОП, `count.txt` в отчёт: решим, достроить ли карты, прежде чем удалять.

## Шаг 2. Рендер ДО правки (gamebox)
```bash
.venv/bin/python -m autoreels render --manifest reviews/IMG_6848_m157.review.json --reels 1-3 --gate m164a --remote 2>&1 | grep -E "ERROR|клипы здесь|ошибка" | tee handoff/m164/before.txt
```

## Шаг 3. Патч, тесты, коммит
```bash
git apply --check handoff/m164/m164-stage-c.patch && git apply handoff/m164/m164-stage-c.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests PLAN.md docs && git commit -m "Render (M164, M1.8 stage C): the tail is placed by the speech map only — the point silencedetect probe is removed (m164: clips needing it N=0)" && git push && git log --oneline -1
```

## Шаг 4. Рендер ПОСЛЕ правки и сравнение
```bash
.venv/bin/python -m autoreels render --manifest reviews/IMG_6848_m157.review.json --reels 1-3 --gate m164b --remote 2>&1 | grep -E "ERROR|нет карты|клипы здесь|ошибка" | tee handoff/m164/after.txt
for r in r01 r02 r03; do
  a=reels-out/IMG_6848/_gate/m164a; b=reels-out/IMG_6848/_gate/m164b
  echo "$r: render.json $(cmp -s $a/$r.render.json $b/$r.render.json && echo совпал || echo РАЗНЫЙ) | длительность $(ffprobe -v error -show_entries format=duration -of csv=p=0 $a/$r.mp4) → $(ffprobe -v error -show_entries format=duration -of csv=p=0 $b/$r.mp4)"
done | tee handoff/m164/compare.txt
```
Ожидается: `render.json совпал` у всех трёх, длительности равны, строк «нет карты» нет.

## Шаг 5. Отчёт и уборка
Гейты m164a/m164b — только для сравнения, после отчёта в Корзину:
```bash
mkdir -p ~/.Trash/autoreels-m164 && mv reels-out/IMG_6848/_gate/m164a reels-out/IMG_6848/_gate/m164b ~/.Trash/autoreels-m164/
ssh gamebox 'rm -rf /mnt/data/autoreels/reels-out/IMG_6848/_gate/m164a /mnt/data/autoreels/reels-out/IMG_6848/_gate/m164b'
```
`handoff/m164/REPORT.md`: `count.txt`, коммит, pytest, `compare.txt`.
`bash handoff/bin/report.sh m164 count.txt before.txt after.txt compare.txt`
Владельцу — одна строка: «этап C сделан: проба хвоста удалена, клипов, которым она была нужна, — 0, рендер до/после совпал».
