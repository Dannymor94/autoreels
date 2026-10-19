# TASK M113 (окно MAIN, Mac + gamebox): точки после распознавания — модель расставляет концы предложений; починка калибровки токенов Groq

Файлы — в ветке `handoff`, папка `handoff/m113/`: `TASK-M113.md`, `m113-punct.patch`, `m113-fixture-test.patch`.

**Ставится поверх M112** (eb193c5). Одна сессия, без фоновых задач. Около получаса: облако ~5 мин, gamebox ~20 мин.

## Зачем
1. **Точки.** M111 показал: флаги whisper.cpp точек не возвращают. Лучший вариант (без VAD) даёт 5.5 конца предложения на 100 слов, Groq — 10.3. При этом свои точки whisper.cpp ставит верно: 90 % из них есть и у Groq. Значит, точки нужно добавлять после распознавания.
   - Новый режим `arl tx-punct --by llm`: модель видит кусок по 120 слов с номерами и называет номера слов, на которых кончается предложение. Знаки ставит код.
   - Слова, время и уже стоящие знаки не меняются. Ответ с номером вне куска не принимается; после второго непринятого ответа кусок остаётся как был, и это видно в выводе.
   - `--llm local` — всё остаётся на gamebox.
   - Меряем на расшифровке `local-m111-novad` из M111 против Groq, теми же строками, что в `tx-compare`.
2. **Калибровка токенов Groq (баг, найден в логе m112).**
   - Калибровка вычитала из числа токенов запроса 400 — это запас для ожидания квоты, а не реальная служебная часть (~13 токенов). На коротких запросах (судьи и плашки autocut) коэффициент выходил отрицательным: в m112 он ушёл до −0.04 и записан в `data/token_scale.json`.
   - Следующий R0 ждал бы квоту так, будто текст запроса ничего не стоит.
   - Теперь вычитается реальная служебная часть. Значение вне 0.5–3.0 не учитывается и не загружается с диска (сегодняшнее −0.04 будет отброшено с предупреждением).
3. **Фикстура реальных ответов.** Тесты разбора ответа пока на рукописных ответах: реальных ещё не было. Прогон шага 2 сохраняет ответы моделей. В шаге 4 из них делается фикстура и тест на ней (правило CLAUDE.md: фикстуры — реальные ответы).

## Правила
1. Любой шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить. Исключение — шаг 3 (gamebox): его ошибка не СТОП, она идёт в отчёт.
2. Перед стартом не должно идти других `arl` и рендера. pytest — только в шагах 1 и 4.
3. gamebox: озвучку не трогать. Если замок занят, `arl` ждёт сам. llama-server `arl` запустит сам и сам же остановит, если запускал.
4. `transcripts/IMG_6848.local*.transcript.json` из M111 не менять: результаты пишутся в новые файлы `…-lpc`, `…-lpl`. `arl tx-use` не запускать: источник остаётся на прежней расшифровке.
5. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.
6. В `git status` допустимы прежние строки (` M data/blocks_dataset/IMG_6848.jsonl`, ` M data/token_scale.json`, `?? manifests/_archive/`, `??` из `transcripts/` и `*.discarded.json`). `data/token_scale.json` не коммитить.
7. Итог — «IMPLEMENTED, GATE PENDING».

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -1; git log --oneline -1; pgrep -fl "arl " || echo "arl не запущен"
ls transcripts/IMG_6848.local-m111-novad.transcript.json
cat data/token_scale.json
git apply --check handoff/m113/m113-punct.patch && git apply handoff/m113/m113-punct.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add config/r0.yaml docs/REEL_SPEC.md src/autoreels/__main__.py src/autoreels/cloud/providers.py src/autoreels/cloud/txcheck.py src/autoreels/core/config.py tests/test_providers.py tests/test_whispercpp.py
git commit -m "Transcription (M113): arl tx-punct --by llm — the model names the words that end a sentence, the code puts the marks (words, times, existing marks untouched); Groq token calibration subtracts the real template cost, not the 400-token pacing buffer (m112 drove the scale to -0.04)"
git push; git log --oneline -1
```
Ожидается:
- последний коммит до патча — M112 (eb193c5); `arl не запущен`; файл `local-m111-novad` есть (если нет — **СТОП**);
- `cat` показывает текущие коэффициенты (записать в отчёт как есть);
- `applied`; pytest: все прошли (если что-то упало — **СТОП**, не коммитить); коммит запушен.

## Шаг 2. Точки моделью в облаке
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m113
arl tx-punct IMG_6848 --src local-m111-novad --by llm --llm cloud --out-tag local-m111-novad-lpc 2>&1 | tee handoff/m113/run.txt
cat data/token_scale.json | tee -a handoff/m113/run.txt
```
Ожидается:
- строка `точки моделью (cloud): кусков N, без ответа M, добавлено K …`;
- строка `концы предложения на 100 слов: local-m111-novad 5.5 → local-m111-novad-lpc X (Groq 10.3)`;
- две строки `концы Groq на совпавших словах …` — до и после;
- строк `⚠ Groq token calibration … не учтён` немного или нет вовсе; коэффициент для `qwen/qwen3.8-27b` в `token_scale.json` — между 0.9 и 1.6.

Если в начале есть строка `⚠ Groq token scale … не принят`, это ожидаемо: это −0.04 с прошлого прогона.

## Шаг 3. Точки моделью на gamebox
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
arl tx-punct IMG_6848 --src local-m111-novad --by llm --llm local --out-tag local-m111-novad-lpl 2>&1 | tee -a handoff/m113/run.txt
```
Ожидается то же, что в шаге 2, с `(local)` и `-lpl`, и строки замка gamebox. Ошибка — не СТОП: она попадает в отчёт, дальше шаг 4.

## Шаг 4. Фикстура реальных ответов и тест на ней
```bash
cd /Users/danny/Documents/autoreels
.venv/bin/python - <<'EOF'
import json, os
rows = []
for llm, tag in (("cloud", "lpc"), ("local", "lpl")):
    f = f"transcripts/IMG_6848.local-m111-novad-{tag}.punct_raw.json"
    if not os.path.exists(f):
        print(f"нет {f}"); continue
    d = json.load(open(f, encoding="utf-8"))
    for a in d["answers"][:4]:
        rows.append({"llm": llm, "k": a["k"], "raw": a["raw"]})
    print(f"{llm}: ответов {len(d['answers'])}, непринятых {sum(not a['ok'] for a in d['answers'])}")
json.dump({"provenance": "Real answers to cloud/txcheck.PUNCT_SYSTEM: the first four of each model in the m113 run of "
                         "arl tx-punct IMG_6848 --src local-m111-novad --by llm (cloud = Groq/OpenRouter pool, "
                         "local = gamebox llama-server), as they came.",
           "answers": rows}, open("tests/fixtures/punct_answers.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("ответов в фикстуре:", len(rows))
EOF
git apply --check handoff/m113/m113-fixture-test.patch && git apply handoff/m113/m113-fixture-test.patch && echo applied
.venv/bin/python -m pytest tests/test_whispercpp.py -q 2>&1 | tail -3
git add tests/fixtures/punct_answers.json tests/test_whispercpp.py
git commit -m "Tests (M113): real model answers to the sentence-end prompt as a fixture (m113 run on IMG_6848)"
git push; git log --oneline -1
```
Ожидается:
- строки `cloud: ответов …` (и `local: …`, если шаг 3 прошёл), `ответов в фикстуре: 4` или `8`;
- `applied`; тесты файла прошли. Если `test_m113_real_model_answers_parse` упал — **СТОП**: в отчёт — его вывод (какой ответ не разобран);
- коммит запушен.

## Шаг 5. Образец текста — до и после
```bash
cd /Users/danny/Documents/autoreels
.venv/bin/python - <<'EOF' | tee handoff/m113/sample.txt
import json, os
for tag in ("local-m111-novad", "local-m111-novad-lpc", "local-m111-novad-lpl"):
    f = f"transcripts/IMG_6848.{tag}.transcript.json"
    if not os.path.exists(f):
        continue
    ws = json.load(open(f, encoding="utf-8"))["words"]
    print(f"=== {tag} (слова 1001–1150)\n" + " ".join(w["word"].strip() for w in ws[1000:1150]) + "\n")
EOF
git status --short
```
Ожидается: два или три одинаковых по словам отрывка, различаются только знаки и заглавные буквы.

## Шаг 6. Отчёт в ветку
Записать `handoff/m113/REPORT.md`:
1. Коммиты шагов 1 и 4, строки pytest; `token_scale.json` до (шаг 1) и после (шаг 2).
2. Таблица: вариант (novad / lpc / lpl) — концов на 100 слов, «совпало с Groq» %, точность %, кусков без ответа, время.
3. `sample.txt` целиком.
4. Одна строка вывода: насколько модель приблизила точки к Groq (облако и gamebox) и во сколько обошлась по времени.

```bash
cd /Users/danny/Documents/autoreels
bash handoff/bin/report.sh m113 run.txt sample.txt
```
Ожидается `отчёт m113 отправлен в ветку handoff`. Владельцу в чат — одна строка: концы на 100 слов было → стало (облако / gamebox), против 10.3 у Groq; «отчёт в ветке».

Статус: IMPLEMENTED, GATE PENDING.
