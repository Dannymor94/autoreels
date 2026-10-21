# TASK M123b (окно MAIN, Mac): продолжение M123 после СТОП на шаге 3 — разбор строк сценариста, длиннее ответ

**Причина СТОП:** Sonnet написал строки `1 | 30.4-30.7 | …` вместо `M | 30.4-7 | …`, а парсер ждал только «M» — ни одна строка не прошла. Ответ к тому же обрезан на `max_tokens` (6000): вышло 11–18 роликов.

Патч `m123b-parser.patch`:
- строкой ролика считается строка, где первое поле — «M», «M3», «3», «3.» или «3)», в том числе в звёздочках или кавычках;
- диапазон `30.4-30.7` понимается как `30.4-7`;
- в промпте явно: каждая строка начинается с «M |», пояснение «why» — до 15 слов;
- `scenario_max_tokens` 6000 → 16000;
- тест записанного ответа допускает обрезанную последнюю строку.

Промпт изменился, поэтому новый запуск — новый запрос к модели (старый ответ в кэше не подойдёт). Это нужно: старый был обрезан.

Правила — как в `TASK-M123.md`.

## Шаг 1. Свежие файлы задачи, убрать копии шага 3, патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git fetch -q origin +refs/heads/handoff:refs/remotes/origin/handoff && git restore --source=origin/handoff --worktree -- handoff/m123
rm -f tests/fixtures/scenario_raw_IMG_6848.txt tests/test_scenario_recorded.py
git status --short; git log --oneline -1
git apply --check handoff/m123/m123b-parser.patch && git apply handoff/m123/m123b-parser.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add config/r0.yaml src/autoreels/cloud/scenario.py tests/test_scenario.py
git commit -m "Autocut (M123b): scenarist lines the way the model writes them («1 | 30.4-30.7»), a longer answer (16000 tokens), «M |» asked explicitly"
git push; git log --oneline -1
```
Ожидается:
- `git status` до патча пуст; последний коммит — M123 (6fa1e98); `applied`;
- pytest — все прошли, в `tests/test_scenario.py` теперь 5 тестов; коммит запушен.

## Шаг 2. Сценарист заново — три источника
Автосборку m123 не повторять, её черновики уже есть.
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; rm -f handoff/m123/run-b.txt
for S in "IMG_6848" "2026-08-08 11h 42m 49s" "Pxl 20260621 112938952"; do
  { echo "=== $S scenarist"; arl autocut "$S" --scenario --llm sonnet --out "reviews/${S}_auto_m123-scen.txt"; } 2>&1 | tee -a handoff/m123/run-b.txt | grep -E "^autocut|сценарист|Claude |ошибка"
done
.venv/bin/python handoff/m120/owner_drafts.py m122 m123 m123-scen 2>&1 | tee handoff/m123/drafts.txt
grep -h "^#   сценарий:" "reviews/IMG_6848_auto_m123-scen.txt" | head -20 | tee handoff/m123/why.txt
```
Ожидается:
- по источнику — `сценарист: строк X, принято кодом Y …` с Y > 0 хотя бы у IMG_6848;
- `предложено сборок M`, строка цены.

Если у всех трёх Y = 0 — СТОП, приложить раздел `# --- сценарист:` черновика IMG_6848.

## Шаг 3 и дальше
Выполнить шаги 3, 4, 5 из `TASK-M123.md` как написано. В шаге 3 берётся самый свежий ответ из `data/cache/scenario/IMG_6848.*.txt` — это ответ нового запроса.

В отчёт добавить строки сценариста из `run-b.txt`. В `report.sh` добавить `run-b.txt`:
```bash
bash handoff/bin/report.sh m123 run.txt run-b.txt drafts.txt why.txt render.txt
```
