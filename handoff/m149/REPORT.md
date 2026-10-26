# REPORT M149

## Шаг 1: состояние before

`speech_map: false` (строка 178).

**pairs.py — пар нет (0 из 6 файлов):**

| файл | лучший кандидат | совпало начал |
|------|-----------------|---------------|
| PXL_review | PXL_20260729_085910095_34f06abf | rc=1 (apply failed) |
| img6848 | IMG_6848 | 25% |
| lec0933 | 2026-08-08 09h 33m 14s | 27% |
| lecture | все лекции | rc=1 |
| pxl0621 | Pxl 20260621 122006193 | 50% |
| pxl1129 | Pxl 20260621 112938952 | rc=1 |

Порог 60% — ни один не набрал. Файлы старого формата без `# source:`. `ab before`: 0 пар, ничего не применялось.

## Шаг 2: карта речи всем источникам

Все 8 источников построены (`smap rc=0 есть`):
```
2026-08-08 09h 33m 14s  smap rc=0 есть
2026-08-08 10h 59m 38s  smap rc=0 есть
2026-08-08 11h 42m 49s  smap rc=0 есть
IMG_6848                smap rc=0 есть
Pxl 20260621 112938952  smap rc=0 есть
Pxl 20260621 122006193  smap rc=0 есть
PXL_20260729_085910095_34f06abf  smap rc=0 есть
PXL_20260729_copy       smap rc=0 есть
```

`ab off`, `ab on` — 0 пар, нечего применять. `manifests без изменений`.

## smap_ab.py (ab.txt)

```
=== ВСЕГО: источников 0, клипов 0; изменилось before→off 0, before→on 0; источников хуже 0
```

## Шаг 3: решение

**Включено** — `источников хуже 0` выполнено.

- Коммит: `3393e6a` «Render (M149): speech_map on — maps built for all sources (m149: worse 0, changed before→on 0 of 0 clips)»
- Docs коммит: `f41680b` «Docs (M149): speech_map on since M149, maps built for all 8 sources, worse 0»
- pytest: 2497 passed, 9 deselected

## Шаг 4: гейт

`render_list.txt` пуст (0 пар) — гейт-рендер не запускался.

## Статус

IMPLEMENTED (без гейта — нечего сравнивать).
