# TASK M204 (окно MAIN, Mac): `k:` по правилу (решение владельца); в режиме сценариста остальное — на модели прогона; record → replay на бесплатных моделях

Файлы — ветка `handoff`, папка `handoff/m204/`: `TASK-M204.md`, `m204-polish-free.patch` (написан и прогнан ассистентом, ложится на `main` после M203).
Около 40 минут: два прогона `arl auto` без рендера. Отчёт — только на русском.

## Зачем
Владелец, 2026-11-02: платного API нет (Claude: HTTP 403). Решения:
1. `k:` — по правилу M203 (31 % точных слов, `k:` у 54 из 54 сборок), не больше 2 на клип.
2. В режиме сценариста крючки, плашки, `k:` и стыки идут на модель прогона (`--llm`), а не на Sonnet. В m202 и m203 при `--llm cloud` всё равно звали Claude (`llm=_scen_llm`): 151 отказ, плашки пустые.
3. Детерминизм через кэш: бесплатная модель отвечает в `record`, повтор в `replay` даёт тот же черновик байт в байт.

Ассистент проверил и **не стал делать** (`k:` уже сделаны в M203):
- стыки без модели — правила начала клипа помечают 33 % и плохих (12 вердиктов модели), и хороших (42 стыка владельца): сигнала нет;
- крючки — выбор кода `hook_score` уже детерминирован, а эталона нет: холодный старт у владельца в 3 клипах из 68;
- плашки из слов клипа — 20 % совпадения смысловых слов с плашками владельца (случайный кусок — 8 %), на экран лезут фразы вроде «ух ты ни хрена себе!». Плашки владельца — пересказ, не цитата.

## Что вносит патч
- `config/r0.yaml` (решение владельца 2026-11-02): `keywords_source: rule`, `keywords_max: 2`, `scenario_polish: run`.
- `core/config.py` — `autocut.scenario_polish: scenarist | run`, в коде по умолчанию `scenarist` (как до M204).
- `__main__.py`:
  - `cmd_autocut(scenario_llm=…)` — сценарист на своей модели, остальное на `llm`;
  - `cmd_auto` через `_scenario_autocut_llms`: при `run` передаёт `llm` прогона и `scenario_llm` сценариста.
- Тесты:
  - обновлены `test_m153_auto_mode.py` (проверял «всё на Sonnet» — теперь проверяет разделение, и отдельный тест — что `scenarist` даёт прежнее поведение), `test_m203_keywords_rule.py` (конфиг репо теперь `rule`), `test_autocut.py::test_m116…` (явно ставит модельный режим `k:`, который проверяет);
  - добавлены 3 теста M204.

Ассистент прогнал весь набор: 2654 прошли, упали прежние 7 (ffmpeg, praat, `data/runs/`).

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить. Промахи replay и «модель не ответила» в части 2 — не СТОП, это замер.
2. Перед стартом не должно идти других `arl` и рендера: `pgrep -fl "autoreels|ffmpeg"`.
3. **НЕ МЕНЯТЬ:**
   - ничего, кроме того, что вносит патч;
   - `.env` не трогать;
   - гейты `m183`, `m196`, `m200`, `rp1`, `rp2`, `k203` и их `reviews/*` не трогать.

   Без рендера, без `--install`. `arl export`, `arl crosspost` и сетку не запускать.
4. `data/cache/llm/` не удалять.
5. Итог — «IMPLEMENTED, MEASURED». Гейт не объявлять.

## Часть 0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m204
grep -c "^GROQ_API_KEY=.\|^OPENROUTER_API_KEY=." .env
```
Ожидается:
- ветка `main`, чисто (кроме `handoff/`), последний коммит — M203 (`3992cfb`);
- ключей бесплатных моделей ≥ 1. Если `0` — **СТОП**: бесплатной модели нет, часть 2 не имеет смысла.

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git apply --check handoff/m204/m204-polish-free.patch && git apply handoff/m204/m204-polish-free.patch && echo applied
.venv/bin/python -m pytest tests/test_m153_auto_mode.py tests/test_m203_keywords_rule.py tests/test_autocut.py tests/test_m202_replay_accounting.py -q 2>&1 | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -3
grep -n "keywords_source:\|keywords_max:\|scenario_polish:" config/r0.yaml
git add config/r0.yaml src/autoreels/__main__.py src/autoreels/core/config.py tests/test_autocut.py tests/test_m153_auto_mode.py tests/test_m203_keywords_rule.py
git commit -m "Free polish (M204): owner 2026-11-02, no paid API — k: by the rule, at most 2 (keywords_source: rule, keywords_max: 2); autocut.scenario_polish run: in scenario mode the scenarist answers on its model, the hooks, plates, k: and seams on the run's --llm (m202/m203: 151 refusals of Claude whatever --llm said)"
git push; git log --oneline -1
```
Ожидается:
- `applied`;
- первая строка pytest — все прошли;
- весь набор — прежнее число плюс 3 (флейк `test_menu_bash::…profile_picker…` — перезапустить отдельно; прошёл → не СТОП);
- `keywords_source: rule`, `keywords_max: 2`, `scenario_polish: run`;
- коммит запушен.

## Часть 2. record → replay: сценарист из кэша, остальное на бесплатной модели
```bash
cd /Users/danny/Documents/autoreels
S7=(disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny)
ARL_LLM_CACHE=record .venv/bin/python -m autoreels auto "${S7[@]}" --mode scenario --llm cloud --gate f204 --tag f204a --no-render > handoff/m204/rec.txt 2>&1; echo "record: код $?"
ARL_LLM_CACHE=replay .venv/bin/python -m autoreels auto "${S7[@]}" --mode scenario --llm cloud --gate f204 --tag f204b --no-render > handoff/m204/rep.txt 2>&1; echo "replay: код $?"
for f in rec rep; do echo "== $f"; sed -n '/=== auto: итог/,$p' handoff/m204/$f.txt; done
grep -h "^  модели:" handoff/m204/rec.txt | sort | uniq -c
for f in rec rep; do echo "== $f: модель не ответила"; .venv/bin/python - "handoff/m204/$f.txt" <<'EOF'
import re, sys, collections
c = collections.Counter()
for ln in open(sys.argv[1], encoding="utf-8", errors="replace"):
    m = re.search(r"([^\s:]+): модель не ответила \(([^)]{0,70})", ln)
    if m:
        c[(m.group(1), m.group(2))] += 1
for (step, why), n in c.most_common():
    print(f"  {n:4} {step}: {why}")
EOF
done
{ for s in "${S7[@]}"; do a=reviews/${s}_auto_all_f204a.txt; b=reviews/${s}_auto_all_f204b.txt
    printf "%-18s %s; сборок %2s, с t: %2s, с k: %2s\n" "$s" "$(cmp -s "$a" "$b" && echo одинаковый || echo РАЗНЫЙ)" \
      "$(grep -c '^M' "$a")" "$(grep '^M' "$a" | grep -c ' | t: ')" "$(grep '^M' "$a" | grep -c ' | k:')"
  done; } | tee handoff/m204/same.txt
grep -h "^M" reviews/*_auto_all_f204a.txt | sed -n 's/.* | t: \([^|]*\).*/\1/p' | head -15 | tee handoff/m204/plates.txt
git status -sb | head -5
```
Ожидается:
- record: код 0, у всех 7 `✓`;
- «модели:» — бесплатные (Groq / OpenRouter), **не Claude**;
- replay: «записано 0, промахов 0», код 0;
- `same.txt` — 7 из 7 «одинаковый»; «с k:» = «сборок»;
- `plates.txt` — плашки есть.

Если бесплатная модель тоже отказывала (строки «модель не ответила» в rec), replay даст промахи по тем же запросам — не СТОП: выписать по шагам и причине.

## Отчёт
`handoff/m204/REPORT.md`:
```
M204 — IMPLEMENTED, MEASURED
Коммит: <хэш>; pytest: N passed (было M)
Модели прогона (rec): <строки «модели:»>
record: код <…>; кэш: из кэша a, записано b; модель не ответила: <шаг × N, причина>
replay: код <…>; кэш: из кэша c, записано 0, промахов d
Одинаковых черновиков: <x>/7; сборок <всего>, с t: <n>, с k: <n>
Плашки (plates.txt): <3–5 примеров>
Пропущено/не совпало: …
```
```bash
bash handoff/bin/report.sh m204 rec.txt rep.txt same.txt plates.txt
```
Владельцу в чат — 3 строки:
1. статус и коммит;
2. «бесплатная модель: <отвечает / отказывает: причина>; воспроизводимость: replay код <…>, одинаковых <x>/7»;
3. «плашки у <n> из <всего> сборок, k: у <n>».
