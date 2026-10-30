# TASK M191 (окно MAIN, Mac): эталонная разметка ассистента → применить без установки → линейка «эталон против m183»

Файлы — ветка `handoff`, папка `handoff/m191/`:
- `TASK-M191.md`;
- семь файлов эталонной разметки `<stem>_ref191.txt`: `prew_isaev_anna`, `prew_isaev_danny`, `day_yoga_p1`, `day_yoga_p2`, `disko_beach_p1`, `disko_beach_p2`, `disko_beach_p3`.

Около 60 минут. Без рендера, без LLM, без сети (кроме push). Отчёт — только на русском.

## Зачем
Владелец, 2026-10-30: «ручную разметку будешь делать ты». Ассистент разметил все 7 источников по выгрузке m190 — 64 клипа, только строки сборки `M`. Разметка делалась независимо от m183, без карты мыслей и черновиков автоматики.

Нужно:
1. проверить и применить эту разметку **без установки** — получить `reviews/<stem>_ref191.review.json`, как у гейта;
2. посчитать линейкой M188 тот же отчёт по эталону и сравнить с m183;
3. добавить в линейку покрытие эталона: какие клипы эталона автоматика m183 нашла, какие потеряла. По каждому потерянному — роли мыслей карты: что в нём есть такого, чего автоматика не строит.

Сама сборка и рендер не меняются. Код меняется только в `cloud/gatescore.py` и `tools/score_gate.py` — оба из M188, только для замера.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить вне этой задачи. Исключение — часть 1, правило 1а. Расхождение чисел в замере — не СТОП, это результат.
   - **1а.** `--apply` отказал из-за конкретной строки `M` (в ошибке названа метка `M<n>` или номер строки файла). Тогда в рабочей копии `handoff/m191/work/<stem>_ref191.txt` эту строку закомментировать: `#! <прежняя строка>  ← apply: <причина одной строкой>`. Затем повторить, не больше трёх раз на источник. Строку не исправлять. Каждую закомментированную строку записать в отчёт.
   - Ошибку нельзя привязать к строке, или после трёх попыток всё ещё отказ — этот источник пропустить с последними 40 строками лога, остальные делать дальше. Это не общий СТОП.
2. Перед стартом не должно идти других `arl` и рендера: `pgrep -fl "autoreels|ffmpeg"`. Пока идёт рендер, pytest не запускать.
3. **НЕ МЕНЯТЬ:**
   - `config/`, `prompts/`;
   - любые файлы `src/`, кроме `src/autoreels/cloud/gatescore.py`;
   - `tools/`, кроме `tools/score_gate.py`;
   - `manifests/`, `transcripts/`;
   - чужие файлы в `reviews/`.

   **Не ставить** (`--install` и `--render` запрещены). Файлы `handoff/m191/<stem>_ref191.txt` (оригиналы ассистента) не править: работать только с копиями в `handoff/m191/work/`.
4. `arl blocks --apply` без `--install` пишет `reviews/<stem>.review.json` (и, возможно, файлы-спутники рядом). Этот путь может быть занят прежним файлом — его надо сохранить и вернуть (часть 1, шаги 1 и 3).
5. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.
6. Итог — «IMPLEMENTED, MEASURED». Гейт не объявлять.

## Часть 0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m191
ls -1 handoff/m191/*_ref191.txt | wc -l
grep -c '^M' handoff/m191/*_ref191.txt
ls -1 reels-out/_score/m183.json reviews/*_m183.review.json | wc -l
grep -nE '^(manual_plan|  enabled)' config/r0.yaml | head -3; grep -n -A1 '^montage:' config/r0.yaml
```
Ожидается:
- рабочая копия чистая (кроме `handoff/`), ветка `main`, последний коммит — M188 (`141fdfa`) или новее;
- 7 файлов `_ref191.txt`, строк `M`: 3, 16, 8, 6, 10, 8, 13 (всего 64; порядок файлов алфавитный);
- `m183.json` и 7 файлов `_m183.review.json` есть (8 строк);
- `manual_plan: true` и `montage: enabled: true` (без них строки `M` игнорируются — **СТОП**).

## Часть 1. Применить эталон без установки
**Зачем:** получить сыгранные окна каждого клипа эталона по тем же правилам плана, что у ручной разметки. Тогда линейка считает эталон и m183 одной функцией.

### Шаг 1. Снимок и сохранение
```bash
cd /Users/danny/Documents/autoreels
mkdir -p handoff/m191/work handoff/m191/bak
cp handoff/m191/*_ref191.txt handoff/m191/work/
touch handoff/m191/.t0; sleep 1
for S in prew_isaev_anna prew_isaev_danny day_yoga_p1 day_yoga_p2 disko_beach_p1 disko_beach_p2 disko_beach_p3; do
  for f in reviews/"$S".review*; do [ -e "$f" ] && cp -p "$f" handoff/m191/bak/ && echo "сохранён $f"; done
done
ls -la handoff/m191/bak/
```

### Шаг 2. Применить (по источнику)
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
for S in prew_isaev_anna prew_isaev_danny day_yoga_p1 day_yoga_p2 disko_beach_p1 disko_beach_p2 disko_beach_p3; do
  echo "== $S"
  arl blocks --apply "handoff/m191/work/${S}_ref191.txt" > "handoff/m191/apply_${S}.txt" 2>&1; echo "код $?"
  grep -E '^manifest →|\[ERROR\]' "handoff/m191/apply_${S}.txt" | head -12
  if [ -f "reviews/${S}.review.json" ]; then
    mv "reviews/${S}.review.json" "reviews/${S}_ref191.review.json"
    find reviews -maxdepth 1 -name "$S.review.*" -newer handoff/m191/.t0 -type f | while read -r f; do mv "$f" "${f/.review./_ref191.review.}"; done
  fi
done 2>&1 | tee handoff/m191/apply_all.txt
```
Ожидается для каждого источника:
- `код 0`;
- строка `manifest → reviews/<stem>.review.json (N reels, selection_source=human)`, где N равно числу строк `M` в файле (минус закомментированные по правилу 1а).

Код не 0 → правило 1а (повторить блок только для этого `S`). Предупреждения (`weak start`, `↗`, `short shot`, `no room after last word` и т. п.) — не ошибки, их не трогать: они идут в часть 3 отчёта.

### Шаг 3. Вернуть прежние файлы и проверить, что лишнего нет
```bash
cd /Users/danny/Documents/autoreels
for f in handoff/m191/bak/*; do [ -e "$f" ] && cp -p "$f" reviews/ && echo "возвращён $(basename "$f")"; done
echo "== изменено после .t0 (ожидаются только *_ref191.review*):"
find reviews manifests transcripts calibrations -newer handoff/m191/.t0 -type f | sort
git status -sb | head -10
ls -1 reviews/*_ref191.review.json | wc -l
```
Ожидается:
- в списке «изменено» только `reviews/<stem>_ref191.review*` (и, может быть, вернувшиеся из `bak/` файлы: `cp -p` сохраняет время, поэтому их там быть не должно);
- `git status` чистый вне `handoff/`;
- 7 файлов `_ref191.review.json` (меньше — только если источник пропущен по правилу 1а; назвать его).

Изменилось что-то ещё → вернуть из `bak/` или `git checkout --`, написать в отчёт, что и почему. Это не СТОП.

### Шаг 4. Сводка предупреждений эталона
```bash
cd /Users/danny/Documents/autoreels
for S in prew_isaev_anna prew_isaev_danny day_yoga_p1 day_yoga_p2 disko_beach_p1 disko_beach_p2 disko_beach_p3; do
  printf "%-18s " "$S"
  grep -oE '\[(WARNING|ERROR)\][^0-9«(]{0,40}|weak start|short shot|no room after last word|↗' "handoff/m191/apply_${S}.txt" | sed 's/ *$//' | sort | uniq -c | sort -rn | head -6 | tr '\n' ';'; echo
done | tee handoff/m191/warn.txt
```

## Часть 2. Линейка: покрытие эталона (TDD)
**Зачем:** M188 считает только «нашла ли автоматика клипы владельца». Нужен тот же ответ для эталона, и главное — список потерянных клипов.

### 2.1 `src/autoreels/cloud/gatescore.py`, функция `coverage`
Сейчас она возвращает `{"found", "total"}`. Добавить, не меняя этих двух ключей и правила сопоставления (≥ 50 % более короткого, жадно, каждый клип гейта не больше одного раза):
- `"matched"`: список `[owner_idx, gate_idx, frac]` найденных пар;
- `"missed"`: список индексов `owner_reels`, которые не найдены;
- `"best"`: для **каждого** `owner_idx` — `[gate_idx, frac]` клипа гейта с наибольшим перекрытием, даже ниже 50 % (`[None, 0.0]`, если перекрытия нет).

Тесты в `tests/test_gatescore.py`: сначала тест (падает), потом код:
1. `test_coverage_reports_missed_and_best`: два клипа владельца, один найден на 60 %, второй перекрыт на 30 % → `missed == [1]`, `best[1] == [gi, 0.3]` (с допуском), `matched` — одна пара.
2. `test_coverage_best_none_without_overlap`: перекрытия нет → `best[0] == [None, 0.0]`.
3. Старые тесты покрытия не меняются и проходят.

```bash
.venv/bin/python -m pytest tests/test_gatescore.py -q 2>&1 | tail -3
```

### 2.2 `tools/score_gate.py`, флаг `--ref <гейт>`
`score_gate.py <гейт> --ref <эталон>` дополнительно:
1. Для каждого источника: клипы эталона — `reviews/<stem>_<эталон>.review.json`, клипы гейта — `reviews/<stem>_<гейт>.review.json`; `coverage(ref_reels, gate_reels)`.
2. Печатает таблицу «эталон <эталон> в <гейт>»: строка на источник и ИТОГО (найдено / всего).
3. Затем список потерянных клипов эталона, по одному в строке:
   ```
   <stem> <rid эталона> «<title_overlay>» <дл. с> | лучшее: <rid гейта> <NN>% | роли: <роли мыслей по порядку> | <проблемы>
   ```
   - роли — поле `units` из `score_clip` для этого клипа эталона: роли через «→», сила в скобках, например `question(4)→thesis(3)→conclusion(5)`;
   - проблемы — те же метки, что у «худших 5 клипов» M188 (`_explain`).
4. Пишет в `reels-out/_score/<гейт>.json` ключ `"ref": {"gate": <эталон>, "per_stem": {...}, "total": {...}, "missed": [...]}` (остальное не меняется).
5. Часть `ref` считается заново при каждом запуске с `--ref`, даже если `reels-out/_score/<гейт>.json` уже есть (кэш M188 используется только для основной таблицы).
6. Без `--ref` вывод прежний, байт в байт: проверить сравнением с `handoff/m188/score_m183.txt` (шаг 2.3).

```bash
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src/autoreels/cloud/gatescore.py tests/test_gatescore.py tools/score_gate.py
git commit -m "Gate yardstick (M191): coverage reports matched/missed/best; score_gate --ref <gate> — which reference clips a gate finds and what the missed ones are made of; measurement only"
```
Ожидается: pytest зелёный (прежнее число прошедших плюс новые), коммит.

### 2.3 Прежний вывод не изменился
```bash
cd /Users/danny/Documents/autoreels
rm -f reels-out/_score/m183.json
.venv/bin/python tools/score_gate.py m183 > handoff/m191/score_m183_again.txt 2>&1
diff <(grep -v '^$' handoff/m188/score_m183.txt) <(grep -v '^$' handoff/m191/score_m183_again.txt) && echo "без изменений"
```
Ожидается: `без изменений`. Если `handoff/m188/score_m183.txt` нет локально — `bash handoff/bin/take.sh m188`. Есть разница → **СТОП**: что изменилось.

## Часть 3. Замер
```bash
cd /Users/danny/Documents/autoreels
.venv/bin/python tools/score_gate.py ref191 2>&1 | tee handoff/m191/score_ref191.txt
.venv/bin/python tools/score_gate.py m183 --compare ref191 2>&1 | tee handoff/m191/compare.txt
.venv/bin/python tools/score_gate.py m183 --ref ref191 2>&1 | tee handoff/m191/ref_in_m183.txt
.venv/bin/python tools/score_gate.py ref191 --ref m183 2>&1 | grep -A80 "эталон m183 в ref191" | tee handoff/m191/m183_in_ref.txt
```
Ожидается:
1. `score_ref191.txt`: 7 строк источников и ИТОГО; клипов в ИТОГО — 64 минус закомментированные. Колонка «покрытие владельца» — сколько клипов владельца нашёл эталон (насколько эталон ассистента согласен с владельцем).
2. `compare.txt`: ИТОГО m183 и ref191 и разница по колонкам.
3. `ref_in_m183.txt`: «эталон ref191 в m183: найдено X из 64» и список потерянных клипов.
4. `m183_in_ref.txt`: обратное — сколько клипов m183 есть в эталоне (клипы автоматики, которые эталон не взял).

## Часть 4. Push
```bash
cd /Users/danny/Documents/autoreels
git push; git log --oneline -2; git status -sb | head -3
git diff --stat HEAD~1 -- src config prompts | tail -1     # только src/autoreels/cloud/gatescore.py
```

## Отчёт
`handoff/m191/REPORT.md` — строго по шаблону:
```
M191 — IMPLEMENTED, MEASURED (гейт не объявляется)
Коммит: <хэш>; pytest: N passed (было M)
Часть 1: применено источников 7/7 (пропущено: …); клипов эталона: N из 64; закомментировано по 1а: <stem M<n> — причина> | нет
         reviews/ после: только *_ref191.review* — да/нет (что ещё)
         предупреждения эталона (warn.txt): <одна строка на источник>
Часть 2: тесты: <имена>; вывод без --ref без изменений — да/нет
Часть 3: ИТОГО ref191 — <строка таблицы целиком>
         ИТОГО m183   — <строка таблицы целиком>
         разница      — <строка>
         эталон в m183: найдено X из N; по источникам: …
         m183 в эталоне: найдено Y из 69
         согласие эталона с владельцем (покрытие владельца у ref191): A/B
         потерянные клипы эталона: <список целиком из ref_in_m183.txt>
Пропущено/не совпало: …
```
```bash
bash handoff/bin/report.sh m191 apply_all.txt warn.txt score_ref191.txt compare.txt ref_in_m183.txt m183_in_ref.txt $(cd handoff/m191 && ls apply_*.txt)
```
Владельцу в чат — 3 строки: статус; «эталон в m183: X из N»; одна главная разница ИТОГО (колонка с наибольшим расхождением).
