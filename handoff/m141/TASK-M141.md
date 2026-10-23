# TASK M141 (параллельный агент, Mac): кто когда говорит — замер разделения говорящих (pyannote)

Файлы — ветка `handoff`, папка `handoff/m141/`: `TASK-M141.md`, `diar.py`, `diar_stats.py`.
**Только замер:** код, конфиг, `reviews/`, `manifests/` не меняются, коммитов нет. Пишется только `data/cache/m141/` (в .gitignore) и `handoff/m141/`. MAIN не мешает, но расчёт тяжёлый — не запускать, пока MAIN гоняет pytest.

## Зачем
Открытый дефект: вопросы ведущего без паузы не отличаются от речи гостя (PLAN, «Открытые дефекты»). Если модель разделения говорящих надёжно делит голоса на этих записях, автомонтаж получает структуру «вопрос ведущего → ответ гостя», а клип перестаёт захватывать чужой голос. Сначала замер: сколько говорящих, есть ли чужой голос внутри клипов владельца, сколько вопросов задано другим голосом и сколько из них ловит нынешнее правило «пауза + вы/ты».

## Нужно от владельца (один раз)
На huggingface.co принять условия моделей `pyannote/speaker-diarization-3.1` и `pyannote/segmentation-3.0`, создать токен (read) и дописать в `.env` строку `HF_TOKEN=…`. Без этого шаг 2 остановится со СТОП и подсказкой. Токен в отчёт и чат не выводить.

## Шаг 1. Окружение
```bash
cd /Users/danny/Documents/autoreels
bash handoff/bin/take.sh m141
python3.13 -m venv ~/.venvs/m141 && ~/.venvs/m141/bin/pip install -q pyannote.audio
~/.venvs/m141/bin/python -c "import pyannote.audio, torch; print(pyannote.audio.__version__, torch.__version__)"
grep -c '^HF_TOKEN=' .env || echo "HF_TOKEN нет — СТОП, нужен владелец"
```
Ожидается: версии напечатаны; `1` (строка токена есть).

## Шаг 2. Разделение голосов
```bash
~/.venvs/m141/bin/python handoff/m141/diar.py 2>&1 | grep -v Warning | tee handoff/m141/diar.txt
ls data/cache/m141/
```
Ожидается: «pyannote на mps» (или cpu); по источнику строка «N реплик, говорящих K, T с»; в `data/cache/m141/` только `.diar.json`, без `.wav`. Долго (порядка 5–15 минут на час записи) — можно ограничить источниками с интервью: `… diar.py IMG_6848 "Pxl 20260621 112938952"`. Если упало на совместимости версий (pyannote / torch / python 3.13) — один раз попробовать `python3.12` вместо `python3.13` в шаге 1; не вышло — СТОП с текстом ошибки.

## Шаг 3. Что это значит для клипов и вопросов
```bash
.venv/bin/python handoff/m141/diar_stats.py 2>&1 | tee handoff/m141/stats.txt | tail -40
git status --short | grep -v "^??" | head
```
Ожидается: по источнику доли говорящих, строка про клипы владельца, «вопросов другим голосом N; правило … поймало бы M», до 8 примеров; итог `=== ВСЕГО`. `git status` без изменений.

## Шаг 4. Отчёт
`handoff/m141/REPORT.md`: `diar.txt`, `stats.txt` целиком, время шага 2.
`TMPDIR=$(mktemp -d) bash handoff/bin/report.sh m141 diar.txt stats.txt`
Владельцу — одна строка: «замер говорящих готов» (или «нужен HF_TOKEN»).
