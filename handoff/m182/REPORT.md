# REPORT M182

## 1. Коммит и тесты

- Коммит: `54a7c94` «Autocut (M182): a cold open may be a clause of a long sentence (h:B.N@i-j, autocut.hook_clauses); a reel never opens on a line pointing back or at the interviewer — earlier start or none (autocut.start_strict)»
- pytest: 2580 passed, 16 skipped, 9 deselected (полный прогон без test_menu_bash)
- test_m182_hooks_starts.py: 10/10 passed

## 2. Перепрогон (itog.txt)

```
=== auto: итог ===
  ✓ disko_beach_p1: готово
  ✓ disko_beach_p2: готово
  ✓ disko_beach_p3: готово
  ✓ day_yoga_p1: готово
  ✓ day_yoga_p2: готово
  ✓ prew_isaev_anna: готово
  ✓ prew_isaev_danny: готово
```

Все 7 источников — ✓. Сценарист — из кэша.

## 3. Крючки (hooks.txt)

| Источник | m176 клипов/с крючком | m182 клипов/с крючком |
|---|---|---|
| prew_isaev_anna | 12 / 1 | 9 / 1 |
| prew_isaev_danny | 14 / 1 | 12 / 1 |
| disko_beach_p1 | 11 / 3 | 11 / **5** |
| disko_beach_p2 | 7 / 1 | 7 / **3** |
| disko_beach_p3 | 16 / 5 | 15 / **6** |
| day_yoga_p1 | 4 / 1 | 3 / 1 |
| day_yoga_p2 | 16 / 2 | 12 / 2 |
| **ИТОГО** | **80 / 14 (18%)** | **69 / 19 (28%)** |

У disko_beach (лекции с длинными фразами) крючков заметно больше. У prew_isaev и day_yoga прирост незначительный — у интервью и коротких фраз мало кандидатов для clause-крючка.

## 4. Крючки из части фразы (clause_hooks.txt)

```
day_yoga_p1:        1
day_yoga_p2:        4
disko_beach_p1:     6
disko_beach_p2:     6
prew_isaev_anna:    0
disko_beach_p3:     4
prew_isaev_danny:   1
```

Итого 22 крючка из части фразы (`h:B.N@i-j`).

## 5. Строгое начало (starts.txt)

20 случаев срабатывания `start_strict` (weak start / «и…» / обращение к собеседнику). Примеры убранных:
- `weak start «И без концепции просто смотреть.» — «и…»`
- `weak start «И раз вы здесь, раз вы здесь родились в таком теле» — «и…»`
- `weak start «И эта среда не может не изменять эту уникальную не» — «и…»`

## 6. Вспышки

SLIVER 0, short 0.

## 7. Клипов по источникам

| Источник | m176 | m182 |
|---|---|---|
| disko_beach_p1 | 11 | 11 |
| disko_beach_p2 | 7 | 7 |
| disko_beach_p3 | 16 | 15 |
| day_yoga_p1 | 4 | 3 |
| day_yoga_p2 | 16 | 12 |
| prew_isaev_anna | 12 | 9 |
| prew_isaev_danny | 14 | 12 |
| **ИТОГО** | **80** | **69** |

Уменьшение — start_strict убрал 11 клипов со слабым началом (они же в «выпали»).

## 8. Сетка (grid2.py)

```
grid.csv: 69 строк, 2026-10-28 … 2027-01-04; на месте 69 (номер тот же у 36), выпали 11, новые в конце 0
выпали: day_yoga_p1/r02, day_yoga_p2/r11, day_yoga_p2/r28, prew_isaev_anna/r08,
        day_yoga_p2/r16, prew_isaev_anna/r10, prew_isaev_anna/r14, day_yoga_p2/r17,
        disko_beach_p3/r02, prew_isaev_danny/r16, prew_isaev_danny/r11
в третьем лице: 0
с хэштегом в заголовке: 0
```

---

**Статус: IMPLEMENTED, GATE PENDING**
