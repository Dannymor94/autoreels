# M134 REPORT

## Статус: IMPLEMENTED, GATE PENDING

### Шаг 1. Патч, тесты, коммит

- `git apply` — чисто, `applied`
- pytest: `2477 passed, 9 deselected` (5 новых в `tests/test_montage_heard_join.py`)
- Коммит: `34e1f66` — `Montage (M134): «a piece goes straight on» by the pause heard, not the Whisper gap (montage.join_heard, off); block cutting stays on Whisper by measure (13 of 72 boundaries would move)`
- Push: `a86a1a2..34e1f66  main -> main`

### Шаг 2. Замер

**blocks.txt (сводные строки — minority совпадений → отложить нарезку):**
```
## 2026-08-08 09h 33m 14s: kept boundaries same: 12 of 75
## 2026-08-08 10h 59m 38s: kept boundaries same: 19 of 92
## 2026-08-08 11h 42m 49s: kept boundaries same: 4 of 27
## IMG_6848: kept boundaries same: 13 of 72
## PXL_20260729_085910095_34f06abf: kept boundaries same: 20 of 105
## PXL_20260729_copy: kept boundaries same: 15 of 108
## Pxl 20260621 112938952: kept boundaries same: 9 of 116
## Pxl 20260621 122006193: kept boundaries same: 2 of 23
```
Ни одного `skipped`. Везде меньшинство — «отложить» подтверждено.

4 строки `rc=0` / `rc=1`:
- `IMG_6848 false rc=0`, `IMG_6848 true rc=0`
- `Pxl 20260621 112938952 false rc=1`, `Pxl 20260621 112938952 true rc=1`

Ошибка Pxl в обоих прогонах: `error: reel r13: segment 1 empty/reversed [1690.978, 1688.880]` — предсуществующая, не связана с флагом (rc=1 у обоих).

Оба `review.json возвращён`. `git diff --stat config/r0.yaml` — пусто.

**joins.txt:**
```
## IMG_6848: clips off/on 12/12; joins off/on 3/6; errors off/on 0/0
## Pxl 20260621 112938952: clips off/on 3/3; joins off/on 8/12; errors off/on 0/0
```
Нет строк с изменёнными окнами (число сегментов во всех клипах осталось прежним).

**Решение по правилу:**
- Ошибок с флагом не больше ✅ (0/0 в обоих источниках)
- Клипов столько же ✅ (12/12 и 3/3)
- Окон нигде не стало больше ✅ (нет ни одной строки `-`)

→ Флаг включён: `join_heard: true`

Коммит: `8749be4` — `Montage (M134): join_heard on (m134: joins off/on 3/6 IMG_6848 + 8/12 Pxl, windows unchanged)`

### Шаг 3. Гейт

Источник с большим числом новых джоинов — `Pxl 20260621 112938952` (+4 новых join).
Поскольку `joins.txt` не показал клипов с изменёнными окнами, отрендерены все 3 клипа.

```
reels-out/Pxl 20260621 112938952/_gate/m134/r01.mp4
reels-out/Pxl 20260621 112938952/_gate/m134/r02.mp4
reels-out/Pxl 20260621 112938952/_gate/m134/r03.mp4
```

Смотреть: на местах, где флаг добавил джоин (M3, M5, M13 — новые бесшовные соединения), должна идти сплошная речь без лишнего стыка.
