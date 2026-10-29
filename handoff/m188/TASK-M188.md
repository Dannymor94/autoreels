# TASK M188 (окно MAIN, Mac): линейка качества гейта — `tools/score_gate.py`, только замер

Файл — ветка `handoff`, папка `handoff/m188/`: `TASK-M188.md` (патча нет, код пишешь ты, по TDD). Около 60 минут, без рендера, без LLM, без сети. Отчёт — только на русском.

## Зачем
Сейчас качество гейта видно только глазами владельца. Каждая веха меряла своё отдельным скриптом: крючки — m183, покрытие клипов владельца — m118/m144, короткие планы — `tools/measure_shots.py`. Нужен один отчёт по всем источникам гейта с одними и теми же числами. Тогда любую следующую правку сборки (веса формул по оценкам, морфология, проверка сюжета) можно доказать числом до просмотра.

Задача **ничего не меняет в сборке и рендере**. Добавляются:
- новый модуль `src/autoreels/cloud/gatescore.py` (чистые функции);
- его тесты;
- скрипт `tools/score_gate.py`;
- две строки документации.

## Правила
1. Любая команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить вне этой задачи. Расхождение чисел в замере — не СТОП, это результат.
2. Перед стартом не должно идти других `arl` и рендера (`pgrep -fl "autoreels|ffmpeg"`). Пока идёт рендер, pytest не запускать.
3. **НЕ МЕНЯТЬ:**
   - любые существующие файлы в `src/`, включая `__main__.py` (новую команду `arl` не добавлять: меню и диспетчер проверяются тестом);
   - `config/`, `prompts/`, `tools/measure_shots.py`, `tools/grid.py`, `tools/publish_dir.py`.
   Только читать: `manifests/`, `reviews/`, `transcripts/`, `reels-out/` (кроме `reels-out/_score/`).
4. Скрипт пишет только в `reels-out/_score/` (папка не в git). Тесты — только в `tmp_path` (autouse-гвард проваливает запись в корень).
5. Псевдонима `arl` в оболочке агента нет. Команды — `.venv/bin/python …`.
6. Итог — «IMPLEMENTED, MEASURED». Гейт не объявлять пройденным.

## Часть 0. Предусловия и замер входов (до кода)
**Зачем:** узнать, что реально лежит на диске, и ответить владельцу на вопрос, сколько у него оценок. От этого зависит следующая задача: веса формул по оценкам.
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m188
mkdir -p handoff/m188
{
echo "== гейты (review.json по гейтам)"; ls reviews/*.review.json | sed -E 's/.*_([^_]+)\.review\.json$/\1/' | sort | uniq -c
echo "== m183"; ls -1 reviews/*_m183.review.json
echo "== оценки"; wc -l reviews/verdicts.jsonl
.venv/bin/python - <<'EOF'
import json, collections
rows = [json.loads(l) for l in open("reviews/verdicts.jsonl", encoding="utf-8") if l.strip()]
print("по гейтам:", collections.Counter(r.get("gate") or "?" for r in rows).most_common())
print("по решениям:", collections.Counter(r.get("verdict") for r in rows).most_common())
print("по видам:", collections.Counter(r.get("kind") for r in rows).most_common())
print("причины:", collections.Counter(x for r in rows for x in r.get("reasons") or []).most_common())
print("источников:", len({r.get("stem") for r in rows}))
EOF
echo "== карты и интонация"; ls -1 transcripts/*.map.json transcripts/*.prosody.json
echo "== разметка владельца (manifests, selection_source=human)"
for f in manifests/*.json; do case "$f" in *.blocks.json|*.discarded.json) continue;; esac
  .venv/bin/python -c "import json,sys;m=json.load(open(sys.argv[1]));print(sys.argv[1],m.get('selection_source') or 'auto',len(m['reels']))" "$f"; done
} 2>&1 | tee handoff/m188/inputs.txt
```
Ожидается:
- рабочая копия чистая, на `main`, последний коммит — M187 (`11c5c28`) или новее;
- `reviews/*_m183.review.json` — 7 файлов (по одному на источник). **Меньше 7 — не СТОП:** считать по тем, что есть, и назвать недостающие в отчёте. **Ноль — СТОП;**
- `verdicts.jsonl` есть. Нет файла — не СТОП: пункт «оценки» в отчёте = 0.

## Часть 1. Модуль `src/autoreels/cloud/gatescore.py` (TDD)
**Зачем:** все числа считаются одной детерминированной функцией. Где можно, берутся те же правила, что у самой сборки, чтобы линейка и конвейер не расходились.

Сначала тесты `tests/test_gatescore.py` (синтетические словари reel/map/prosody, `tmp_path`), потом код. Функции чистые: на вход — словари из JSON, никаких путей и чтения файлов внутри, кроме одной `load_gate(root, gate)`.

Определения. Время клипа — выходное, то есть длительность окна, делённая на `reel["speed"]`. «Тело» — `segments` (пусто → одно окно `[start, end]`), без `cold_open`.

| Поле клипа | Как считается |
|---|---|
| `dur` | (длина `cold_open` + сумма длин окон тела) / `speed` |
| `hook` | есть `cold_open` и его длина > 0 |
| `seams` | границы соседних окон тела, у второго окна `window_cut == False` (стык кусков) |
| `cuts` | то же, но `window_cut == True` (вырезанная пауза или паразит) |
| `back_jumps` | стыки, где следующее окно начинается раньше начала предыдущего (перестановка) |
| `first_text` | слова `subtitles` с `t0` внутри первого окна тела, по порядку, до первого слова на `.?!…` включительно (нет такого — все слова окна) |
| `start_backref` | `autoreels.cloud.autocut.back_reference(first_text)` — строка причины или `None`. Импортировать, не копировать |
| `start_short` | `first_text` не вопрос и в нём меньше слов, чем `autocut.context_min_words` из конфига |
| `end_tone` | последнее слово тела: слово `subtitles` с наибольшим `t0` внутри последнего окна тела. В `prosody["words"]` ищется запись с ближайшим `t0` (не дальше 0,1 с), дальше `autoreels.local.prosody.classify(entry)` → `final` / `open` / `unsure` / `none` (нет записи или нет данных) |
| `short_shots`, `slivers` | планы между сменами картинки — та же логика, что `shots()` в `tools/measure_shots.py` (скопировать функцию в модуль; скрипт не трогать). `short` < `short_shot_sec` конфига, `sliver` < 0,2 с; крючок и последний план не считаются |
| `warnings` | `reel["warnings"]` по видам: вид = текст до первого «:», «(» или «—», обрезанный до 40 знаков |
| `units` | мысли карты (`map["units"]`, поля `t0`/`t1`/`role`/`punch`/`topic`), которые окна тела покрывают не меньше чем на 50 % длины мысли, в порядке проигрывания (по первому окну, которое её покрывает) |
| `open_role` | среди первых двух мыслей есть роль `question` или `thesis` |
| `close_role` | среди последних двух мыслей есть роль `conclusion` |
| `closure` | число общих основ (слово ≥ 5 букв → первые 5 букв, как `_stems` в `cloud/postcopy.py`; импортировать) у текста первой и последней мысли; мысль одна — `None` |
| `topics` | число разных `topic` среди мыслей (1 — клип в одной теме) |
| `punch_mean` | средняя сила мыслей (`None`, если нет ни одной) |

Сводка по источнику и по гейту (`summarize(clips)`):
- клипов, длительность (медиана / мин / макс);
- доли (%): `hook`, `start_backref`, `start_short`, `end_tone=open`, `end_tone=none`, `open_role`, `close_role`, `topics==1`, `closure ≥ 1`;
- на минуту: `seams`, `cuts`; всего: `back_jumps`, `short_shots`, `slivers`;
- топ-5 видов предупреждений.

Покрытие клипов владельца (`coverage(owner_reels, gate_reels)`). Клип владельца — reel ручного манифеста `manifests/<stem>.json` (`selection_source == "human"`). Он «найден», если у какого-то клипа гейта окна тела перекрываются с его окнами тела не меньше чем на 50 % длины более короткого из двух. Каждый клип гейта засчитывается не больше одного раза, жадно по убыванию перекрытия. Нет ручного манифеста с тем же именем — `None`, в таблице «нет разметки».

> Это касается `prew_isaev_danny`: разметка владельца лежит на другом файле, `PXL_20260729_085910095_34f06abf` (другой sha). Не сопоставлять.

Оценки (`verdicts(rows, gate)`): строки `verdicts.jsonl` с `gate == <гейт>` — счёт по `verdict` и по причинам; плюс всего строк в файле.

Тесты — минимум по одному на каждое правило таблицы. Обязательные:
1. `dur` с крючком и `speed: 1.1`.
2. `seams` и `cuts` различаются по `window_cut`; перестановка даёт `back_jumps = 1`.
3. `first_text` останавливается на первой точке; «И это так важно.» → `start_backref` не `None`; «Что такое страх?» → `None`.
4. `end_tone`: `end_pct` 10 → `final`, 80 → `open`, записи нет → `none`.
5. Покрытие: перекрытие 60 % → найден, 40 % → нет; один клип гейта не засчитывается двум клипам владельца.
6. `units`: мысль, покрытая на 40 %, не входит; порядок — по проигрыванию при перестановке.
7. `closure`: «страхи мешают жить» … «без страха жить легче» → ≥ 1.
8. `short_shots`/`slivers` на клипе с `close_intervals` совпадают с подсчётом по правилам `measure_shots`.

```bash
.venv/bin/python -m pytest tests/test_gatescore.py -q 2>&1 | tail -3     # сначала падает (модуля нет), потом зелёный
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src/autoreels/cloud/gatescore.py tests/test_gatescore.py
git commit -m "Gate yardstick (M188): cloud/gatescore — per-clip and per-source metrics of a gate (hooks, starts, end tone, seams, shots, story roles, owner coverage, verdicts); measurement only"
```
Ожидается: новые тесты зелёные; весь pytest — столько же прошедших, сколько до части 1, плюс новые; коммит.

## Часть 2. Скрипт `tools/score_gate.py`
**Зачем:** один запуск — одна таблица. Сравнение двух гейтов — одна строка разницы.

`.venv/bin/python tools/score_gate.py <гейт> [--compare <гейт2>] [--stems a,b]`:
1. Читает:
   - `reviews/<stem>_<гейт>.review.json` (все, что есть);
   - `manifests/<stem>.json` (ручной);
   - `transcripts/<stem>.map.json`, `transcripts/<stem>.prosody.json` (чего нет — те поля `None`, в таблице «—», не падать);
   - `config/r0.yaml` через `autoreels.core.config.load_r0_config`;
   - `reviews/verdicts.jsonl`.
2. Печатает таблицу: строка на источник + `ИТОГО`. Колонки:

   `клипов | дл. мед | крючок% | ссылка назад% | обрывок% | конец →% | без тона% | стыков/мин | вырезов/мин | скачков назад | коротких планов | вспышек | открытие% | вывод% | одна тема% | замыкание% | покрытие владельца`

   Под таблицей:
   - топ-5 предупреждений;
   - оценки гейта;
   - 5 клипов с наибольшим числом проблем (`start_backref`, `start_short`, `end_tone=open`, нет `close_role`, `topics>1`, короткие планы) — `источник rNN: причины`.
3. Пишет `reels-out/_score/<гейт>.json` (сводки и все поля по каждому клипу).
4. `--compare` читает оба JSON (нет второго — сначала считает его) и печатает ИТОГО обоих гейтов и разницу по каждой колонке.

```bash
.venv/bin/python tools/score_gate.py m183 2>&1 | tee handoff/m188/score_m183.txt
```
Ожидается:
- 7 строк источников (или столько, сколько review.json в части 0) и ИТОГО;
- клипов в ИТОГО = 69;
- крючок в ИТОГО = 32 из 69 (≈ 46 %): это число m183. **Если не 32 — не СТОП**, но разобрать 2–3 расходящихся клипа и написать причину в отчёте;
- вспышек 0 (как у `measure_shots` в m187);
- файл `reels-out/_score/m183.json` есть.

## Часть 3. Базовая линия: старый гейт
**Зачем:** без второй точки нельзя понять, работает ли линейка на сравнении.

Из списка гейтов части 0 взять самый свежий гейт до m183, у которого есть review.json хотя бы по 5 источникам (кандидаты — m176, m175; старые клипы в Корзине не нужны, читается только review.json).
```bash
.venv/bin/python tools/score_gate.py m183 --compare <старый гейт> 2>&1 | tee handoff/m188/compare.txt
```
Ожидается: обе строки ИТОГО и разница. Владелец о m176 сказал «начало пустое», «хуки пустые» (замер m183: крючок 14 из 80 → 32 из 69) — у m183 крючок% должен быть выше. Если нет — не СТОП, написать.

Нет ни одного подходящего гейта — часть пропустить, так и написать.

## Часть 4. Документация, push
- `PROJECT_STRUCTURE.md`: строка про `cloud/gatescore.py` и `tools/score_gate.py`.
- `PLAN.md`, таблица блока «Автомонтаж»: строка «Линейка гейта | `tools/score_gate.py <гейт> [--compare]` — числа гейта по источникам (крючки, начала, тон конца, стыки, планы, роли мыслей, покрытие клипов владельца, оценки); только замер | M188». Значения порогов не писать: только ссылку на конфиг.
```bash
.venv/bin/python -m pytest -q 2>&1 | tail -2
git add PROJECT_STRUCTURE.md PLAN.md tools/score_gate.py
git commit -m "Gate yardstick (M188): tools/score_gate.py — one table per gate, --compare; docs"
git push; git log --oneline -3; git status -sb | head -3
git diff --stat HEAD~2 -- src config prompts | tail -1     # только новый файл src/autoreels/cloud/gatescore.py
```
Ожидается:
- pytest зелёный;
- два коммита запушены;
- `git diff --stat` по `src config prompts` показывает только `gatescore.py` (выход рендера не может измениться).

## Отчёт
`handoff/m188/REPORT.md` — строго по шаблону:
```
M188 — IMPLEMENTED, MEASURED (гейт не объявляется)
Коммиты: <хэш> <хэш>; pytest: N passed (было M)
Часть 0: review.json m183 — N из 7 (нет: …); оценок в verdicts.jsonl — N строк, по гейтам: …; по решениям: …; причины: …
Часть 1: тесты (имена): …
Часть 2: ИТОГО m183 — <строка таблицы целиком>; крючок 32/69 совпал? да/нет (почему)
Худшие 5 клипов: …
Часть 3: сравнение с <гейт>: <две строки ИТОГО + разница> | пропущено: причина
Пропущено/не совпало: …
```
```bash
bash handoff/bin/report.sh m188 inputs.txt score_m183.txt compare.txt
```
Владельцу в чат — 3 строки: статус; ИТОГО m183 одной строкой; сколько строк в `verdicts.jsonl`.
