# TASK M202 (окно MAIN, Mac): кэш ответов моделей (record / replay) и учёт кандидатов autocut; доказать воспроизводимость на 7 источниках

Файлы — ветка `handoff`, папка `handoff/m202/`: `TASK-M202.md`, `m202-replay-accounting.patch` (написан и прогнан ассистентом, ложится на `main` **после M201**).
Около 30–40 минут: два прогона `arl auto` без рендера. Отчёт — только на русском.

## Зачем
Владелец, 2026-11-02: «максимально детерминированно». Сейчас один и тот же `arl auto` даёт разный черновик в зависимости от того, что ответили модели в этот день (m200: модель молчала, плашки, `k:` и стыки тихо остались без неё). A/B правки кода поэтому смешивает разницу кода и разницу ответов. И кандидат, ушедший как «похожий» или «не дошла очередь», в консоли не виден (m200: «Алгоритм или эмпатия»).

## Что вносит патч
- `cloud/llmcache.py` + `llm_cache` в `config/r0.yaml` (по умолчанию `"off"` — всё как раньше). Переменная `ARL_LLM_CACHE=off|record|replay` переопределяет режим на один прогон:
  - `record` — сохранённый ответ возвращается без запроса, новый запрашивается и сохраняется в `data/cache/llm/`;
  - `replay` — только сохранённые ответы; промах считается, `arl auto` завершается кодом 1 со строкой «прогон НЕ воспроизведён».

  Ключ — модель + сообщения + температура (sha256). Обёртка стоит в `_make_pool`, то есть на всех шагах `arl auto`.
- autocut: консоль показывает каждого ушедшего кандидата — `≈` похож на принятый (с причиной), `○` без крючка, `…` не дошла очередь. В черновик добавлен раздел «не дошла очередь». Сумма категорий сверяется с пулом; при расхождении — строка `⚠ учёт кандидатов`.
- `CLAUDE.md`, «Дисциплина разработки» — два правила: A/B кода на `replay`; каждый ушедший кандидат виден с причиной.
- `tests/test_m202_replay_accounting.py` — 10 тестов; без кода патча они не собираются.

Выход клипов при `mode: "off"` не меняется. Ассистент прогнал весь набор поверх M201: 2641 прошли. Упали 8: прежние 7 (ffmpeg, praat, `data/runs/`) и `test_menu_bash::test_menu_settings_profile_picker_and_cancel` под нагрузкой полного набора; отдельно он прошёл 4 из 4 — это флейк по времени, не патч.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить. Расхождение чисел и промахи replay в части 2 — не СТОП, это замер.
2. Перед стартом не должно идти других `arl` и рендера: `pgrep -fl "autoreels|ffmpeg"`.
3. **НЕ МЕНЯТЬ:**
   - ничего, кроме того, что вносит патч;
   - `llm_cache.mode` в `config/r0.yaml` оставить `"off"` — режим задаётся только переменной на время прогона;
   - `.env` не трогать;
   - гейты `m183`, `m196`, `m200` и их `reviews/*` не трогать.

   Без рендера, без `--install`. `arl export`, `arl crosspost` и сетку не запускать.
4. `data/cache/llm/` после прогона **не удалять**: это замороженные ответы для следующих A/B (m203).
5. Итог — «IMPLEMENTED, MEASURED». Гейт не объявлять.

## Часть 0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -3; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m202
git log --oneline -5 | grep -c "M201"; head -4 handoff/m201/REPORT.md
```
Ожидается:
- ветка `main`, чисто (кроме `handoff/`);
- коммит M201 есть (`1`), отчёт M201 есть. Если M201 не выполнена — **СТОП**: «сначала m201».

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git apply --check handoff/m202/m202-replay-accounting.patch && git apply handoff/m202/m202-replay-accounting.patch && echo applied
.venv/bin/python -m pytest tests/test_m202_replay_accounting.py tests/test_m201_provider_errors.py tests/test_scenario.py tests/test_autocut.py -q 2>&1 | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -3
grep -n -A2 "^llm_cache:" config/r0.yaml
git add CLAUDE.md config/r0.yaml src/autoreels/__main__.py src/autoreels/cloud/llmcache.py src/autoreels/core/config.py tests/test_m202_replay_accounting.py
git commit -m "Replay (M202): the models' answers kept per request — llm_cache off|record|replay (ARL_LLM_CACHE), a replay miss fails arl auto; autocut shows every candidate that went (≈ too close, ○ hookless, … not reached) and checks the count against the pool; CLAUDE.md: A/B of code on replay"
git push; git log --oneline -1
```
Ожидается:
- `applied`;
- первая строка pytest — все прошли;
- весь набор — прежнее число плюс 10. Если упал только `test_menu_bash::…profile_picker…` — перезапустить его отдельно; прошёл → не СТОП, записать;
- `mode: "off"`;
- коммит запушен.

## Часть 2. Воспроизводимость: record, затем replay на тех же 7 источниках
Модель для карты, судей и плашек: если в `handoff/m201/ping.txt` sonnet «ОТВЕТИЛ» — флаг не нужен (`LLM=()`); если «НЕ ОТВЕТИЛ» — бесплатные модели (`LLM=(--llm cloud)`). Сценарист отвечает из своего кэша, как в m200.
```bash
cd /Users/danny/Documents/autoreels
grep -q "sonnet: ОТВЕТИЛ" handoff/m201/ping.txt && LLM=() || LLM=(--llm cloud); echo "модель: ${LLM[*]:-по умолчанию}"
S7=(disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny)
ARL_LLM_CACHE=record .venv/bin/python -m autoreels auto "${S7[@]}" "${LLM[@]}" --gate rp1 --tag rp1 --no-render > handoff/m202/rp1.txt 2>&1; echo "record: код $?"
ARL_LLM_CACHE=replay .venv/bin/python -m autoreels auto "${S7[@]}" "${LLM[@]}" --gate rp2 --tag rp2 --no-render > handoff/m202/rp2.txt 2>&1; echo "replay: код $?"
for f in rp1 rp2; do echo "== $f"; sed -n '/=== auto: итог/,$p' handoff/m202/$f.txt; done
{ for s in "${S7[@]}"; do
    a=reviews/${s}_auto_all_rp1.txt; b=reviews/${s}_auto_all_rp2.txt; ja=reviews/${s}_rp1.review.json; jb=reviews/${s}_rp2.review.json
    printf "%-18s черновик %s; review.json %s\n" "$s" "$(cmp -s "$a" "$b" && echo одинаковый || echo РАЗНЫЙ)" "$(cmp -s "$ja" "$jb" && echo одинаковый || echo РАЗНЫЙ)"
  done; } | tee handoff/m202/same.txt
for s in "${S7[@]}"; do cmp -s reviews/${s}_auto_all_rp1.txt reviews/${s}_auto_all_rp2.txt || diff reviews/${s}_auto_all_rp1.txt reviews/${s}_auto_all_rp2.txt | head -20; done > handoff/m202/diff.txt; wc -l < handoff/m202/diff.txt
grep -c "учёт кандидатов" handoff/m202/rp1.txt
grep -hE "^  (≈|○|…) " handoff/m202/rp1.txt | tee handoff/m202/went.txt | wc -l
grep -h "модель не ответила" handoff/m202/rp1.txt | sed 's/.*модель не ответила/модель не ответила/' | sort | uniq -c | sort -rn | head -5
du -sh data/cache/llm; find data/cache/llm -name '*.json' | wc -l
git status -sb | head -5
```
Ожидается:
- record: код 0, у всех 7 `✓`, строка «кэш моделей: из кэша …, записано N, промахов 0»;
- replay: код 0, «записано 0, промахов 0»; в `same.txt` все 14 — «одинаковый»; `diff.txt` — 0 строк;
- «учёт кандидатов» — 0;
- `went.txt` — строки `≈ / ○ / …` с причинами (у prew_isaev_anna ожидается `≈ … 20.10` или `20.9` — «Алгоритм или эмпатия»);
- `data/cache/llm` — файлы есть; `git status` чистый вне `handoff/`.

Если replay дал промахи или «РАЗНЫЙ» — не СТОП: выписать, какие источники и шаги («модель не ответила» в rp1 = эти запросы не сохранились, их и не хватило в rp2).

## Отчёт
`handoff/m202/REPORT.md`:
```
M202 — IMPLEMENTED, MEASURED
Коммит: <хэш>; pytest: N passed (было M); флейк menu: <да/нет>
Модель прогонов: <по умолчанию / --llm cloud>
record: код <0/1>; кэш: из кэша a, записано b, промахов 0
replay: код <0/1>; кэш: из кэша c, записано 0, промахов d
Одинаковые черновики/review.json: <x из 7 / y из 7>; diff.txt: <строк>
Учёт кандидатов: расхождений <0>; ушедших с причиной: ≈ <n>, ○ <n>, … <n>; prew_isaev_anna: <строка «Алгоритм»>
Кэш: <размер, файлов>
Пропущено/не совпало: …
```
```bash
bash handoff/bin/report.sh m202 rp1.txt rp2.txt same.txt diff.txt went.txt
```
Владельцу в чат — 3 строки:
1. статус и коммит;
2. «воспроизводимость: replay код <…>, одинаковых черновиков <x>/7»;
3. «„Алгоритм“: <причина из went.txt>; кэш ответов сохранён для m203».
