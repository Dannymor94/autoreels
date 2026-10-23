# TASK M140 (окно MAIN, Mac): добирать пул автомонтажа, когда он меньше черновика

Файлы — ветка `handoff`, папка `handoff/m140/`: `TASK-M140.md`, `m140-fill.patch`. Нужны готовые черновики `reviews/*_auto_m138-off.txt`, `*_auto_m138-w10.txt` и скрипты `handoff/m138/owner_drafts.py`, `handoff/m138b/topk.py` (остались от m138/m138b). Около 30 минут, без платных моделей.

## Зачем
m138/m138b: пул кандидатов меньше потолка черновика (09h33: 13 при потолке 16; Pxl: 22 при 23), поэтому порядок, в том числе по вкусу, ничего не решал. Покрытие клипов владельца — 35/66, первые k (минуты ÷ 3.5) — 27/66. Патч: флаг `autocut.fill_seed_punch` (0 = выкл). Когда пул меньше, чем черновик может взять, он добирается клипами вокруг зёрен силы на одну ниже (3 вместо 4), без общих мыслей с уже взятыми, и всё упорядочивается по оценке (с вкусом, если `taste_weight` > 0). Тест `test_m140_*` в `tests/test_taste.py`, запись в R0_SPEC.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. pytest только в шаге 1, рендера нет. Новые файлы в `reviews/` — только `*_auto_m140-*.txt`. `config/r0.yaml` меняется только по правилу шага 3.

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m140
git apply --check handoff/m140/m140-fill.patch && git apply handoff/m140/m140-fill.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests config R0_SPEC.md && git commit -m "Autocut (M140): a pool smaller than the draft is filled with clips around weaker seeds (fill_seed_punch, off)" && git push && git log --oneline -1
```
Ожидается: `applied`; pytest — все прошли; коммит запушен.

## Шаг 2. Черновики с добором (без вкуса и со вкусом 10, модель — без этого источника)
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
for mp in manifests/*.json; do
  S=$(basename "$mp" .json)
  case "$S" in *.blocks*|*.discarded*|PXL_20260729_copy) continue;; esac
  [ -f "data/cache/m138/taste_wo_$S.json" ] || continue
  arl autocut "$S" --llm none --ac fill_seed_punch=3 --out "reviews/${S}_auto_m140-fill.txt" > "handoff/m140/run-$S-fill.txt" 2>&1; echo "$S fill rc=$?"
  arl autocut "$S" --llm none --ac fill_seed_punch=3 --ac taste_weight=10 --ac "taste_model=data/cache/m138/taste_wo_$S.json" \
    --out "reviews/${S}_auto_m140-fillw10.txt" > "handoff/m140/run-$S-fillw10.txt" 2>&1; echo "$S fillw10 rc=$?"
  grep -h "пул:" "handoff/m140/run-$S-fill.txt" || echo "  $S: пул не добирался"
done
.venv/bin/python handoff/m138/owner_drafts.py m138-off m140-fill m140-fillw10 2>&1 | tee handoff/m140/cover.txt | tail -5
.venv/bin/python handoff/m138b/topk.py m138-off m140-fill m140-fillw10 2>&1 | tee handoff/m140/topk.txt | tail -5
git status --short | grep -v "^??"
```
Ожидается: по две строки `rc=0` на источник и строка «пул: N < M — добавлено K» (или «не добирался»); `cover.txt` и `topk.txt` с итогами `=== ВСЕГО`; `git status` без изменений в отслеживаемых файлах.

## Шаг 3. Решение (агент применяет сам)
- **Добор** включить (`fill_seed_punch: 3` в `config/r0.yaml`), если в `cover.txt` у `m140-fill` покрыто больше, чем у `m138-off`, хотя бы на 3, «внутри» не ниже больше чем на 3 пункта, и в `topk.txt` (столбец `k=мин÷3.5`) покрыто не меньше, чем у off.
- **Вкус** (`taste_weight: 10`) включить дополнительно, только если в `topk.txt` у `m140-fillw10` покрыто больше, чем у `m140-fill`, хотя бы на 2.
- Что включено — один коммит `Autocut (M140): <fill_seed_punch 3 | + taste_weight 10> on (m140: covered off/fill/fillw10 …, top-k …)` с числами, push. Не выполнено — ничего не трогать, написать чего не хватило.

## Шаг 4. Отчёт
`handoff/m140/REPORT.md`: коммиты, pytest, строки «пул:», `cover.txt` и `topk.txt` (итоги и по источникам), решение.
`bash handoff/bin/report.sh m140 cover.txt topk.txt`
Владельцу — одна строка с итогом.
