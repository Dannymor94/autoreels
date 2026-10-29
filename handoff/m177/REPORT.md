# REPORT M177

## Шаг 1. Патч, тесты, коммит

Коммит `fea381f` (запушен):
> Auto (M177): a label clip repeating a kept clip (autocut.combined_overlap_max of its seconds, montage first) or with a short shot leaves the combined draft (m176: 105 clips)

pytest: **2565 passed** (5 новых `test_m177_repeats.py`), 16 skipped, 9 deselected.

Два правила в `arl auto`:
1. Клип разметки, чьи секунды на `combined_overlap_max` (0.3) совпадают с уже принятым клипом (сначала принимаются сборки), убирается из combined draft.
2. Клип разметки с коротким планом убирается так же, как сборка.
Оба правила: 1 = выкл.

---

## Шаг 2. Какие клипы m176 убрать

`exclude.txt`:

| Источник | Убрать | Причина |
|---|---|---|
| disko_beach_p1 | 3 | r02 short shot; r04 repeats r14 (91%); r05 repeats r10 (96%) |
| disko_beach_p2 | 1 | r04 short shot |
| disko_beach_p3 | 9 | r01/r02 repeats; r08/r09/r10/r11 short shots; r13/r18/r20 repeats r15 |
| day_yoga_p1 | 2 | r01 repeats r04 (100%); r02 repeats r05 (62%) |
| day_yoga_p2 | 4 | r04/r05 repeats; r07/r09 short shots |
| prew_isaev_anna | 6 | r05 short shot; r06/r07/r08/r09/r10 repeats |
| prew_isaev_danny | 7 | r01/r03/r05/r06/r08/r09/r10 repeats |
| **ИТОГО** | **32** | |

**Проверка 3 пар повторов** (`pairs.txt`): все три пары рассказывают одно и то же (випассана r04≈r14, обусловленность r05≈r10, уникальность r01≈r23).

---

## Шаг 3. Перенос, выгрузка, сетка

Клипы перенесены в `reels-out/<источник>/_gate/m176/_excluded/` (не удалены).

### Клипов по источникам после

| Источник | До | Убрано | После |
|---|---|---|---|
| disko_beach_p1 | 14 | 3 | 11 |
| disko_beach_p2 | 8 | 1 | 7 |
| disko_beach_p3 | 21 | 9 | 12 |
| day_yoga_p1 | 5 | 2 | 3 |
| day_yoga_p2 | 20 | 4 | 16 |
| prew_isaev_anna | 16 | 6 | 10 |
| prew_isaev_danny | 21 | 7 | 14 |
| **ИТОГО** | **105** | **32** | **73** |

### Сетка

```
grid.csv: 73 строк, 2026-10-28 … 2027-01-08
на месте 73 (номер тот же у 73), выпали 0, новые в конце 0
в третьем лице: 0
с хэштегом в заголовке: 0
```

После переноса образовался 6-пробег disko_beach_p3 (строки 54-59: r23, r04, r05, r16, r21, r07) — убранные клипы anna/r07 были разбивателями. Исправлено: anna/r14 перемещена из строки 68 после p3/r05 (строка 56), связь: «общество прессует уникальность в форму — настоящий свидетель помогает раскрыться, не давить». После правки: все пробеги ≤ 3 дней подряд ✓.

---

## Листы ревью

`reels-out/<источник>/_gate/m176/_review.html` — все 7 источников, клипы `_excluded/` в листе не отображаются.

Убранные клипы: `reels-out/<источник>/_gate/m176/_excluded/`.

Статус: **IMPLEMENTED, GATE PENDING** — гейт закрывает только владелец после просмотра.
