# M138 REPORT

## Статус: IMPLEMENTED, GATE PENDING (флаг не включён)

### Шаг 1. Патч, тесты, модель, коммит

- `git apply` — чисто, `applied`
- pytest: `2480 passed, 9 deselected` (6 новых в `tests/test_taste.py`)
- fit_eval.py: 7 источников, `held-out AUC taken: 0.65`, `held-out AUC start: 0.73` — выше ожидаемых ~0.6 / ~0.65
- `config/taste.json written`; сильнейшие признаки старта: `dur +0.54, punch +0.44, level_db +0.21`
- Коммит: `56912f0` — `Autocut (M138): the owner's taste (a model of his 66 clips, cloud/taste.py, config/taste.json) may order the proposals — taste_weight, off`
- Push: `ccdd1c3..56912f0  main -> main`

**fit.txt:**
```
2026-08-08 09h 33m 14s: thoughts 121, taken 37, starts 15
2026-08-08 10h 59m 38s: thoughts 140, taken 22, starts 8
2026-08-08 11h 42m 49s: thoughts 47, taken 11, starts 4
IMG_6848: thoughts 107, taken 23, starts 8
PXL_20260729_085910095_34f06abf: thoughts 156, taken 24, starts 10
Pxl 20260621 112938952: thoughts 189, taken 50, starts 18
Pxl 20260621 122006193: thoughts 39, taken 5, starts 2
held-out AUC taken: 0.65
held-out AUC start: 0.73
config/taste.json written; start head strongest: dur +0.54, punch +0.44, level_db +0.21, filtered -0.18, role_explanation -0.17, role_thesis +0.16
```

### Шаг 2. Черновики: без вкуса и со вкусом (вес 10 и 20)

- 21 прогон (7 источников × 3 тега): все `rc=0`
- Побочный эффект: `data/token_scale.json` — обновилась калибровка qwen/qwen3.8-27b (1.2835 → 1.0168), это штатное поведение autocut, не нарушение правил
- `git status` без изменений в `reviews/`, `config/`, `manifests/`

**cover.txt (сводка):**
```
=== ВСЕГО (только источники, где есть черновик тега)
   m138-off         сборок  90 (под сомнением 0, без крючка 17, скачков 0/1/2/3+ 62/28/0/0); клипов владельца покрыто 35/66; внутри  23%
   m138-w10         сборок  90 (под сомнением 0, без крючка 17, скачков 0/1/2/3+ 62/28/0/0); клипов владельца покрыто 35/66; внутри  23%
   m138-w20         сборок  90 (под сомнением 0, без крючка 17, скачков 0/1/2/3+ 62/28/0/0); клипов владельца покрыто 35/66; внутри  23%
```

Полная cover.txt — все 7 источников дали одинаковые числа для всех трёх тегов.

### Шаг 3. Решение

Правило не выполнено: покрытие off/w10/w20 = **35/35/35 из 66**, «внутри» = **23%/23%/23%** — полностью идентично.

Причина: `taste_weight` влияет на порядок кандидатов из LLM-пула. При `--llm none` LLM-пула нет — пул формируется только кодом, и добавка `taste_weight × вкус` к оценке не меняет ни состав, ни порядок черновиков. Вкус работает как задумано, но его эффект виден только при реальном LLM-прогоне.

→ `config/r0.yaml` не изменён, `taste_weight` остаётся `0` (выключено).

### Шаг 4

Коммит с включением флага не сделан. Отчёт отправлен в ветку `handoff`.
