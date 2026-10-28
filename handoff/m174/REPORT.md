# REPORT M174

## Шаг 1: патч, тесты, коммит

Коммит `b894da4`: `Plan (M174): a short piece inside a sentence takes silence from the neighbouring cut, else the cut is dropped (m173: 53 short shots inside a sentence)`

Изменено: `src/autoreels/cloud/reel_plan.py` (удлинение короткого куска тишиной из соседней вырезки), `tests/test_m174_lengthen_short.py` (4 теста).

pytest: **2556 passed, 16 skipped, 9 deselected** — все прошли (+4 теста vs m173).

## Шаг 2: замер до рендера (`pre.txt`)

```
ВСЕГО: SLIVER 0, short 10
```

«inside a sentence»: **0** (было 53 в m173). Все 10 остатков — «whole sentences»: уберёт перепрогон.

| источник | short pre |
|---|---|
| day_yoga_p2 | 3 (r01, r03, r12) |
| disko_beach_p1 | 2 (r04, r06) |
| disko_beach_p2 | 2 (r04) |
| prew_isaev_anna | 2 (r05, r18) |
| prew_isaev_danny | 1 (r19) |

## Шаг 3: перепрогон всех 7 источников в гейт m174

```
=== auto: итог ===
  ✓ disko_beach_p1: готово — общий черновик не прошёл (rc=1) — взят только черновик сборок
  ✓ disko_beach_p2: готово
  ✓ disko_beach_p3: готово — общий черновик не прошёл (rc=1)
  ✓ day_yoga_p1: готово
  ✓ day_yoga_p2: готово — общий черновик не прошёл (rc=1)
  ✓ prew_isaev_anna: готово — общий черновик не прошёл (rc=1)
  ✓ prew_isaev_danny: готово — общий черновик не прошёл (rc=1)
```

Клипов m174 против m163/m157:

| источник | старый гейт | было | стало |
|---|---|---|---|
| disko_beach_p1 | m163 | 10 | 10 |
| disko_beach_p2 | m163 | 8 | 8 |
| disko_beach_p3 | m163 | 6 | 9 |
| day_yoga_p1 | m163 | 5 | 5 |
| day_yoga_p2 | m163 | 13 | 9 |
| prew_isaev_anna | m157 | 20 | 9 |
| prew_isaev_danny | m157 | 26 | 10 |
| **ИТОГО** | | **88** | **60** |

Примечание: prew_isaev_danny r11 — `[ERROR] whoosh pass failed` (ffmpeg ошибка на постобработке). 10 клипов без ERROR.

## Шаг 4: замер после (`after.txt`)

```
ВСЕГО: SLIVER 0, short 2
```

Оба оставшихся коротких плана — disko_beach_p2 r04 (0.00s и 33.08s, «whole sentences»): тишины после вырезки не хватило для удлинения, вырезка снята, пауза играет. Ожидаемое поведение по патчу.

## Посты (`posts.txt`)

```
disko_beach_p1: клипов 10, без поста: (нет)
disko_beach_p2: клипов 8, без поста: (нет)
disko_beach_p3: клипов 9, без поста: (нет)
day_yoga_p1: клипов 5, без поста: (нет)
day_yoga_p2: клипов 9, без поста: (нет)
prew_isaev_anna: клипов 9, без поста: (нет)
prew_isaev_danny: клипов 10, без поста: (нет)
ИТОГО: 60 клипов
```

disko_beach_p3 r01: при `arl describe --force` первый вызов вернул «not JSON» (rate-limit?); второй вызов принял пост.

## Выгрузка и сетка (`export.txt`, `grid.txt`)

```
crosspost: 10+8+9+5+9+9+10 = 60 клипов
grid.csv: 60 строк, 2026-10-28 … 2026-12-26
выпали 0, новые в конце 0 (после расстановки по смыслу)
в третьем лице: 0
с хэштегом в заголовке: 0
check_grid: OK: 60 роликов, 2026-10-28 … 2026-12-26
```

12 новых клипов (которых не было в m173) расставлены по смыслу в `schedule.csv`:
- `day_yoga_p1/r05` — после `day_yoga_p1/r02` (внутренний ребёнок, поддержка)
- `disko_beach_p1/r02` — после `disko_beach_p1/r01` (поза и закрытые глаза перед дыханием)
- `disko_beach_p1/r06` — после `disko_beach_p1/r05` (Будда нашёл выход, технология)
- `day_yoga_p2/r08` — после `disko_beach_p1/r09` (мудрец-наблюдатель, випассана)
- `prew_isaev_danny/r04` — после `prew_isaev_danny/r01` (три уровня тело-эмоции-ум)
- `disko_beach_p2/r05` — после `disko_beach_p2/r03` (стресс отключает неокортекс)
- `day_yoga_p2/r07` — после `disko_beach_p2/r04` (взрослый выбирает, иногда уйти с работы)
- `disko_beach_p2/r07` — после `disko_beach_p2/r08` (за маской — предназначение)
- `disko_beach_p3/r04` — после `disko_beach_p3/r01` (сама давлю — хроническое напряжение)
- `disko_beach_p3/r03` — после `disko_beach_p3/r02` (дыхание и бессознательное)
- `disko_beach_p3/r05` — после `disko_beach_p3/r03` (дыхание разряжает зажимы)
- `disko_beach_p3/r07` — после `disko_beach_p3/r06` (папы нет, давление осталось)

Листы ревью: `reels-out/<источник>/_gate/m174/_review.html`.

## Статус: IMPLEMENTED, GATE PENDING
