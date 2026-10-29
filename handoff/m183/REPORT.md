# REPORT M183

## 1. Коммит и тесты

- Коммит: `74a6e59` «Autocut (M183): label clips of arl auto get a cold open from their own second half (autocut.label_hooks); a sentence that points back still gives its later clauses as hooks»
- pytest: 2582 passed, 16 skipped, 9 deselected
- test_m182_hooks_starts.py: **12 passed** (было 10 в m182)

## 2. Проба шага 2 (prew_isaev_anna, --no-render)

- Сборок: 8, с крючком: **7** (в m182 — 1)
- Крючков из части фразы (`@i-j`): 2 (в m182 — 0)
- Крючки у клипов разметки: 3 (строки «крючок N+M:»)
- pre_hooks.txt: 3 крючка отброшены моделью («что» / «и так далее» / «только потом»)

## 3. Перепрогон (itog.txt)

Все 7 источников — ✓. Сценарист — из кэша.

## 4. Крючки (hooks.txt)

| Источник | m176 клипов/крючков | m182 клипов/крючков | m183 клипов/крючков |
|---|---|---|---|
| prew_isaev_anna | 12 / 1 | 9 / 1 | 9 / **2** |
| prew_isaev_danny | 14 / 1 | 12 / 1 | 12 / **2** |
| disko_beach_p1 | 11 / 3 | 11 / 5 | 11 / **6** |
| disko_beach_p2 | 7 / 1 | 7 / 3 | 7 / **5** |
| disko_beach_p3 | 16 / 5 | 15 / 6 | 15 / **10** |
| day_yoga_p1 | 4 / 1 | 3 / 1 | 3 / 1 |
| day_yoga_p2 | 16 / 2 | 12 / 2 | 12 / **6** |
| **ИТОГО** | **80 / 14 (18%)** | **69 / 19 (28%)** | **69 / 32 (46%)** |

## 5. Крючки у клипов разметки

98 строк «крючок N+M:» в auto.txt — label_hooks сработал на всех источниках.

## 6. Вспышки

SLIVER 0, short 0.

## 7. Клипов по источникам

| Источник | m182 | m183 |
|---|---|---|
| disko_beach_p1 | 11 | 11 |
| disko_beach_p2 | 7 | 7 |
| disko_beach_p3 | 15 | 15 |
| day_yoga_p1 | 3 | 3 |
| day_yoga_p2 | 12 | 12 |
| prew_isaev_anna | 9 | 9 |
| prew_isaev_danny | 12 | 12 |
| **ИТОГО** | **69** | **69** |

## 8. Сетка (grid2.py)

```
grid.csv: 69 строк, 2026-10-28 … 2027-01-04; на месте 69 (номер тот же у 64), выпали 0, новые в конце 0
в третьем лице: 0
с хэштегом в заголовке: 0
```

## 9. Старые гейты (gates_after.txt)

У всех 7 источников в `_gate/` осталась только `m183`. Остальные гейты перемещены в `~/.Trash/autoreels-m183/`.

---

**Статус: IMPLEMENTED, GATE PENDING**
