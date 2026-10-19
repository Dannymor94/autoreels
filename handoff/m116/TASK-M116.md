# TASK M116 (окно MAIN, Mac; Groq и Claude, gamebox не нужен): какая модель лучше собирает клипы; подсказка Groq без утечки; подсказки голоса для k:

Файлы — в ветке `handoff`, папка `handoff/m116/`:
- `TASK-M116.md`, `m116-models.patch`, `m116-fixture-test.patch`;
- скрипты замера (ничего не пишут): `compare_models.py`, `bench_summary.py`, `groq_prompt_stats.py`.

**Ставится поверх M115** (b151ab1). Одна сессия, без фоновых задач. Около 40–60 минут. Модель на gamebox — в следующей задаче (m117).

## Зачем
Владелец: «Мало сборок — самое важное», «подсказка Groq попадает в текст», «интонация, этап D»; «выяснить разницу между Haiku, Sonnet, Qwen на Groq и Qwen с размышлениями и без». Ключ Claude владелец положил в `.env`. Решение владельца об оплате Claude записано в `CLAUDE.md` (раздел «Технические ограничения»).

**Что в патче:**
1. **Claude как модель.** Новые режимы `--llm haiku | sonnet` (и `local-think` — для m117). В конце прогона печатается цена. Модели и цены — `config/r0.yaml`, раздел `anthropic`.
2. **Ошибка в кэше судей.** Ответы судей начала и крючка кэшировались без учёта того, какая модель ответила. Облачные прогоны m112/m115 могли брать ответы, которые дала модель gamebox в m106/m107. Теперь ключ кэша включает модель, поэтому в этом прогоне каждая модель ответит заново (это ожидаемо).
3. **Журнал суждений и повтор.**
   - `arl autocut … --judge-log <файл>` пишет каждое суждение с точным запросом;
   - `arl judge-bench <файл> --llm <модель>` задаёт те же запросы другой модели — сравнение на одних и тех же началах и тизерах.
4. **Этап D плана M1.9.** Слова, которые голос растягивает (длительность на букву по карте интонации), показываются модели ключевых слов подсказкой «[voice: …]». Выбирает по-прежнему модель, проверки прежние. Флаг `autocut.keywords_voice`; `--no-voice-keys` выключает подсказки для сравнения.
5. **Вариант Groq с другой подсказкой.** `arl tx-compare … --tag <имя> --groq-prompt "<текст>"` (`""` — без подсказки). Нарезка как в работе; результат — `transcripts/<stem>.groq-<имя>.transcript.json`. Кэш и манифест не трогаются.

## Правила
1. Любой шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить. Расхождение чисел между моделями — не СТОП, это замер.
2. Перед стартом не должно идти других `arl` и рендера. pytest — только в шагах 1 и 2.
3. Не трогать:
   - `reviews/*_answer.txt`, `reviews/*_auto_m56.txt`, `reviews/*_auto_all.txt`, `reviews/*_auto_m112.txt`, `reviews/*_auto_m115.txt`;
   - `reviews/*.review.json`, `reviews/verdicts.jsonl`;
   - манифест `PXL_20260729_085910095_34f06abf.json`.

   Черновики этой задачи — новые файлы `reviews/<источник>_auto_m116-<модель>.txt`. `arl auto`, `arl render`, `arl export`, `arl tx-use` не запускать.
4. Ключ Claude никуда не выводить и не копировать: ни в отчёт, ни в вывод команд.
5. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.
6. В `git status` допустимы прежние строки (` M data/blocks_dataset/IMG_6848.jsonl`, ` M data/token_scale.json`, `?? manifests/_archive/`, `??` из `transcripts/` и `*.discarded.json`).
7. Итог — «IMPLEMENTED, GATE PENDING» (код) и «MEASURED» (замеры).

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -1; git log --oneline -1; pgrep -fl "arl " || echo "arl не запущен"
grep -c '^ANTHROPIC_API_KEY=' .env
git apply --check handoff/m116/m116-models.patch && git apply handoff/m116/m116-models.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add CLAUDE.md config/r0.yaml docs/REEL_SPEC.md src/autoreels/__main__.py src/autoreels/cloud/autocut.py src/autoreels/cloud/providers.py src/autoreels/core/config.py tests/test_autocut.py tests/test_models_m116.py
git commit -m "Models (M116): Claude as a provider (--llm haiku|sonnet, cost line) and the reasoning local model (local-think); the judge cache keyed by the answering model; autocut --judge-log + arl judge-bench; voice hints for k: (M1.9 D); tx-compare --groq-prompt"
git push; git log --oneline -1
```
Ожидается:
- последний коммит до патча — M115 (b151ab1); `arl не запущен`;
- `grep -c` печатает `1` (ключ в `.env` есть; если `0` — **СТОП**);
- `applied`; pytest: все прошли (если что-то упало — **СТОП**, не коммитить); коммит запушен.

## Шаг 2. Настоящий ответ Claude — фикстура и тест на ней
```bash
cd /Users/danny/Documents/autoreels
.venv/bin/python - <<'EOF'
import json, os, httpx
from autoreels.__main__ import _load_env
_load_env()
key = os.environ["ANTHROPIC_API_KEY"].strip()
h = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
body = {"model": "claude-haiku-5-5", "max_tokens": 60, "system": "Answer only with JSON.",
        "messages": [{"role": "user", "content": "First sentence: «Страх нас защищает.» Does it make sense on its own? "
                                                   "Answer {\"ok\": true|false, \"why\": \"<2 words>\"}"}]}
r = httpx.post("https://api.anthropic.com/v1/messages", headers=h, json=body, timeout=60)
print("HTTP", r.status_code)
if r.status_code != 200:
    print(r.text[:300])
    m = httpx.get("https://api.anthropic.com/v1/models", headers=h, timeout=30)
    print("модели:", [x.get("id") for x in (m.json().get("data") or [])] if m.status_code == 200 else m.status_code)
    raise SystemExit(1)
d = r.json(); d["id"] = "msg_recorded"
json.dump({"provenance": "A real Messages API answer of claude-haiku-5-5, recorded by the m116 run (the id replaced)",
           "response": d}, open("tests/fixtures/anthropic_messages_envelope.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("текст:", "".join(b.get("text", "") for b in d["content"] if b.get("type") == "text")[:120], "| usage:", d.get("usage"))
EOF
git apply --check handoff/m116/m116-fixture-test.patch && git apply handoff/m116/m116-fixture-test.patch && echo applied
.venv/bin/python -m pytest tests/test_models_m116.py -q 2>&1 | tail -2
git add tests/fixtures/anthropic_messages_envelope.json tests/test_models_m116.py
git commit -m "Tests (M116): a recorded Claude Messages API answer as a fixture"
git push; git log --oneline -1
```
Ожидается:
- `HTTP 200`, текст с JSON, `usage` с числами;
- `applied`, тесты файла прошли, коммит запушен.

Если не `HTTP 200` — **СТОП**: в отчёт код ответа и список моделей (имя модели в `config/r0.yaml` могло устареть).

## Шаг 3. Сборки трёх источников тремя моделями: Groq, Haiku, Sonnet
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m116
rm -f handoff/m116/run_*.txt handoff/m116/judge_*.jsonl handoff/m116/bench_*.jsonl
for M in cloud haiku sonnet; do
  for S in "IMG_6848" "2026-08-08 11h 42m 49s" "Pxl 20260621 112938952"; do
    { echo "=== $S"; /usr/bin/time -p .venv/bin/python -m autoreels autocut "$S" --llm $M --out "reviews/${S}_auto_m116-$M.txt" --judge-log handoff/m116/judge_$M.jsonl; } 2>&1 | tee -a handoff/m116/run_$M.txt | grep -E "^autocut|Claude |^real|ошибка"
  done
done
wc -l handoff/m116/judge_*.jsonl
```
Ожидается:
- по каждой модели и источнику — строка `autocut …: предложено сборок N …` и `real …`;
- у `haiku` и `sonnet` — строка `Claude claude-…: запросов …, вход …, ответ … токенов ≈ $…`;
- три журнала `judge_cloud.jsonl`, `judge_haiku.jsonl`, `judge_sonnet.jsonl`, в каждом — строки.

## Шаг 4. Одни и те же суждения — разными моделями
За общий набор запросов берётся журнал Groq.
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
for M in haiku sonnet; do arl judge-bench handoff/m116/judge_cloud.jsonl --llm $M --out handoff/m116/bench_$M.jsonl 2>&1 | tee -a handoff/m116/run_bench.txt | grep -vE "^  …"; done
```
Ожидается: по каждой модели — строка `judge-bench … → anthropic:…: запросов N`, строки по видам суждений и строка цены.

## Шаг 5. Подсказки голоса для k: — с ними и без (Haiku)
Суждения Haiku уже в кэше, поэтому сборки выйдут те же, а разница будет только в k:.
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
for S in "IMG_6848" "2026-08-08 11h 42m 49s" "Pxl 20260621 112938952"; do
  { echo "=== $S"; arl autocut "$S" --llm haiku --no-voice-keys --out "reviews/${S}_auto_m116-haiku-novoice.txt"; } 2>&1 | tee -a handoff/m116/run_haiku-novoice.txt | grep -E "^autocut|Claude "
done
{
.venv/bin/python handoff/m116/compare_models.py haiku haiku-novoice
echo; echo "--- подсказки голоса в черновиках Haiku:"
grep -h "голос выделяет" reviews/*_auto_m116-haiku.txt
} 2>&1 | tee handoff/m116/voice.txt
```
Ожидается:
- сборки `haiku` и `haiku-novoice` совпадают по составу (строки `M…`), различаются только `k:`;
- строки `голос выделяет: B.N «слово», …`. Если их нет ни в одном черновике — не СТОП: значит, нет карты интонации, так и написать.

## Шаг 6. Groq без подсказки — на двух источниках
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
{
arl tx-compare IMG_6848 --tag noprompt --groq-prompt ""
arl tx-compare "Pxl 20260621 112938952" --tag noprompt --groq-prompt ""
.venv/bin/python handoff/m116/groq_prompt_stats.py IMG_6848 noprompt local-m111-novad
.venv/bin/python handoff/m116/groq_prompt_stats.py "Pxl 20260621 112938952" noprompt local-m114-novad
} 2>&1 | tee handoff/m116/groq.txt | grep -vE "транскрипция|chunk"
git status --short
```
Ожидается:
- по источнику — `Groq: initial_prompt пустой` и блок `== … (локально: N с): слов Groq …`;
- две таблицы из трёх строк: Groq с подсказкой, Groq без подсказки, whisper.cpp;
- в `git status` новых строк нет.

Если Groq упрётся в часовой лимит на звук (ошибка 429 после повторов), это не СТОП. Подождать 20 минут и повторить команду этого источника один раз; если снова 429 — записать в отчёт и идти дальше.

## Шаг 7. Сводки
```bash
cd /Users/danny/Documents/autoreels
.venv/bin/python handoff/m116/compare_models.py cloud haiku sonnet 2>&1 | tee handoff/m116/models.txt
.venv/bin/python handoff/m116/bench_summary.py handoff/m116/judge_cloud.jsonl handoff/m116/bench_haiku.jsonl handoff/m116/bench_sonnet.jsonl 2>&1 | tee handoff/m116/bench.txt
```
Ожидается: таблицы по источникам и по видам суждений, примеры расхождений.

## Шаг 8. Отчёт в ветку
Записать `handoff/m116/REPORT.md`:
1. Коммиты шагов 1–2, строки pytest.
2. `models.txt` целиком: сборки и плашки по моделям, время и цена.
3. `bench.txt` целиком: одни и те же суждения у трёх моделей.
4. `voice.txt` целиком.
5. Таблицы из `groq.txt`.
6. Итого по цене: сумма строк `Claude …` из `run_haiku.txt`, `run_sonnet.txt`, `run_bench.txt`.

```bash
cd /Users/danny/Documents/autoreels
bash handoff/bin/report.sh m116 models.txt bench.txt voice.txt groq.txt run_cloud.txt run_haiku.txt run_sonnet.txt run_bench.txt judge_cloud.jsonl bench_haiku.jsonl bench_sonnet.jsonl
```
Ожидается `отчёт m116 отправлен в ветку handoff`. Владельцу в чат — одна строка: сколько сборок у каждой модели на трёх источниках и сколько стоил Claude, «отчёт в ветке; дальше m117 (gamebox)».

Статус: IMPLEMENTED, GATE PENDING (код); MEASURED (замеры).
