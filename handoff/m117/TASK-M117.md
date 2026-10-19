# TASK M117 (окно MAIN, Mac + gamebox, без патча): модель gamebox — без размышления и с размышлением — на тех же сборках и суждениях

Файлы — в ветке `handoff`, папка `handoff/m117/` (только эта задача). Скрипты замера — из `handoff/m116/`.

**Ставится поверх M116**: нужны его коммиты и журнал `handoff/m116/judge_cloud.jsonl`. Если их нет — **СТОП**: сначала «Выполни m116». Одна сессия, без фоновых задач. Долго: 1,5–3 часа (модель gamebox медленная, с размышлением — ещё медленнее). Озвучку книги не трогать: если gamebox занят, `arl` ждёт сам.

## Зачем
Владелец: «выяснить разницу между Haiku, Sonnet, Qwen на Groq и Qwen с размышлениями и без». Groq, Haiku и Sonnet померены в m116. Здесь — та же Qwen на gamebox:
1. **Без размышления** (`--llm local`, как работала раньше). Полные сборки трёх источников и те же суждения, что задавались Groq.
2. **С размышлением** (`--llm local-think`). На gamebox нет лимита Groq на длину ответа, размышление стоит только времени. Только суждения: первые 40 запросов из журнала Groq. Полная сборка с размышлением заняла бы несколько часов на источник.

## Правила
1. Любой шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить. Расхождение чисел между моделями — не СТОП, это замер.
2. Перед стартом не должно идти других `arl` и рендера. pytest не запускать.
3. gamebox: озвучку не трогать. Из sudo — только то, что делает сам `arl` (`systemctl start|stop llama-server`). Если цикл ожидания замка висит дольше 90 минут — **СТОП**.
4. Не трогать то же, что в m116 (`reviews/*_answer.txt`, `*_auto_m56.txt`, `*_auto_all.txt`, `*_auto_m112.txt`, `*_auto_m115.txt`, `*.review.json`, `verdicts.jsonl`, манифест `PXL_20260729_085910095_34f06abf.json`). Черновики — новые файлы `reviews/<источник>_auto_m116-local.txt`.
5. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.
6. Итог — «MEASURED».

## Шаг 1. Сборки трёх источников моделью gamebox без размышления
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m117
git log --oneline -3; pgrep -fl "arl " || echo "arl не запущен"; ls -l handoff/m116/judge_cloud.jsonl
rm -f handoff/m116/run_local.txt handoff/m116/judge_local.jsonl
for S in "IMG_6848" "2026-08-08 11h 42m 49s" "Pxl 20260621 112938952"; do
  { echo "=== $S"; /usr/bin/time -p .venv/bin/python -m autoreels autocut "$S" --llm local --out "reviews/${S}_auto_m116-local.txt" --judge-log handoff/m116/judge_local.jsonl; } 2>&1 | tee -a handoff/m116/run_local.txt | grep -E "^autocut|gamebox|^real|ошибка"
done
```
Ожидается:
- в `git log` есть коммиты M116; `arl не запущен`; журнал `judge_cloud.jsonl` есть;
- строки замка gamebox (`замок взят` / `отпущен`);
- по каждому источнику — `autocut …: предложено сборок N …` и `real …`.

## Шаг 2. Те же суждения — gamebox без размышления и с размышлением
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
{
arl judge-bench handoff/m116/judge_cloud.jsonl --llm local --out handoff/m116/bench_local.jsonl
arl judge-bench handoff/m116/judge_cloud.jsonl --llm local-think --limit 40 --out handoff/m116/bench_local-think.jsonl
} 2>&1 | tee handoff/m117/run_bench_local.txt | grep -vE "^  …"
```
Ожидается: два блока `judge-bench … → local:…: запросов N` (у `local-think` — 40 и модель `local:local+think`), строки по видам суждений с секундами на запрос.

## Шаг 3. Сводки по всем пяти
```bash
cd /Users/danny/Documents/autoreels
.venv/bin/python handoff/m116/compare_models.py cloud haiku sonnet local 2>&1 | tee handoff/m117/models.txt
.venv/bin/python handoff/m116/bench_summary.py handoff/m116/judge_cloud.jsonl handoff/m116/bench_haiku.jsonl handoff/m116/bench_sonnet.jsonl handoff/m116/bench_local.jsonl handoff/m116/bench_local-think.jsonl 2>&1 | tee handoff/m117/bench.txt
cp handoff/m116/run_local.txt handoff/m116/bench_local.jsonl handoff/m116/bench_local-think.jsonl handoff/m117/
git status --short
```
Ожидается: таблицы с пятью моделями (у `local-think` — только на 40 запросах, совпадение считается на общих). В `git status` новых строк нет.

## Шаг 4. Отчёт в ветку
Записать `handoff/m117/REPORT.md`:
1. `models.txt` и `bench.txt` целиком.
2. Время: `real` по источникам из `run_local.txt`, секунды на запрос у `local` и `local-think` из `run_bench_local.txt`.

```bash
cd /Users/danny/Documents/autoreels
bash handoff/bin/report.sh m117 models.txt bench.txt run_bench_local.txt run_local.txt bench_local.jsonl bench_local-think.jsonl
```
Ожидается `отчёт m117 отправлен в ветку handoff`. Владельцу в чат — одна строка: сборок у gamebox против остальных, время одного суждения без размышления и с ним, «отчёт в ветке».

Статус: MEASURED.
