# M140 REPORT

## Статус: IMPLEMENTED, GATE PENDING (fill_seed_punch: 3 включён; taste_weight остаётся 0)

### Шаг 1. Патч, тесты, коммит

- `git apply` — чисто, `applied`
- Изменено 7 файлов: `src/autoreels/cloud/autocut.py`, `src/autoreels/__main__.py`, `src/autoreels/core/config.py`, `tests/test_taste.py` (+1 тест), `config/r0.yaml`, `R0_SPEC.md`, `data/token_scale.json`
- pytest: `2481 passed, 9 deselected` (был 2480 — 1 новый тест m140)
- Коммит 1: `a93dd7d` — `Autocut (M140): a pool smaller than the draft is filled with clips around weaker seeds (fill_seed_punch, off)`
- Push: `56912f0..a93dd7d main -> main`

**Регрессия обнаружена и исправлена:** второй вызов `propose` в новом коде не передавал `rhythm_out`, из-за чего `test_m120_cmd_autocut_lists_clips_that_could_not_keep_the_rhythm` падал (`AttributeError: 'NoneType' object has no attribute 'append'`). Исправлено: добавлен `rhythm_out=[]`. Все 73 теста в `test_taste.py + test_autocut.py` прошли.

### Шаг 2. Черновики с добором

14 прогонов (7 источников × fill + fillw10): все `rc=0`.

**Строки «пул:»:**
```
2026-08-08 09h 33m 14s: пул: 15 сборок < 48 — добавлено 4 вокруг мыслей силы 3
2026-08-08 10h 59m 38s: пул: 17 сборок < 66 — добавлено 4 вокруг мыслей силы 3
2026-08-08 11h 42m 49s: пул: 3 сборок < 21 — добавлено 0 вокруг мыслей силы 3
IMG_6848:               пул: 15 сборок < 54 — добавлено 1 вокруг мыслей силы 3
Pxl 20260621 112938952: пул: 23 сборок < 69 — добавлено 8 вокруг мыслей силы 3
Pxl 20260621 122006193: пул: 3 сборок < 18 — добавлено 1 вокруг мыслей силы 3
PXL_20260729_085910095_34f06abf: пул: 22 сборок < 72 — добавлено 8 вокруг мыслей силы 3
```

**cover.txt (=== ВСЕГО):**
```
m138-off     сборок  90; клипов владельца покрыто 35/66; внутри  23%
m140-fill    сборок 104; клипов владельца покрыто 40/66; внутри  25%
m140-fillw10 сборок 104; клипов владельца покрыто 39/66; внутри  24%
```

**topk.txt (=== ВСЕГО):**
```
m138-off     k=его число: покрыто 29/66, сборок в его клипах 13/63; k=мин÷3.5: покрыто 27/66, в его клипах 11/64
m140-fill    k=его число: покрыто 30/66, сборок в его клипах 15/65; k=мин÷3.5: покрыто 27/66, в его клипах 13/64
m140-fillw10 k=его число: покрыто 28/66, сборок в его клипах 14/65; k=мин÷3.5: покрыто 25/66, в его клипах 12/64
```

`git status` без изменений в отслеживаемых файлах (кроме штатного `data/token_scale.json`).

### Шаг 3. Решение

**Добор (`fill_seed_punch: 3`):**
- cover.txt: fill покрыто 40/66 vs off 35/66 → +5 ≥ 3 ✓
- cover.txt: «внутри» 25% vs 23% → не упало ✓
- topk.txt k=мин÷3.5: fill 27/66 = off 27/66 → не ниже ✓

→ `fill_seed_punch: 3` включён в `config/r0.yaml`.

**Вкус (`taste_weight: 10`):**
- topk.txt k=мин÷3.5: fillw10 25/66 < fill 27/66 → не +2 ❌

→ `taste_weight` остаётся `0`.

**Коммит 2:** `e961a32` — `Autocut (M140): fill_seed_punch 3 on (m140: covered off/fill/fillw10 35/40/39 of 66, top-k 27/27/25; fix rhythm_out regression)`
Push: `a93dd7d..e961a32 main -> main`
