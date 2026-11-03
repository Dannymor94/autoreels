# TASK M208 (окно MAIN, Mac): паспорт карты без модели — правила; замер против модели и A/B автомонтажа

Файлы — ветка `handoff`, папка `handoff/m208/`: `TASK-M208.md`, `m208-map-passport.patch` (написан и прогнан ассистентом, ложится на `main` после M207, `a1885a7`), `compare.py` — копия `handoff/m205/compare.py`.
Около 60 минут: замер и два прогона `arl auto` без рендера. Отчёт — только на русском.

## Зачем
Владелец, 2026-11-02: детерминированные механики, без платного API. Последнее модельное звено пути — карта мыслей.
Нарезку на мысли (1–4 фразы по паузам), голос и похожие места и так считает код. Модель даёт только **паспорт** мысли (роль, сила 1–5, понятна ли без предыдущего, опора, краткое) и **темы**. Это звено и заменяют правила.

**Главный критерий — клипы, а не совпадение с моделью:** сколько клипов владельца находит автомонтаж (`score_gate` — покрытие). В режиме сценариста паспорт почти не участвует, поэтому A/B идёт в режиме автомонтажа (`--mode autocut`), где на паспорте держится отбор.

## Что вносит патч
- `cloud/textmap.py` — паспорт и темы по правилам:
  - роль — по маркерам («?» — вопрос; «например / однажды / помню» — пример; «как будто / словно» — образ; «поэтому / итак / в итоге» — вывод; «потому что / то есть» — объяснение; < 3 смысловых слов — служебное; иначе тезис);
  - сила — сырой балл (краткость, «не…, а…», обобщения, энергия голоса, роль) и ранг внутри источника: 5 — верхние 10 %, 4 — 20 %, 3 — 30 %, 2 — 25 %, 1 — остальные; служебное — 1;
  - понятна ли без предыдущего — правила начала клипа (`back_reference`, `start_morph`); опора — предыдущая мысль;
  - краткое — самая содержательная фраза без паразитов;
  - темы — TextTiling по леммам (около 1 темы на 8 мыслей, 3–15, не короче 3 мыслей).
- `config/r0.yaml`: `autocut.map_passport: model` (по умолчанию как раньше); `rules` — пересчёт при чтении карты в autocut, **файл карты не меняется**. Проверка «карта неполна» идёт после пересчёта.
- `tools/map_rules_check.py` — совпадение с паспортом модели по 7 картам (только чтение).
- Документация: `PLAN.md`, `README.md`, `docs/REEL_SPEC.md`, `PROJECT_STRUCTURE.md`.
- `tests/test_m208_textmap.py` — 16 тестов.

Ассистент прогнал весь набор: 2684 прошли (было 2668 + 16), упали прежние 7 и флейк menu.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить. Расхождение чисел — не СТОП, это замер.
2. Перед стартом не должно идти других `arl` и рендера: `pgrep -fl "autoreels|ffmpeg"`.
3. **НЕ МЕНЯТЬ:**
   - ничего, кроме того, что вносит патч;
   - `config/r0.yaml` после части 3 вернуть (`git checkout config/r0.yaml`): включает владелец по замеру;
   - карты `transcripts/*.map.json`, `.env`, гейты и их `reviews/*` не трогать.

   **Без рендера.** `arl export`, `arl crosspost` и сетку не запускать. `data/token_scale.json` не коммитить.
4. `data/cache/llm/` не удалять (прогоны в `record`: новые ответы бесплатной модели сохраняются).
5. Итог — «IMPLEMENTED, MEASURED». Гейт не объявлять.

## Часть 0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m208
ls transcripts/{disko_beach_p1,disko_beach_p2,disko_beach_p3,day_yoga_p1,day_yoga_p2,prew_isaev_anna,prew_isaev_danny}.map.json | wc -l
```
Ожидается:
- ветка `main`, последний коммит — M207 (`a1885a7`);
- карт — `7`.

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git apply --check handoff/m208/m208-map-passport.patch && git apply handoff/m208/m208-map-passport.patch && echo applied
.venv/bin/python -m pytest tests/test_m208_textmap.py tests/test_map.py tests/test_autocut.py -q 2>&1 | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add PLAN.md PROJECT_STRUCTURE.md README.md config/r0.yaml docs/REEL_SPEC.md src/autoreels/__main__.py src/autoreels/cloud/textmap.py src/autoreels/core/config.py tests/test_m208_textmap.py tools/map_rules_check.py
git commit -m "Map passport (M208): autocut.map_passport rules (default model) — the role by markers, the strength by a raw score ranked within the source, standalone by the start rules, the summary the richest sentence, topics by TextTiling over lemmas; recomputed when autocut reads the map, the map file stays; tools/map_rules_check.py compares with the model's passport; docs"
git push; git log --oneline -1
git status -s | grep -v "handoff/\|data/token_scale.json" || echo "всё закоммичено"
```
Ожидается:
- `applied`;
- первая строка pytest — все прошли (в `test_map.py` прежнее падение `test_voice_profile…` — не СТОП);
- весь набор — прежнее число плюс 16;
- коммит запушен; «всё закоммичено».

## Часть 2. Совпадение с паспортом модели (только чтение)
```bash
cd /Users/danny/Documents/autoreels
.venv/bin/python tools/map_rules_check.py 2>&1 | tee handoff/m208/map_check.txt
```
Ожидается: строка на каждый из 7 источников (мыслей, роль %, сила ±1 %, ρ силы, самостоятельность %, границы тем), итог, распределения ролей и силы, частые расхождения. Любые числа — не СТОП.

## Часть 3. A/B автомонтажа: паспорт модели против правил
```bash
cd /Users/danny/Documents/autoreels
S7=(disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny)
run() {  # tag passport
  git checkout -q config/r0.yaml
  .venv/bin/python - "$2" <<'PY'
import re, sys
from pathlib import Path
p = Path("config/r0.yaml"); t = p.read_text(encoding="utf-8")
assert len(re.findall(r"(?m)^  map_passport: \w+", t)) == 1
p.write_text(re.sub(r"(?m)^  map_passport: \w+", f"  map_passport: {sys.argv[1]}", t), encoding="utf-8")
print("конфиг: map_passport", sys.argv[1])
PY
  .venv/bin/python -m autoreels auto "${S7[@]}" --mode autocut --llm cloud --gate "$1" --tag "$1" --no-render > "handoff/m208/$1.txt" 2>&1; echo "$1: код $?"
}
run p208m model
run p208r rules
git checkout config/r0.yaml; grep -n "  map_passport:" config/r0.yaml
for t in p208m p208r; do echo "== $t"; sed -n '/=== auto: итог/,$p' handoff/m208/$t.txt | tail -9; done
grep -c "паспорт и темы по правилам" handoff/m208/p208r.txt
.venv/bin/python tools/score_gate.py p208r --compare p208m 2>&1 | tee handoff/m208/score.txt | tail -30
.venv/bin/python handoff/m208/compare.py p208m p208r 2>&1 | head -12 | tee handoff/m208/counts.txt
git status -sb | head -5
```
Ожидается:
- после прогонов `map_passport: model` (файл вернулся);
- оба прогона: код 0, у всех 7 `✓`;
- «паспорт и темы по правилам» в p208r — `7`;
- `score.txt` — таблицы обоих прогонов, столбец «покрытие» (клипов владельца найдено из 66);
- `counts.txt` — сборок по источникам.

Код 1 или `✗` у источника — не СТОП, если это не падение команды: выписать причину из итога.

## Отчёт
`handoff/m208/REPORT.md`:
```
M208 — IMPLEMENTED, MEASURED
Коммит: <хэш>; pytest: N passed (было M)
Совпадение с моделью (map_check.txt, итог): роль <%>, сила ±1 <%>, ρ <…>, самостоятельность <%>, границы тем <hit/правил (у модели)>
Распределение силы модель → правила: <строка>
A/B автомонтажа: покрытие клипов владельца — модель <x/66>, правила <y/66>; сборок — модель <n>, правила <n>
Пропущено/не совпало: …
```
```bash
bash handoff/bin/report.sh m208 map_check.txt p208m.txt p208r.txt score.txt counts.txt
```
Владельцу в чат — 3 строки:
1. статус и коммит;
2. «паспорт карты без модели: покрытие клипов владельца — модель <x>/66, правила <y>/66»;
3. «совпадение с моделью: роль <%>, сила ±1 <%>; включить — autocut.map_passport: rules (решение владельца)».
