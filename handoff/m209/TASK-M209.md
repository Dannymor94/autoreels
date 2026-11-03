# TASK M209 (окно MAIN, Mac): паспорт карты — модель, правила только там, где модель не ответила

Файлы — ветка `handoff`, папка `handoff/m209/`: `TASK-M209.md`, `m209-map-fallback.patch` (написан и прогнан ассистентом, ложится на `main` после M208, `6b5cf91`).
Около 25 минут: два прогона replay без рендера. Отчёт — только на русском.

## Зачем
m208: паспорт по правилам хуже модели — покрытие клипов владельца 33 против 36 из 56. Правила модель не заменяют.
Владелец, 2026-11-02: правила — запасной вариант, только для мыслей, на которые модель не ответила. Неполная карта больше не должна останавливать `arl auto`.

## Что вносит патч
- `cloud/textmap.py` — `apply_fallback`:
  - мысли без паспорта модели получают паспорт правил;
  - мысли из части источника, где запрос тем остался без ответа (тема −1), получают тему правил (номера от 1000, без пересечений с темами модели);
  - полная карта возвращается как есть; карта совсем без тем — как раньше (каждая мысль — своя тема).
- `config/r0.yaml`: `autocut.map_passport: fallback` (решение владельца; в коде по умолчанию `model`).
  - `arl map`: неполная карта — `⚠` и код 0, а не `✗` и код 3; файл карты хранит, чего не хватает, повтор `arl map` дозапросит у модели;
  - autocut: «по правилам паспорт N, тема M».
- Тесты:
  - `test_map.py` (строгий режим) и `test_m208_textmap.py` явно ставят `map_passport: model`;
  - `tests/test_m209_map_fallback.py` — 4 теста.
- Документация: `PLAN.md` (с итогом m208), `README.md`, `docs/REEL_SPEC.md`, `PROJECT_STRUCTURE.md`.

Ассистент прогнал весь набор: 2689 прошли, упали прежние 7.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить.
2. Перед стартом не должно идти других `arl` и рендера: `pgrep -fl "autoreels|ffmpeg"`.
3. **НЕ МЕНЯТЬ:**
   - ничего, кроме того, что вносит патч;
   - карты `transcripts/*.map.json`, `.env`, гейты и их `reviews/*` не трогать.

   **Без рендера.** `arl export`, `arl crosspost` и сетку не запускать. `data/token_scale.json` не коммитить.
4. Итог — «IMPLEMENTED, VERIFIED». Гейт не объявлять.

## Часть 0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m209
ls reviews/*_auto_all_t206.txt reviews/*_auto_all_p208m.txt | wc -l
```
Ожидается:
- ветка `main`, последний коммит — M208 (`6b5cf91`);
- черновиков t206 и p208m — `14`.

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git apply --check handoff/m209/m209-map-fallback.patch && git apply handoff/m209/m209-map-fallback.patch && echo applied
grep -n "  map_passport:" config/r0.yaml
.venv/bin/python -m pytest tests/test_m209_map_fallback.py tests/test_m208_textmap.py tests/test_map.py -q 2>&1 | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add PLAN.md PROJECT_STRUCTURE.md README.md config/r0.yaml docs/REEL_SPEC.md src/autoreels/__main__.py src/autoreels/cloud/textmap.py src/autoreels/core/config.py tests/test_m208_textmap.py tests/test_m209_map_fallback.py tests/test_map.py
git commit -m "Map fallback (M209): owner 2026-11-02 — autocut.map_passport fallback: the model's passport, the rules only for the thoughts it gave nothing and the topic only for a part the topics request left unanswered; a complete map is unchanged, an incomplete one no longer stops arl auto (arl map warns, code 0); m208 measured: all by rules 33 of 56 owner clips against the model's 36; docs"
git push; git log --oneline -1
git status -s | grep -v "handoff/\|data/token_scale.json" || echo "всё закоммичено"
```
Ожидается:
- `applied`; `map_passport: fallback`;
- первая строка pytest — все прошли, кроме прежнего `test_map.py::test_voice_profile…` (praat) — не СТОП;
- весь набор — прежнее число плюс 4 (флейк `test_menu_bash::…profile_picker…` — перезапустить отдельно);
- коммит запушен; «всё закоммичено».

## Часть 2. Полные карты — выход не меняется (replay, без рендера)
Все 7 карт полные, поэтому `fallback` не должен менять ни одного черновика ни в режиме сценариста (= t206), ни в режиме автомонтажа (= p208m).
```bash
cd /Users/danny/Documents/autoreels
S7=(disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny)
ARL_LLM_CACHE=replay .venv/bin/python -m autoreels auto "${S7[@]}" --mode scenario --llm cloud --gate f209s --tag f209s --no-render > handoff/m209/f209s.txt 2>&1; echo "сценарист: код $?"
ARL_LLM_CACHE=replay .venv/bin/python -m autoreels auto "${S7[@]}" --mode autocut --llm cloud --gate f209a --tag f209a --no-render > handoff/m209/f209a.txt 2>&1; echo "автомонтаж: код $?"
for t in f209s f209a; do echo "== $t"; sed -n '/=== auto: итог/,$p' handoff/m209/$t.txt | tail -9; done
grep -c "по правилам паспорт" handoff/m209/f209s.txt handoff/m209/f209a.txt
{ for s in "${S7[@]}"; do printf "%-18s сценарист %s, автомонтаж %s\n" "$s" \
    "$(cmp -s reviews/${s}_auto_all_t206.txt reviews/${s}_auto_all_f209s.txt && echo одинаковый || echo РАЗНЫЙ)" \
    "$(cmp -s reviews/${s}_auto_all_p208m.txt reviews/${s}_auto_all_f209a.txt && echo одинаковый || echo РАЗНЫЙ)"; done; } | tee handoff/m209/same.txt
git status -sb | head -5
```
Ожидается:
- оба прогона: код 0, у всех 7 `✓`, «промахов 0»;
- «по правилам паспорт» — `0` в обоих (карты полные);
- `same.txt` — 7 из 7 «одинаковый» в обоих столбцах;
- `git status` чистый вне `handoff/`.

Промахи replay или «РАЗНЫЙ» — не СТОП: выписать источники, шаги и первые строки `diff`.

## Отчёт
`handoff/m209/REPORT.md`:
```
M209 — IMPLEMENTED, VERIFIED
Коммит: <хэш>; pytest: N passed (было M)
Сценарист f209s: код <…>, промахов <…>, одинаковых с t206 <x>/7
Автомонтаж f209a: код <…>, промахов <…>, одинаковых с p208m <y>/7
«по правилам паспорт»: <0/0>
Пропущено/не совпало: …
```
```bash
bash handoff/bin/report.sh m209 f209s.txt f209a.txt same.txt
```
Владельцу в чат — 2 строки:
1. статус и коммит;
2. «карта: модель + правила там, где модель не ответила; на полных картах выход тот же — <x>/7 и <y>/7».
