# M136 REPORT

## Статус: IMPLEMENTED, GATE PENDING

### Шаг 1. Патч, тесты, коммит

- `git apply` — чисто, `applied`
- pytest: `2474 passed, 9 deselected, 2 errors` (errors — порядковый конфликт, не патч: оба теста проходят в одиночку; `test_filler_cut.py -k m136` — 1 passed)
- Коммит: `ccdd1c3` — `Plan (M136): a cut that overlaps a kept one is never kept (a filler cut and the long pause next to it reversed Pxl 112938952 r13; m134 --apply failed)`
- Push: `3233acb..ccdd1c3  main -> main`

### Шаг 2. Замер Pxl целиком

- `false rc=0`, `true rc=0`
- `review.json возвращён`
- `git diff --stat config/r0.yaml` — пуст

**joins.txt:**
```
clips off/on 16/16; joins off/on 8/12; errors off/on 0/0
- r01: windows 7 → 7
- r02: windows 4 → 4
- r03: windows 4 → 3  ← изменилось
- r04: windows 3 → 3
- r05: windows 4 → 5  ← изменилось
- r06: windows 2 → 2
- r07: windows 5 → 5
- r08: windows 6 → 6
- r09: windows 7 → 7
- r10: windows 3 → 3
- r11: windows 2 → 2
- r12: windows 6 → 6
- r13: windows 9 → 9
- r14: windows 2 → 2
- r15: windows 6 → 6
- r16: windows 6 → 6
```

Регрессия устранена: 16/16 клипов (в m134 было 3/16 из-за reversed-сегмента r13).
join_heard: стыков 8→12 (+4), окна изменились у r03 (4→3) и r05 (4→5).

### Шаг 3. Гейт

Отрендерены r13 (пауза + «ну», там была регрессия), r03 и r05 (изменились окна).

```
reels-out/Pxl 20260621 112938952/_gate/m136/r03.mp4
reels-out/Pxl 20260621 112938952/_gate/m136/r05.mp4
reels-out/Pxl 20260621 112938952/_gate/m136/r13.mp4
```

Смотреть: r13 — пауза перед «ну» не должна ломать клип (прежде был reversed-сегмент); r03/r05 — изменились окна из-за join_heard.
