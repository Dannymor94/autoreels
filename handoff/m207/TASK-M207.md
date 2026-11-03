# TASK M207 (окно MAIN, Mac): сценарист через чат — задание файлом, ответ файлом, те же проверки; доказательство без рендера

Файлы — ветка `handoff`, папка `handoff/m207/`: `TASK-M207.md`, `m207-chat-scenarist.patch` (написан и прогнан ассистентом, ложится на `main` после M206b, `13af9bd`).
Около 20 минут, без рендера и без API. Отчёт — только на русском.

## Зачем
Владелец, 2026-11-02: «экспорт с заготовленным промтом и инструкцией: я беру текстовый файл, закидываю в чат, чат работает сценаристом, я скидываю ответ обратно — и по нему идёт сборка». Платного API нет.

## Что вносит патч
- `cloud/chatscenario.py`:
  - пути `exchange/<ист>.scenario.md | .answer.txt | .fix.md`;
  - задание: шаги владельцу, затем для чата — те же правила, пронумерованный текст и примеры владельца, что у API-сценариста;
  - отпечаток пронумерованного текста; сообщение для чата об отклонённых строках.
- `__main__.py`:
  - `--scenario-llm chat`: без ответа — задание пишется, источник «ждёт ответа чата» (код 3), автомонтаж вместо него **не** идёт. С ответом — те же `parse_scenarios` и проверки, дальше обычный путь; плашки, `k:` и стыки — на `--llm`;
  - ответ к другому тексту (расшифровка изменилась) не берётся, задание пишется заново;
  - `--scenario-llm chat` сам включает режим сценариста, и после платного окна;
  - `arl scenario-check <ист>` — что принято, что нет и почему → `exchange/<ист>.scenario.fix.md`.
- `.gitignore` — `exchange/` (текст источника, как `transcripts/`).
- Документация: `PLAN.md` (строка из «план» стала сделанной), `README.md` (переключатель, команда, порядок из 4 шагов), `R0_SPEC.md`, `docs/REEL_SPEC.md`, `PROJECT_STRUCTURE.md`.
- `tests/test_m207_chat_scenarist.py` — 7 тестов; без подключения в `__main__.py` 5 из них падают.

Ассистент прогнал весь набор: 2668 прошли (было 2661 + 7), упали прежние 7.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить. Расхождение чисел — не СТОП.
2. Перед стартом не должно идти других `arl` и рендера: `pgrep -fl "autoreels|ffmpeg"`.
3. **НЕ МЕНЯТЬ:**
   - ничего, кроме того, что вносит патч;
   - `.env`, `config/r0.yaml` не трогать;
   - гейты и их `reviews/*` не трогать.

   **Без рендера.** `arl export`, `arl crosspost` и сетку не запускать. `data/token_scale.json` не коммитить.
4. Итог — «IMPLEMENTED, VERIFIED». Гейт не объявлять.

## Часть 0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m207
ls reviews/*_auto_all_t206.txt | wc -l; grep -c "сценарист: ответ из кэша" handoff/m206/t206.txt
```
Ожидается:
- ветка `main`, последний коммит — M206b (`13af9bd`);
- черновиков t206 — `7`, строк «ответ из кэша» — `7`.

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git apply --check handoff/m207/m207-chat-scenarist.patch && git apply handoff/m207/m207-chat-scenarist.patch && echo applied
.venv/bin/python -m pytest tests/test_m207_chat_scenarist.py tests/test_m153_auto_mode.py tests/test_scenario.py -q 2>&1 | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add .gitignore PLAN.md PROJECT_STRUCTURE.md R0_SPEC.md README.md docs/REEL_SPEC.md src/autoreels/__main__.py src/autoreels/cloud/chatscenario.py tests/test_m207_chat_scenarist.py
git commit -m "Chat scenarist (M207): --scenario-llm chat — the scenarist's task one file exchange/<src>.scenario.md for any chat, the answer back in exchange/<src>.scenario.answer.txt, the same parse and checks; the source waits for the chat (no autocut in its place); arl scenario-check writes the refused lines as a message for the chat; an answer to another text is not used; docs"
git push; git log --oneline -1
git status -s | grep -v "handoff/\|data/token_scale.json" || echo "всё закоммичено"
```
Ожидается:
- `applied`;
- первая строка pytest — все прошли;
- весь набор — прежнее число плюс 7 (флейк `test_menu_bash::…profile_picker…` — перезапустить отдельно);
- коммит запушен; «всё закоммичено».

## Часть 2. Доказательство без рендера: путь через чат = путь через API
Как «ответ чата» берётся ответ Sonnet из кэша сценариста — тот самый, на котором собран t206. Тогда путь через чат обязан дать те же черновики байт в байт: ответ тот же, код проверок тот же, плашки и `k:` — из кэша ответов (`record`).
```bash
cd /Users/danny/Documents/autoreels
S7=(disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny)
# 1) задания: каждый источник ждёт ответа чата
.venv/bin/python -m autoreels auto "${S7[@]}" --scenario-llm chat --llm cloud --gate c207 --tag c207 --no-render > handoff/m207/wait.txt 2>&1; echo "ожидание: код $?"
sed -n '/=== auto: итог/,$p' handoff/m207/wait.txt
ls -la exchange/ | grep scenario.md | wc -l; wc -c exchange/*.scenario.md | tail -1
head -12 exchange/day_yoga_p1.scenario.md | tee handoff/m207/task_head.txt
# 2) «ответ чата» = ответ Sonnet из кэша, на котором собран t206
.venv/bin/python - <<'EOF'
import re, shutil
from pathlib import Path
log = Path("handoff/m206/t206.txt").read_text(encoding="utf-8", errors="replace")
for name in re.findall(r"сценарист: ответ из кэша (\S+\.txt)", log):
    stem = name.split(".")[0]
    shutil.copyfile(Path("data/cache/scenario") / name, Path("exchange") / f"{stem}.scenario.answer.txt")
    print("ответ:", stem, "←", name)
EOF
# 3) проверка ответа
for s in "${S7[@]}"; do .venv/bin/python -m autoreels scenario-check "$s" 2>&1 | grep "^scenario-check"; done | tee handoff/m207/check.txt
head -8 exchange/prew_isaev_anna.scenario.fix.md | tee handoff/m207/fix_head.txt
# 4) сборка по «ответам чата» и сравнение с t206
.venv/bin/python -m autoreels auto "${S7[@]}" --scenario-llm chat --llm cloud --gate c207 --tag c207 --no-render > handoff/m207/c207.txt 2>&1; echo "сборка: код $?"
sed -n '/=== auto: итог/,$p' handoff/m207/c207.txt
{ for s in "${S7[@]}"; do printf "%-18s %s\n" "$s" "$(cmp -s reviews/${s}_auto_all_t206.txt reviews/${s}_auto_all_c207.txt && echo одинаковый || echo РАЗНЫЙ)"; done; } | tee handoff/m207/same.txt
for s in "${S7[@]}"; do cmp -s reviews/${s}_auto_all_t206.txt reviews/${s}_auto_all_c207.txt || diff reviews/${s}_auto_all_t206.txt reviews/${s}_auto_all_c207.txt | head -20; done > handoff/m207/diff.txt; wc -l < handoff/m207/diff.txt
git status -sb | head -5
```
Ожидается:
- **ожидание:** код 1; у всех 7 «остановлен на „сценарист через чат“ — ждёт ответа чата»; заданий — `7`; в `task_head.txt` — шаги владельцу; строк «взят автомонтаж» нет;
- **ответы:** скопированы 7;
- **check.txt:** 7 строк «принято N, не принято K». K — те же отказы, что у API-сценариста;
- **сборка:** код 0, у всех 7 `✓`, «промахов 0»;
- **same.txt:** 7 из 7 «одинаковый», `diff.txt` — 0 строк;
- `git status` чистый вне `handoff/` (`exchange/` в `.gitignore`).

«РАЗНЫЙ» — не СТОП: выписать источники и первые строки `diff.txt`.

## Отчёт
`handoff/m207/REPORT.md`:
```
M207 — IMPLEMENTED, VERIFIED
Коммит: <хэш>; pytest: N passed (было M)
Ожидание: код <…>, заданий <7>, размер заданий <байт всего>; автомонтаж вместо чата: <нет>
scenario-check (check.txt): <по источникам: принято/не принято>
Сборка c207: код <…>; одинаковых с t206: <x>/7; diff.txt: <строк>
Пропущено/не совпало: …
```
```bash
bash handoff/bin/report.sh m207 wait.txt task_head.txt check.txt fix_head.txt c207.txt same.txt diff.txt
```
Владельцу в чат — 3 строки:
1. статус и коммит;
2. «сценарист через чат: задание `exchange/<ист>.scenario.md` → чат → ответ `exchange/<ист>.scenario.answer.txt` → `arl scenario-check` → `arl auto <ист> --scenario-llm chat`»;
3. «путь через чат = путь через API: <x>/7 черновиков байт в байт».
