# TASK M111 (окно MAIN, Mac + gamebox): почему у whisper.cpp на gamebox мало точек — замер вариантов

Файлы — в ветке `handoff`, папка `handoff/m111/`: `TASK-M111.md`, `m111-tx-variants.patch`.

**Ставится поверх M109** (8363892). Одна сессия, без фоновых задач. Прогоны идут по очереди, всего около часа.

## Зачем
У whisper.cpp на gamebox концов предложений ~8.9 на 100 слов, у Groq — 13.1. Без точек предложения получаются длинными, и клипу не на чем закончиться. Подсказки-промпты не помогли (M64b). Не проверены три другие причины:
- **Модель.** На gamebox стоит large-v3-turbo: у неё 4 слоя декодера вместо 32, а пунктуацию ставит именно декодер. Groq работает на полной large-v3.
- **Отсев тишины (VAD).** whisper.cpp вырезает паузы до распознавания, и модель не слышит пауз, на которых кончаются предложения.
- **Контекст (`-mc 0`).** Каждое окно в 30 с распознаётся без предыдущего текста. Groq контекст использует.

Патч добавляет в `arl tx-compare` параметр `--wc ключ=значение`: вариант whisper.cpp без правки конфига. Ещё одна новая строка в выводе показывает, сколько концов предложений Groq есть и у gamebox на тех же словах. Прогоняем на IMG_6848 пять вариантов.

## Правила
1. Любой шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить. Расхождение чисел между вариантами — не СТОП, это замер.
2. Перед стартом на Mac не должно идти других `arl` и рендера. pytest — только в шаге 1, до прогонов.
3. gamebox: озвучку не трогать. Если замок занят, `arl` ждёт сам (строка «gamebox занят … жду»). sudo не нужен.
4. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.
5. `transcripts/IMG_6848.local.transcript.json` не перезаписывать: все варианты идут с `--tag`.
6. В `git status` допустимы прежние строки: ` M data/blocks_dataset/IMG_6848.jsonl`, ` M data/token_scale.json`, `?? manifests/_archive/`, `??` из `transcripts/` и `*.discarded.json`.
7. Итог — «MEASURED».

## Шаг 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -1; git log --oneline -1; pgrep -fl "arl " || echo "arl не запущен"
git apply --check handoff/m111/m111-tx-variants.patch && git apply handoff/m111/m111-tx-variants.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src/autoreels/__main__.py src/autoreels/cloud/txcheck.py tests/test_whispercpp.py
git commit -m "Transcription (M111): tx-compare --wc whisper.cpp variants without editing the config; sentence-end agreement with Groq on matched words"
git push; git log --oneline -1
```
Ожидается:
- последний коммит до патча — M109 (8363892); `arl не запущен`; `applied`;
- pytest: все прошли (если что-то упало — **СТОП**, не коммитить);
- новый коммит запушен.

## Шаг 2. Модель large-v3 на gamebox
```bash
ssh gamebox 'source ~/llama.env; echo "W=$W"; ls -la "$W"/*.bin; df -h "$W" | tail -1'
```
Ожидается: каталог `$W`, файлы моделей, свободное место.
- **СТОП**, если `$W` на системном SSD (в последней колонке `df` стоит `/`): модели должны лежать на HDD.
- Если `ggml-large-v3.bin` уже есть — шаг 3 пропустить.

## Шаг 3. Скачать large-v3 (только если её нет)
Нужно ≥ 8 ГБ свободного места на `$W`, иначе **СТОП**. Файл ~3.1 ГБ.
```bash
ssh gamebox 'source ~/llama.env; cd "$W" && curl -fL --retry 3 -o ggml-large-v3.bin.part https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin && mv ggml-large-v3.bin.part ggml-large-v3.bin && ls -la ggml-large-v3.bin'
```
Ожидается: `ggml-large-v3.bin` размером около 3 095 000 000 байт.

## Шаг 4. Пять вариантов на IMG_6848
Сначала быстрые (turbo), потом медленные (large-v3). Каждый вариант берёт замок gamebox и отпускает его.
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; mkdir -p handoff/m111
{
echo "== base: как сейчас (turbo, VAD, -mc 0)"; arl tx-compare IMG_6848 --tag m111-base
echo "== novad: без отсева тишины";             arl tx-compare IMG_6848 --tag m111-novad --wc vad_model=
echo "== ctx: с контекстом (-mc -1)";            arl tx-compare IMG_6848 --tag m111-ctx --wc max_context=-1
echo "== v3: полная large-v3";                   arl tx-compare IMG_6848 --tag m111-v3 --wc 'model=$W/ggml-large-v3.bin'
echo "== v3novad: large-v3 без отсева тишины";   arl tx-compare IMG_6848 --tag m111-v3novad --wc 'model=$W/ggml-large-v3.bin' --wc vad_model=
} 2>&1 | tee handoff/m111/run.txt
```
Ожидается: пять блоков `== IMG_6848 (локально: N с)`. В каждом есть строки «конец предложения на 100 слов» и «концы Groq на совпавших словах». Если один вариант упал, остальные идут дальше: это не СТОП, ошибка попадёт в отчёт.

## Шаг 5. Таблица
```bash
cd /Users/danny/Documents/autoreels
cp transcripts/IMG_6848.txcompare-m111-*.json handoff/m111/
.venv/bin/python - <<'EOF' | tee handoff/m111/table.txt
import json, glob
print("вариант   концов/100  совп.с Groq  точность  слов   расхожд.  выдумки  повторы")
for f in sorted(glob.glob("transcripts/IMG_6848.txcompare-m111-*.json")):
    r = json.load(open(f)); c = r["compare"]; sa = c["sent_agree"]; l = r["local"]
    name = f.split("m111-")[1][:-5]
    print(f"{name:9} {c['other_sent_ends']:>8}   {sa['recall']:>9}%  {sa['precision']:>7}%  {c['other_words']:>5}  {c['differ']:>7}%  {l['serious']:>7}  {l['repeat']:>7}")
print(f"Groq: {c['ref_sent_ends']} концов на 100 слов, {c['ref_words']} слов")
EOF
git status --short
```
Ожидается: строка на каждый вариант и строка Groq.

## Шаг 6. Отчёт в ветку
Записать `handoff/m111/REPORT.md`:
1. Шаг 1 — хэш коммита и строка pytest.
2. Шаг 2–3 — `W=…`, последняя строка `df`, скачивалась ли модель.
3. `table.txt` целиком и время каждого варианта (из `run.txt`, «локально: N с»).
4. Одна строка вывода: какой вариант ближе всего к Groq по концам/100 и «совп. с Groq», и во сколько раз он медленнее base. Если ни один не дал больше 11 концов на 100 слов, так и написать: «флаги whisper.cpp точек не возвращают».

```bash
cd /Users/danny/Documents/autoreels
bash handoff/bin/report.sh m111 run.txt table.txt $(cd handoff/m111 && ls IMG_6848.txcompare-m111-*.json)
```
Ожидается `отчёт m111 отправлен в ветку handoff`. Владельцу в чат — одна строка: лучший вариант, его концы на 100 слов против 13.1 у Groq, «отчёт в ветке».

Статус: MEASURED.
