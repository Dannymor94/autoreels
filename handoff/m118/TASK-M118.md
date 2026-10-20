# TASK M118 (окно MAIN, Mac + gamebox в конце): где автомат теряет клипы владельца; судьи против начал владельца; слова от Groq без подсказки + точки от Groq с подсказкой; подсказки голоса для k: — выключить

Файлы — в ветке `handoff`, папка `handoff/m118/`: `TASK-M118.md`, `m118-keys.patch`, `owner_starts.py`, `owner_funnel.py`, `tx_variants.py`. Скрипт сводки — `handoff/m116/bench_summary.py`.

**Ставится поверх M116** (b4eab15). Одна сессия, без фоновых задач. Около 50 минут, из них ~20 — на gamebox.

## Зачем
Итоги m116/m117:
- **Мало сборок — не из-за модели.** Все модели отбраковывают большую часть начал: Groq — 64%, Haiku — 64%, Sonnet — 84%. Чем сильнее модель, тем она строже и тем меньше сборок. Где правы судьи, а где строже владельца, неизвестно. Ответ дают 65 клипов, которые владелец выбрал сам: их начала он принял. Задаём эти начала каждой модели и считаем, какую долю модель принимает. Модель, которая отбраковывает начала владельца, строже владельца.
- **Подсказка Groq стоит слов.**
  - На IMG_6848 расшифровка с подсказкой содержит лишь 66% слов whisper.cpp, без подсказки — 89,5%. На Pxl 112938952 — 78% и 93%.
  - Вставок подсказки без неё нет, «звука без слов» 45 с вместо 385 с.
  - Зато без подсказки точек втрое меньше: 3,6 вместо 10,3 на 100 слов.
  - Проверяем сочетание: слова от Groq без подсказки, а концы предложений переносятся с Groq с подсказкой на те же слова. Для этого уже есть `arl tx-punct` (M64c), кода не нужно.
- **Подсказки голоса для k: сделали выбор хуже.** С ними Haiku выбрал «потом», «месте», «школу», без них — «инструменты», «отклик», «буллинг». Голос растягивает не только смысл, но и «допустим», «какой-то», «каким-то».
  - Патч выключает подсказки (`autocut.keywords_voice: false`, код остаётся).
  - Слова-связки (`потом`, `допустим`, `какой-то`, `как-то`, `вообще`, `значит`…) код больше не принимает как ключевые, что бы ни сказала модель.

- **Воронка клипов владельца.** 66 клипов, которые владелец выбрал сам, — готовый ответ на вопрос «сколько клипов автомат должен находить». Для каждого проверяем, где он теряется в автоматической сборке:
  - есть ли в нём мысли карты;
  - есть ли «зерно» (сильная мысль, вокруг которой autocut строит сборку);
  - не короче ли он `min_sec`: 14 из 66 клипов владельца короче 25 с;
  - строит ли код без модели сборку с его мыслями;
  - принимает ли судья его начало.

## Правила
1. Любой шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить. Расхождение чисел — не СТОП, это замер.
2. Перед стартом не должно идти других `arl` и рендера. pytest — только в шаге 1. Если в pytest упал только `tests/test_menu_bash.py::test_menu_settings_profile_picker_and_cancel` — перезапустить этот тест один раз. Прошёл — не СТОП: он зависит от времени и под нагрузкой иногда падает, отметить в отчёте.
3. Не трогать то же, что в m116. `arl tx-use`, `arl auto`, `arl render` не запускать: источники остаются на прежних расшифровках.
4. gamebox: озвучку не трогать, `arl` ждёт сам. Если ожидание дольше 30 минут — шаг 4 пропустить, не СТОП, так и написать.
5. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.
6. Итог — «IMPLEMENTED» (патч) и «MEASURED» (замеры).

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -1; git log --oneline -1; pgrep -fl "arl " || echo "arl не запущен"
git apply --check handoff/m118/m118-keys.patch && git apply handoff/m118/m118-keys.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add config/r0.yaml src/autoreels/cloud/autocut.py tests/test_autocut.py
git commit -m "Keywords (M118): voice hints off by default (m116: they led the model to hedges); hedges and fillers are never k: words"
git push; git log --oneline -1
```
Ожидается:
- последний коммит до патча — M116 (b4eab15); `applied`;
- pytest: все прошли (с оговоркой правила 2); коммит запушен.

## Шаг 2. Слова без подсказки + точки с подсказкой
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m118
{
arl tx-punct IMG_6848 --src groq-noprompt
arl tx-punct "Pxl 20260621 112938952" --src groq-noprompt
.venv/bin/python handoff/m118/tx_variants.py IMG_6848 local-m111-novad groq-noprompt groq-noprompt-gp
.venv/bin/python handoff/m118/tx_variants.py "Pxl 20260621 112938952" local-m114-novad groq-noprompt groq-noprompt-gp
} 2>&1 | tee handoff/m118/tx.txt
```
Ожидается:
- по источнику — строка `точки Groq → groq-noprompt: добавлено N; концы предложения на 100 слов: groq-noprompt X → groq-noprompt-gp Y (Groq Z)`;
- две таблицы по четыре строки: Groq с подсказкой (сейчас), без подсказки, без подсказки + точки, whisper.cpp.

## Шаг 3. Начала владельца — Groq, Haiku, Sonnet
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
.venv/bin/python handoff/m118/owner_starts.py
for M in cloud haiku sonnet; do arl judge-bench handoff/m118/owner_starts.jsonl --llm $M --out handoff/m118/owner_$M.jsonl 2>&1 | grep -vE "^  …"; done 2>&1 | tee handoff/m118/run_owner.txt
```
Ожидается:
- `начал владельца: 65` (или около того) и список источников;
- по каждой модели строка `First sentence: ответов N/65, «да» X%, совпало с журналом M/65 (…%)`. «Совпало с журналом» здесь — доля начал владельца, которые модель приняла;
- у Haiku и Sonnet — строка цены.

## Шаг 4. Начала владельца — gamebox (без размышления)
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
arl judge-bench handoff/m118/owner_starts.jsonl --llm local --out handoff/m118/owner_local.jsonl 2>&1 | grep -vE "^  …" | tee -a handoff/m118/run_owner.txt
```
Ожидается: строки замка gamebox и `First sentence: ответов N/65 …`.

## Шаг 4б. Воронка клипов владельца
Черновики «только правила»: всё, что код может предложить без модели и без проверок.
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
for S in "2026-08-08 09h 33m 14s" "2026-08-08 10h 59m 38s" "2026-08-08 11h 42m 49s" "IMG_6848" "Pxl 20260621 112938952" "Pxl 20260621 122006193" "PXL_20260729_085910095_34f06abf"; do
  echo "=== $S"; arl autocut "$S" --llm none --no-check --clips 50 --out "reviews/${S}_auto_m118-rules.txt" 2>&1 | grep -E "^autocut|ошибка"
done 2>&1 | tee handoff/m118/run_rules.txt
.venv/bin/python handoff/m118/owner_funnel.py 2>&1 | tee handoff/m118/funnel.txt
```
Ожидается:
- по источнику строка `autocut …: предложено сборок N` или `ошибка: нет карты …` — это не СТОП, источник без карты воронка пропустит;
- `funnel.txt`: по каждому клипу владельца строка с мыслями, зерном, кандидатом и оценками судей; в конце — воронка и причины потерь.

`arl autocut` только пишет черновик в новый файл и манифест не меняет. Это касается и `PXL_20260729_085910095_34f06abf` (ручной выбор владельца).

## Шаг 5. Сводка
```bash
cd /Users/danny/Documents/autoreels
.venv/bin/python handoff/m116/bench_summary.py handoff/m118/owner_starts.jsonl handoff/m118/owner_cloud.jsonl handoff/m118/owner_haiku.jsonl handoff/m118/owner_sonnet.jsonl $(ls handoff/m118/owner_local.jsonl 2>/dev/null) 2>&1 | tee handoff/m118/owner.txt
git status --short
```
Ожидается: строка `owner_starts ответов 65/65, «да» 100%` и строки моделей; совпадение моделей с владельцем; примеры, где модели отбраковали начало владельца. В `git status` новых строк нет.

## Шаг 6. Отчёт в ветку
Записать `handoff/m118/REPORT.md`:
1. Коммит шага 1, строка pytest.
2. `tx.txt` целиком.
3. `owner.txt` целиком и строки цены из `run_owner.txt`.
4. `funnel.txt` целиком.

```bash
cd /Users/danny/Documents/autoreels
bash handoff/bin/report.sh m118 tx.txt owner.txt funnel.txt run_rules.txt run_owner.txt owner_starts.jsonl owner_cloud.jsonl owner_haiku.jsonl owner_sonnet.jsonl $(cd handoff/m118 && ls owner_local.jsonl 2>/dev/null)
```
Ожидается `отчёт m118 отправлен в ветку handoff`. Владельцу в чат — одна строка: какую долю начал владельца принимает каждая модель, сколько слов и точек у сочетания «без подсказки + точки», «отчёт в ветке».

Статус: IMPLEMENTED (патч); MEASURED (замеры).
