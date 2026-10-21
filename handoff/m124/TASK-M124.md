# TASK M124 (окно MAIN, Mac): двойная расшифровка Groq для новых видео; покрытие сценариста

Файлы — в ветке `handoff`, папка `handoff/m124/`: `TASK-M124.md`, `m124-dual.patch`, `owner_drafts.py`, `decide_tx.py`.

**Ставится поверх M123** (последний коммит — «Tests (M123): a recorded answer…»). Около 40 минут, из них до ~30 — Groq. gamebox не нужен.

## Зачем
1. **Расшифровка новых видео.** С подсказкой (`initial_prompt`) Groq теряет слова: на IMG_6848 — 66% слов whisper.cpp, на Pxl 112938952 — 78%. Ещё он вписывает подсказку в текст: «Каждый из них влияет на результат по-своему.» стала началом клипа. Без подсказки слов 89–93%, но точек втрое меньше.

   M118 показал: слова без подсказки плюс точки с подсказкой дают 7,5–12 концов на 100 слов при 89–93% слов, без вставок.

   Патч делает это сразу при расшифровке: `groq.dual` в `config/transcribe.yaml` — два прохода Groq на каждый кусок. Флаг по умолчанию выключен. Готовые источники не трогаются.
2. **Покрытие сценариста.** У черновиков m123-scen не было строк с номерами мыслей, поэтому `owner_drafts` показал 0. Теперь сценарист пишет эти строки, а новый скрипт берёт мысли по фразам строки M — уже готовые черновики можно посчитать без повторного запуска.

Включение `groq.dual` по умолчанию — по правилу, объявленному заранее (`decide_tx.py`). Все три условия на IMG_6848:
- слов whisper.cpp ≥ 85%;
- концов предложений ≥ 7 на 100 слов;
- известных выдумок 0.

## Правила
1. Любой шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить.
2. Перед стартом не должно идти других `arl` и рендера. Если в pytest упал только `tests/test_menu_bash.py::test_menu_settings_profile_picker_and_cancel` — перезапустить его один раз; прошёл — не СТОП, отметить.
3. Не трогать `reviews/*_answer.txt`, `reviews/*.review.json`, `reviews/verdicts.jsonl`, черновики, `manifests/`. `arl tx-use`, `arl auto`, `arl render` не запускать: источники остаются на своих расшифровках.
4. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -1; git log --oneline -1; pgrep -fl "arl " || echo "arl не запущен"
git apply --check handoff/m124/m124-dual.patch && git apply handoff/m124/m124-dual.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add config/transcribe.yaml docs/REEL_SPEC.md src/autoreels/__main__.py src/autoreels/cloud/scenario.py src/autoreels/cloud/transcribe.py src/autoreels/core/config.py tests/test_scenario.py tests/test_transcribe_dual.py
git commit -m "Transcribe (M124): Groq in two passes — words without the prompt, sentence ends with it (groq.dual, off); tx-compare --groq-dual; the scenarist writes the map's thoughts of each reel"
git push; git log --oneline -1
```
Ожидается: `applied`; pytest — все прошли (3 новых в `tests/test_transcribe_dual.py`); коммит запушен.

## Шаг 2. Покрытие клипов владельца у сценариста m123
```bash
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m124
.venv/bin/python handoff/m124/owner_drafts.py m122 m123 m123-scen 2>&1 | tee handoff/m124/drafts.txt
```
Ожидается: строки m123-scen с числом сборок (13, 4, 16) и покрытием по трём источникам; «ВСЕГО».

## Шаг 3. Двойная расшифровка IMG_6848 — замер
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
{ arl tx-compare IMG_6848 --groq-dual --tag dual 2>&1 | grep -vE "^  …" | tail -12
  .venv/bin/python handoff/m118/tx_variants.py IMG_6848 local-m111-novad groq-noprompt groq-noprompt-gp groq-dual; } 2>&1 | tee handoff/m124/tx.txt
.venv/bin/python handoff/m124/decide_tx.py handoff/m124/tx.txt | tee handoff/m124/decide.txt
```
Ожидается:
- `transcripts/IMG_6848.groq-dual.transcript.json` записан;
- в таблице пять строк: Groq с подсказкой (сейчас), groq-noprompt, groq-noprompt-gp, groq-dual, whisper.cpp;
- последняя строка `decide.txt` — `включить` или `оставить выключенным`.

Ожидание лимита Groq (429) — не СТОП: код ждёт сам.

## Шаг 4. Включить по правилу
Выполнять только если последняя строка `decide.txt` — `включить`:
```bash
cd /Users/danny/Documents/autoreels
sed -i '' 's/^  dual: false$/  dual: true/' config/transcribe.yaml && grep -n "^  dual:" config/transcribe.yaml
.venv/bin/python -m pytest -q tests/test_transcribe_dual.py 2>&1 | tail -1
git add config/transcribe.yaml
git commit -m "Transcribe (M124): groq.dual on for new videos (m124 IMG_6848: the rule in decide_tx.py held)"
git push; git log --oneline -1
```
Ожидается: `dual: true`; тесты прошли; коммит запушен.

## Шаг 5. Отчёт в ветку
Записать `handoff/m124/REPORT.md`:
1. Коммиты, строка pytest.
2. `drafts.txt`.
3. `tx.txt` и `decide.txt`.
4. Выполнен ли шаг 4.

```bash
bash handoff/bin/report.sh m124 drafts.txt tx.txt decide.txt
```
Владельцу в чат — две строки:
- покрытие сценариста против автосборки;
- слова и точки двойной расшифровки, включена ли она для новых видео.
