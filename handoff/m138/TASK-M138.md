# TASK M138 (окно MAIN, Mac): вкус владельца упорядочивает предложения автомонтажа

Файлы — ветка `handoff`, папка `handoff/m138/`: `TASK-M138.md`, `m138-taste.patch`, `fit_eval.py`, `owner_drafts.py`.
Около 40 минут. Без платных моделей: автомонтаж гоняется с `--llm none` (выбор и проверки — код, без крючков и плашек от модели), поэтому прогоны дешёвые и одинаковые для сравнения.

## Зачем
m137: владелец начинает клип с длинной законченной мысли, берёт сильные мысли из первой половины разговора, где голос громче; «вирусные» признаки сигнала не несут. Патч:
- `cloud/taste.py` — две логистические головы («мысль взята», «клип начат с неё») по признакам мысли карты;
- автомонтаж прибавляет `taste_weight × вкус` к оценке предложения. Меняется только порядок, а он решает, какие из пула (×3) станут черновиками;
- `taste_weight: 0` — выключено, всё как раньше;
- тесты `tests/test_taste.py`, записи в PLAN, R0_SPEC, PROJECT_STRUCTURE.

`fit_eval.py` подбирает модель на всех клипах владельца → `config/taste.json`, плюс 7 моделей «без одного источника». Проверка честная: черновик источника строится моделью, которая этот источник не видела.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. pytest только в шаге 1, рендера нет. `*_answer.txt`, `manifests/` не трогать; новые файлы в `reviews/` — только `*_auto_m138-*.txt`.
3. `config/r0.yaml` меняется только по правилу решения в шаге 3.

## Шаг 1. Патч, тесты, модель, коммит
```bash
cd /Users/danny/Documents/autoreels
git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m138
git apply --check handoff/m138/m138-taste.patch && git apply handoff/m138/m138-taste.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
.venv/bin/python handoff/m138/fit_eval.py 2>&1 | tee handoff/m138/fit.txt
git add src tests config docs PLAN.md R0_SPEC.md PROJECT_STRUCTURE.md
git commit -m "Autocut (M138): the owner's taste (a model of his 66 clips, cloud/taste.py, config/taste.json) may order the proposals — taste_weight, off" && git push && git log --oneline -1
```
Ожидается: `applied`; pytest — все прошли (6 новых в `tests/test_taste.py`); `fit.txt` — 7 источников, две строки `held-out AUC` (ожидаемо около 0.6 и 0.65), `config/taste.json written`; коммит запушен и содержит `config/taste.json`.

## Шаг 2. Черновики: без вкуса и со вкусом (вес 10 и 20), модель — без этого источника
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
for mp in manifests/*.json; do
  S=$(basename "$mp" .json)
  case "$S" in *.blocks*|*.discarded*|PXL_20260729_copy) continue;; esac
  [ -f "data/cache/m138/taste_wo_$S.json" ] || continue
  arl autocut "$S" --llm none --out "reviews/${S}_auto_m138-off.txt" > "handoff/m138/run-$S-off.txt" 2>&1; echo "$S off rc=$?"
  for W in 10 20; do
    arl autocut "$S" --llm none --ac taste_weight=$W --ac "taste_model=data/cache/m138/taste_wo_$S.json" \
      --out "reviews/${S}_auto_m138-w$W.txt" > "handoff/m138/run-$S-w$W.txt" 2>&1; echo "$S w$W rc=$?"
  done
done
.venv/bin/python handoff/m138/owner_drafts.py m138-off m138-w10 m138-w20 2>&1 | tee handoff/m138/cover.txt | tail -12
git status --short | grep -v "^??"
```
Ожидается: по три строки `rc=0` на каждый из 7 источников (если у источника `rc≠0` во всех трёх — назвать причину из `run-*.txt`, это не СТОП); `cover.txt` — по источникам и `=== ВСЕГО`: «клипов владельца покрыто N/66» и «внутри …%» для трёх тегов; `git status` без изменений в отслеживаемых файлах.

## Шаг 3. Решение (агент применяет сам)
Из строк `=== ВСЕГО` в `cover.txt`: взять вес (10 или 20) с наибольшим покрытием.
- Покрытие с ним **больше**, чем у `m138-off`, и «внутри» не ниже, чем у `off`, больше чем на 3 пункта → в `config/r0.yaml` поставить `taste_weight: <вес>`. Затем коммит `Autocut (M138): taste_weight <вес> on (m138 held-out: covered off/w <N>/<M> of 66, inside <a>%/<b>%)` и push.
- Иначе флаг не трогать и написать в отчёт, чего не хватило.

## Шаг 4. Отчёт
`handoff/m138/REPORT.md`: коммиты, pytest, `fit.txt` целиком, `cover.txt` целиком, решение.
```bash
bash handoff/bin/report.sh m138 fit.txt cover.txt
```
Владельцу — одна строка: «вкус включён (вес W): покрыто N→M из 66» или «не включён: …».
Смотреть глазами здесь нечего: меняется только порядок черновиков.
