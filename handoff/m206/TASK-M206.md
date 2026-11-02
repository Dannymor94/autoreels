# TASK M206 (окно MAIN, Mac): флаги владельца включены, кэш ответов по умолчанию, `numpy`, документация + в плане «Сценарист через чат»; проверка replay без рендера

Файлы — ветка `handoff`, папка `handoff/m206/`: `TASK-M206.md`, `m206-flags-docs.patch` (написан и прогнан ассистентом, ложится на `main` после M205).
Около 20 минут: один прогон `arl auto` без рендера. Отчёт — только на русском.

## Зачем
Владелец, 2026-11-02:
- «включаем» — `start_morph`, `close_by: sound`, `select: global` (m205: 51 → 54 клипа, «Алгоритм» сохранён);
- текущая фаза — только механики: без нового рендера и пересборки клипов, рендер — только для проверки;
- в план — «Сценарист через чат»: экспорт задания сценаристу одним файлом → любой чат → ответ обратно → обычный путь.

## Что вносит патч
- `config/r0.yaml`:
  - `start_morph: true`, `close_by: sound`, `select: global`;
  - `llm_cache.mode: record` — каждый прогон хранит свои ответы: тот же запрос — тот же ответ.
- `pyproject.toml` — `numpy>=1.26` в зависимостях (была только в ветке `dev` с 18.10; без неё тесты на чистой машине не собираются).
- `tests/conftest.py` — тесты не пишут и не читают настоящий кэш ответов (`ARL_LLM_CACHE=off`; тесты кэша ставят режим сами).
- Тесты, закреплявшие прежние значения конфига (`test_m200`, `test_m202`, `test_m205`), — теперь код по умолчанию прежний, конфиг репо включён; тест «≈ похож» явно ставит `close_by: units`, который проверяет.
- `PLAN.md` — строки M201–M206; плановые строки «**Сценарист через чат** (M207)» и «**Карта без модели** (M208)»; «Начало без опоры» — включено; платного API нет (403).
- `README.md` — переключатели: кэш ответов, `k:`, модель прогона в режиме сценариста, похожесть и отбор.
- `CLAUDE.md` — правило текущей фазы (только механики, платного API нет).
- `docs/REEL_SPEC.md` — `k:` по правилу; похожесть по звуку, глобальный отбор и учёт ушедших кандидатов; «начало без опоры» включено; модель прогона для роликов сценариста.
- `R0_SPEC.md` — сценарист: модели при `scenario_polish`, «Сценарист через чат» (план).
- `PROJECT_STRUCTURE.md` — `cloud/llmcache.py`, `tools/kw_rule_check.py`, число тестов; `PROJECT_GUIDE.md` — `data/cache/llm/`.

Ассистент прогнал весь набор: 2661 прошли, упали прежние 7 (ffmpeg, praat, `data/runs/`).

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить.
2. Перед стартом не должно идти других `arl` и рендера: `pgrep -fl "autoreels|ffmpeg"`.
3. **НЕ МЕНЯТЬ:**
   - ничего, кроме того, что вносит патч;
   - `.env` не трогать;
   - гейты и их `reviews/*` не трогать.

   **Без рендера**, без `--install`. `arl export`, `arl crosspost` и сетку не запускать.
4. `data/cache/llm/` не удалять.
5. Итог — «IMPLEMENTED, VERIFIED». Гейт не объявлять.

## Часть 0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m206
ls reviews/*_auto_all_s205c.txt | wc -l
```
Ожидается:
- ветка `main`, чисто (кроме `handoff/`), последний коммит — M205 (`64b7917`);
- черновиков s205c — `7`.

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git apply --check handoff/m206/m206-flags-docs.patch && git apply handoff/m206/m206-flags-docs.patch && echo applied
grep -n "^  mode:\|  start_morph:\|  close_by:\|  select:" config/r0.yaml; grep -n numpy pyproject.toml
.venv/bin/python -m pytest tests/test_m200_start_morph.py tests/test_m202_replay_accounting.py tests/test_m205_selection.py -q 2>&1 | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add CLAUDE.md PLAN.md README.md R0_SPEC.md PROJECT_STRUCTURE.md PROJECT_GUIDE.md docs/REEL_SPEC.md config/r0.yaml pyproject.toml tests/conftest.py tests/test_m200_start_morph.py tests/test_m202_replay_accounting.py tests/test_m205_selection.py
git commit -m "Flags and docs (M206): owner 2026-11-02 — start_morph, close_by sound, select global on; llm_cache record by default (tests isolated); numpy declared; docs for M201–M206 in PLAN, README, CLAUDE.md, REEL_SPEC, R0_SPEC, PROJECT_STRUCTURE, PROJECT_GUIDE; PLAN: the planned chat scenarist (M207) and model-free map (M208); CLAUDE.md: the mechanics-only phase"
git push; git log --oneline -1
git status -s | grep -v "handoff/" || echo "всё закоммичено"
```
Ожидается:
- `applied`;
- `mode: record`, `start_morph: true`, `close_by: sound`, `select: global`; строка `numpy`;
- после коммита — «всё закоммичено» (вне `handoff/` ничего не висит);
- первая строка pytest — все прошли;
- весь набор — прежнее число (новых тестов нет), упавших не больше прежних (флейк `test_menu_bash::…profile_picker…` — перезапустить отдельно);
- коммит запушен.

## Часть 2. Проверка без рендера: replay с новыми значениями = s205c
s205c шёл ровно с этими флагами (`start_morph`, `sound`, `global`) в `record`. Новый конфиг по умолчанию должен дать те же черновики байт в байт, без единого нового запроса.
```bash
cd /Users/danny/Documents/autoreels
S7=(disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny)
ARL_LLM_CACHE=replay .venv/bin/python -m autoreels auto "${S7[@]}" --mode scenario --llm cloud --gate t206 --tag t206 --no-render > handoff/m206/t206.txt 2>&1; echo "replay: код $?"
sed -n '/=== auto: итог/,$p' handoff/m206/t206.txt
{ for s in "${S7[@]}"; do printf "%-18s %s\n" "$s" "$(cmp -s reviews/${s}_auto_all_s205c.txt reviews/${s}_auto_all_t206.txt && echo одинаковый || echo РАЗНЫЙ)"; done; } | tee handoff/m206/same.txt
for s in "${S7[@]}"; do cmp -s reviews/${s}_auto_all_s205c.txt reviews/${s}_auto_all_t206.txt || diff reviews/${s}_auto_all_s205c.txt reviews/${s}_auto_all_t206.txt | head -20; done > handoff/m206/diff.txt; wc -l < handoff/m206/diff.txt
git status -sb | head -5
```
Ожидается:
- replay: код 0, у всех 7 `✓`, «записано 0, промахов 0»;
- `same.txt` — 7 из 7 «одинаковый», `diff.txt` — 0 строк;
- `git status` чистый вне `handoff/`.

Промахи или «РАЗНЫЙ» — не СТОП: выписать источники, шаги и первые строки `diff.txt`.

## Отчёт
`handoff/m206/REPORT.md`:
```
M206 — IMPLEMENTED, VERIFIED
Коммит: <хэш>; pytest: N passed (было M)
replay t206: код <…>; кэш: из кэша a, записано 0, промахов b; одинаковых с s205c: <x>/7; diff.txt: <строк>
Пропущено/не совпало: …
```
```bash
bash handoff/bin/report.sh m206 t206.txt same.txt diff.txt
```
Владельцу в чат — 2 строки:
1. статус и коммит;
2. «флаги включены, кэш record по умолчанию; replay = s205c <x>/7; „Сценарист через чат“ в плане (M207)».
