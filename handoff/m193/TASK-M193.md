# TASK M193 (окно MAIN, Mac): ролик не начинается с ответа на вопрос, которого зритель не слышал

Файлы — ветка `handoff`, папка `handoff/m193/`:
- `TASK-M193.md`;
- `m193-answer-start.patch` — код и тесты; патч написан и прогнан ассистентом;
- `drafts_diff.py` — замер.

Около 40 минут. Без рендера. LLM — только сценарист Sonnet с кэшем ответа (тот же запрос второй раз не оплачивается). Отчёт — только на русском.

## Зачем
Слепые судьи m192b (`handoff/m192b/judges_result.txt`) оценили 10 клипов эталона против 10 клипов m183. Самый слабый балл m183 — начало: 2,3–2,6 из 5 против 3,0–3,7 у эталона. Плохие начала m183 — ответы на вопрос, которого в ролике нет: «Да, у меня даже как получается…», «Знаете, когда ко мне приходит человек…» сразу после вопроса ведущего. Это ловится детерминированно.

Патч добавляет флаг `autocut.answer_start` (работает вместе с `start_strict`, по умолчанию **выключен** — выход прежний). С флагом ролик не открывается:
1. **словом-ответом**: «Да, …», «Нет.», «Конечно, …», «Согласен, …», «Ага, …»; «Наверное/Возможно» — только если это весь ответ («Наверное, да.»);
2. **ответом на реплику ведущего**: первая фраза начинается не позже `answer_gap_sec` (3 с) после фразы ведущего по карте говорящих, не вопрос, и в ней меньше двух общих содержательных слов с вопросом. «Как ты отдыхаешь? — …» и пересказ вопроса своими словами проходят.

Дальше — как у `start_strict` (M182):
- у сценариста начало сдвигается на 1–2 фразы раньше. Реплику ведущего при `interviewer: off` добавить нельзя, поэтому такой ролик уходит в «не принят» с причиной;
- у клипа разметки в `arl auto` проверяется только слово-ответ, такой клип убирается.

Где код:
- `cloud/autocut.py` — `answer_start_reason`, поля `AutoParams`;
- `cloud/scenario.py` — `scenario_proposals`, блок `start_strict`;
- `__main__.py` — проводка параметров и проверка клипов разметки;
- `core/config.py`, `config/r0.yaml` — `answer_start: false`, `answer_gap_sec: 3.0`.

Тесты — `tests/test_m193_answer_start.py` (5 тестов). Ассистент прогнал весь набор: 2598 прошли. Упали 9 тестов, которым нужны ffmpeg/praat, — их в его окружении нет, на Mac они проходят.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить. Расхождение чисел в замере — не СТОП.
2. Перед стартом не должно идти других `arl` и рендера: `pgrep -fl "autoreels|ffmpeg"`.
3. **НЕ МЕНЯТЬ** ничего, кроме того, что вносит патч. Флаг в `config/r0.yaml` **не включать**: включает владелец по итогам замера. Черновики пишутся только в `handoff/m193/` (`--out` обязателен, иначе перепишется `reviews/<stem>_auto_m56.txt`). Без `--apply`, без рендера.
4. Сценарист: `--llm sonnet`. Ответ модели берётся из кэша `data/cache/scenario/`. Если в выводе есть строка о цене прогона — выписать её в отчёт. Суммарная цена больше $1 → остановиться после текущего источника и написать в отчёт (не СТОП для уже сделанного).
5. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.
6. Итог — «IMPLEMENTED (флаг выключен), MEASURED». Гейт не объявлять.

## Часть 0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m193
```
Ожидается: ветка `main`, чисто (кроме `handoff/`), последний коммит — M191 (`7ce87c9`) или новее.

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git apply --check handoff/m193/m193-answer-start.patch && git apply handoff/m193/m193-answer-start.patch && echo applied
.venv/bin/python -m pytest tests/test_m193_answer_start.py -q 2>&1 | tail -2
.venv/bin/python -m pytest -q 2>&1 | tail -2
git add config/r0.yaml src/autoreels/__main__.py src/autoreels/cloud/autocut.py src/autoreels/cloud/scenario.py src/autoreels/core/config.py tests/test_m193_answer_start.py
git commit -m "Starts (M193): autocut.answer_start (off) — with start_strict a reel never opens on an answer word («Да, …») or on the reply right after the interviewer's sentence that does not repeat it; label clips of arl auto: the answer word"
git push; git log --oneline -1
```
Ожидается:
- `applied`;
- 5 passed;
- весь набор — прежнее число прошедших плюс 5, упавших нет;
- коммит запушен.

## Часть 2. Замер: сценарист без правила и с правилом (все 7 источников)
**Зачем:** узнать, сколько роликов правило убирает или сдвигает и какие начала заменяет. Без правила черновик должен повторить сценариста m183. С правилом — то же, но с другими началами.
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
for S in prew_isaev_anna prew_isaev_danny day_yoga_p1 day_yoga_p2 disko_beach_p1 disko_beach_p2 disko_beach_p3; do
  echo "=== $S off"
  arl autocut "manifests/${S}.json" --scenario --llm sonnet --out "handoff/m193/${S}_off.txt" 2>&1 | tail -4
  echo "=== $S on"
  arl autocut "manifests/${S}.json" --scenario --llm sonnet --ac answer_start=true --out "handoff/m193/${S}_on.txt" 2>&1 | tail -4
done 2>&1 | tee handoff/m193/run.txt
.venv/bin/python handoff/m193/drafts_diff.py 2>&1 | tee handoff/m193/diff.txt
git status -sb | head -5
```
Ожидается:
- по каждому источнику два черновика в `handoff/m193/`;
- `diff.txt`: строка на источник и ИТОГО. В источниках без интервью (`day_yoga_*`, `disko_beach_*`) разница только там, где ролик начинался с «Да, …», «Нет.», «Конечно, …»;
- `git status` чистый вне `handoff/`.

`--ac answer_start=true` отказан («нет такого поля») → **СТОП**: патч не применился или поле не проведено.

## Часть 3. Сверка с судьями
**Зачем:** проверить, что правило ловит именно те начала, которые судьи назвали плохими, и не трогает хорошие.
```bash
cd /Users/danny/Documents/autoreels
bash handoff/bin/take.sh m192b >/dev/null
.venv/bin/python - <<'EOF' 2>&1 | tee handoff/m193/judges_check.txt
import json, sys
sys.path.insert(0, "src")
from autoreels.cloud.autocut import answer_start_reason, strict_start_reason
texts = {x["id"]: x for x in json.load(open("handoff/m192b/blind_texts.json", encoding="utf-8"))}
j = {n: {e["id"]: e for e in json.load(open(f"handoff/m192b/judge{n}.json", encoding="utf-8"))} for n in (1, 2)}
for x, t in sorted(texts.items()):
    body = t["text"]
    if t["cold_open"] and body.startswith(t["cold_open"]):
        body = body[len(t["cold_open"]):].lstrip()
    first = body.split(". ")[0][:120]
    why = strict_start_reason(first) or answer_start_reason(first)
    print(f"{x} начало судей {j[1][x]['start']}/{j[2][x]['start']} | правило: {why or '—'} | «{first[:70]}»")
EOF
```
Ожидается: 20 строк. Только текстовая часть правила (слово-ответ и старые правила) — карты говорящих здесь нет.

## Отчёт
`handoff/m193/REPORT.md`:
```
M193 — IMPLEMENTED (флаг выключен), MEASURED
Коммит: <хэш>; pytest: N passed (было M), тесты M193: 5 passed
Замер (diff.txt, ИТОГО): строк M без правила A, с правилом B; заметок про ответ C
По источникам: <строка diff.txt на источник>
Ролики, которые правило убрало или сдвинуло (до 15): <источник | было «первая фраза» → стало «…» | или «не принят: причина»>
Цена сценариста: <строки цены из run.txt> | из кэша
Сверка с судьями (judges_check.txt): <сколько начал с баллом судей ≤ 2 правило ловит, сколько ловит с баллом ≥ 4>
Пропущено/не совпало: …
```
```bash
bash handoff/bin/report.sh m193 run.txt diff.txt judges_check.txt $(cd handoff/m193 && ls *_off.txt *_on.txt)
```
Владельцу в чат — 3 строки:
1. статус;
2. «с правилом: роликов A → B, сдвинуто начало у C»;
3. одна пара «было → стало» из интервью.
