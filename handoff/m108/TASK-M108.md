# TASK M108–M109 (окно MAIN, Mac + gamebox): общий замок тяжёлых задач gamebox и расшифровка диктофона

Файлы в `handoff/m108/`: `TASK-M108.md`, `m108-gamebox-lock-dictate.patch`.

**Ставится поверх M107** (a529e1f). Одна сессия. Фоновая команда — только та, что прямо написана в шаге 2.

## Зачем
- **M108 — общий замок.** На gamebox владелец запускает озвучку книги. Она и llama-server вместе не помещаются в память. Обе стороны берут один замок: `flock /mnt/data/locks/heavy.lock`. Кто пришёл вторым, ждёт и не обрывает чужую работу. autoreels берёт замок, когда нужна локальная модель или whisper.cpp на gamebox. Если llama-server выключен, autoreels запускает его сам, а в конце гасит — только если запускал сам. Со стороны озвучки замок берёт её собственная обёртка (её пишут в другом чате). Новая команда `arl gamebox` показывает статус: занят ли замок, работает ли модель, сколько свободно памяти. Ожидание «gamebox занят — жду» в задачах больше не нужно: его делает сам замок.
- **M109 — `arl dictate`.** Аудио с диктофона превращается в текст. Без файла команда спросит путь; файл можно перетащить в терминал. Команда проверяет, что gamebox отвечает, берёт замок и расшифровывает через whisper.cpp. Текст кладёт рядом с аудио (`<имя>.txt`) и копирует в буфер обмена. Если gamebox не отвечает — предлагает Groq.

## Правила
1. Любой шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить.
2. Перед стартом на Mac не должно идти других `arl`, фоновых оболочек и мониторов. pytest — только в шаге 1.
3. На gamebox: из sudo — только `sudo -n systemctl start|stop llama-server`, пароль не вводить. **Озвучку не трогать и не останавливать.** Если замок занят озвучкой — ждать.
4. Псевдонима `arl` в оболочке агента нет: первая строка блоков шагов 2–3 определяет функцию `arl`. Блок запускать целиком.
5. В `git status` допустимы три строки (` M data/blocks_dataset/IMG_6848.jsonl`, ` M data/token_scale.json`, `?? manifests/_archive/`), прежние `??` из `transcripts/` и `*.discarded.json`.
6. Итог — «IMPLEMENTED, GATE PENDING».

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -1; git log --oneline -1; pgrep -fl "arl " || echo "arl не запущен"
.venv/bin/python -m pytest --collect-only -q 2>/dev/null | tail -1
git apply --check handoff/m108/m108-gamebox-lock-dictate.patch && git apply handoff/m108/m108-gamebox-lock-dictate.patch && echo applied
.venv/bin/python -m pytest tests/test_heavy_lock.py tests/test_providers.py tests/test_cli.py -q 2>&1 | tail -2
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add CLAUDE.md config/r0.yaml docs/GAMEBOX.md src/autoreels/__main__.py src/autoreels/cloud/providers.py src/autoreels/cloud/transcribe.py src/autoreels/core/config.py src/autoreels/core/heavy_lock.py tests/test_heavy_lock.py
git commit -m "gamebox (M108/M109): one flock lock for every heavy job there (the audiobook, llama-server use, whisper.cpp) — the second comer waits; llama-server started when down, stopped when we started it; arl gamebox; arl dictate — a voice recording to text on gamebox"
git push; git status --short
```
Ожидается:
- последний коммит — M107 (a529e1f); `arl не запущен`;
- `N0` = 2401, `applied`;
- `0 failed`, всего 2410.

## Шаг 2. Замок вживую (без модели)
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m108
{
arl gamebox
arl gamebox take
ssh gamebox 'flock /mnt/data/locks/heavy.lock sleep 25' & HOLDER=$!
sleep 3
arl gamebox
arl gamebox take
wait $HOLDER
arl gamebox
} 2>&1 | tee handoff/m108/lock.txt
```
Ожидается:
- первая строка `gamebox: замок свободен; llama-server: …; свободно памяти: N ГБ`;
- `замок gamebox:/mnt/data/locks/heavy.lock работает (взят и отпущен за 0–2 с)`;
- пока держит `sleep 25`: статус `замок ЗАНЯТ`, затем `gamebox занят (общий замок …) — жду…`, `gamebox: замок взят (ждал ~22 с)` и `работает (… за ~22 с)`;
- последний статус — `замок свободен`.

Если замок не берётся (`mkdir`/`flock` на gamebox — нет прав на `/mnt/data/locks` или нет `flock`) — **СТОП** с текстом ошибки: путь выберет владелец.

## Шаг 3. Диктофон: минута звука из кэша через gamebox
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
A=$(ls -S data/cache/*.mp3 2>/dev/null | head -1); echo "исходник: ${A:-нет mp3 в data/cache}"
if [ -n "$A" ]; then
  ffmpeg -v error -y -ss 60 -t 60 -i "$A" /tmp/dictate_test.m4a
  arl dictate /tmp/dictate_test.m4a --no-copy 2>&1 | tee handoff/m108/dictate.txt
  head -c 500 /tmp/dictate_test.txt; echo
  arl gamebox
fi
git status --short
```
Ожидается:
- `=== dictate: dictate_test.m4a → whisper.cpp на gamebox ===`, `gamebox: замок взят`, `готово: N слов, ~1 мин → /tmp/dictate_test.txt`, `gamebox: замок отпущен`;
- текст — связный русский с точками;
- в конце `замок свободен`.

Если mp3 в `data/cache` нет — шаг пропустить и написать об этом (не СТОП).

## Отчёт владельцу
1. Шаг 1 — `N0`, итог тестов, хэш.
2. Шаг 2 — `handoff/m108/lock.txt` целиком.
3. Шаг 3 — `handoff/m108/dictate.txt` и первые строки текста.

Статус: IMPLEMENTED, GATE PENDING.
