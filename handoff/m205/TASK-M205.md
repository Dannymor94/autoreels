# TASK M205 (окно MAIN, Mac): похожесть клипов по звуку и глобальный отбор — A/B на трёх прогонах

Файлы — ветка `handoff`, папка `handoff/m205/`: `TASK-M205.md`, `m205-selection.patch` (написан и прогнан ассистентом, ложится на `main` после M204), `compare.py` (сравнение черновиков, только чтение).
Около 60 минут: три прогона `arl auto` без рендера. Отчёт — только на русском.

## Зачем
1. **Похожесть по мыслям карты.** m200: «Алгоритм или эмпатия» (prew_isaev_anna) ушёл как «общие мысли с M3: #52», хотя ни одной общей фразы у клипов нет. Мысли карты размечает модель, так что решение кода стояло на разметке модели.
2. **Жадный отбор.** Пул обходится по рангу сценариста, и сильный кандидат может закрыть собой двух хороших; одна правка начала каскадом меняет соседей.

Владелец, 2026-11-02: детерминированно, A/B на одних и тех же ответах моделей.

## Что вносит патч
- `cloud/autocut.py`:
  - `sound_close` — клипы похожи, если общих сыгранных фраз больше `close_share_max` от секунд более короткого, либо одна и та же первая фраза, либо одинаковый заголовок;
  - `select_global` — набор до `clips` кандидатов с наибольшей суммой оценок без похожих пар (точный перебор с отсечением до 30 кандидатов, выше — жадно по оценке).
- `config/r0.yaml`, autocut (по умолчанию — как раньше):
  - `close_by: units` (`sound` — по звуку);
  - `close_share_max: 0.0` (ни одной общей фразы);
  - `select: greedy` (`global` — сначала обходится лучший набор; проверки ниже по-прежнему могут отказать — тогда место занимает следующий).
- `__main__.py`, autocut — подключение. При `global` в консоли строка «отбор: глобальный — K без пересечений (сумма …), по порядку было бы J», если наборы различаются.
- `tests/test_m205_selection.py` — 7 тестов. Один из них на собранной карте воспроизводит случай «Алгоритма»: по мыслям жадно — 1 клип, глобально — 2, по звуку — 3. Без кода тесты не собираются.

Ассистент прогнал весь набор: 2660 прошли (было 2654 + 7, флейк menu упал). Упали прежние 7.

## Правила
1. Команда упала или не совпала с «Ожидается» → **СТОП**: номер части, команда, последние 40 строк. Ничего не чинить. Расхождение чисел — не СТОП, это замер.
2. Перед стартом не должно идти других `arl` и рендера: `pgrep -fl "autoreels|ffmpeg"`.
3. **НЕ МЕНЯТЬ:**
   - ничего, кроме того, что вносит патч;
   - `config/r0.yaml` после части 2 вернуть (`git checkout config/r0.yaml`): включает владелец по замеру;
   - `.env` не трогать;
   - гейты `m183`, `m196`, `m200`, `rp1`, `rp2`, `k203`, `f204` и их `reviews/*` не трогать.

   Без рендера, без `--install`. `arl export`, `arl crosspost` и сетку не запускать.
4. `data/cache/llm/` не удалять. Прогоны идут в `record`: старые ответы берутся из кэша, новые (плашки клипов, которых не было в f204) запрашиваются у бесплатной модели и сохраняются.
5. Итог — «IMPLEMENTED, MEASURED». Гейт не объявлять.

## Часть 0. Предусловия
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -1; pgrep -fl "autoreels|ffmpeg" || echo "ничего не запущено"
bash handoff/bin/take.sh m205
find data/cache/llm -name '*.json' | wc -l
```
Ожидается:
- ветка `main`, чисто (кроме `handoff/`), последний коммит — M204 (`2680162`);
- в кэше ≥ 222 файлов (M204).

## Часть 1. Патч, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
git apply --check handoff/m205/m205-selection.patch && git apply handoff/m205/m205-selection.patch && echo applied
.venv/bin/python -m pytest tests/test_m205_selection.py tests/test_m202_replay_accounting.py tests/test_autocut.py tests/test_scenario.py -q 2>&1 | tail -1
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add config/r0.yaml src/autoreels/__main__.py src/autoreels/cloud/autocut.py src/autoreels/core/config.py tests/test_m205_selection.py
git commit -m "Selection (M205): autocut.close_by sound — two reels too close by the sentences heard in both (close_share_max), the same first sentence or title, not by the map's thoughts; autocut.select global — the set with the largest total score and no two too close goes first (defaults: units, greedy — as before)"
git push; git log --oneline -1
```
Ожидается:
- `applied`;
- первая строка pytest — все прошли;
- весь набор — прежнее число плюс 7 (флейк `test_menu_bash::…profile_picker…` — перезапустить отдельно; прошёл → не СТОП);
- коммит запушен.

## Часть 2. A/B: три прогона с `start_morph: true`
`start_morph` включён во всех трёх: именно с ним «Алгоритм» уходил в m200.

| тег | `close_by` | `select` |
|---|---|---|
| s205a | units | greedy — как сейчас |
| s205b | sound | greedy |
| s205c | sound | global |

```bash
cd /Users/danny/Documents/autoreels
S7=(disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny)
run() {  # tag close_by select
  git checkout -q config/r0.yaml
  .venv/bin/python - "$2" "$3" <<'EOF'
import re, sys
from pathlib import Path
p = Path("config/r0.yaml"); t = p.read_text(encoding="utf-8")
for key, val in (("start_morph", "true"), ("close_by", sys.argv[1]), ("select", sys.argv[2])):
    assert len(re.findall(rf"(?m)^  {key}: \w+", t)) == 1, key
    t = re.sub(rf"(?m)^  {key}: \w+", f"  {key}: {val}", t)
p.write_text(t, encoding="utf-8"); print("конфиг:", "start_morph true, close_by", sys.argv[1], ", select", sys.argv[2])
EOF
  ARL_LLM_CACHE=record .venv/bin/python -m autoreels auto "${S7[@]}" --mode scenario --llm cloud --gate "$1" --tag "$1" --no-render > "handoff/m205/$1.txt" 2>&1; echo "$1: код $?"
}
run s205a units greedy
run s205b sound greedy
run s205c sound global
git checkout config/r0.yaml; grep -n "  start_morph:\|  close_by:\|  select:" config/r0.yaml
for t in s205a s205b s205c; do echo "== $t"; sed -n '/=== auto: итог/,$p' handoff/m205/$t.txt | tail -9; done
.venv/bin/python handoff/m205/compare.py s205a s205b s205c | tee handoff/m205/compare.txt
grep -c "учёт кандидатов" handoff/m205/s205a.txt handoff/m205/s205b.txt handoff/m205/s205c.txt
grep -h "отбор: глобальный" handoff/m205/s205c.txt | tee handoff/m205/global.txt
grep -hE "^  ≈ " handoff/m205/s205b.txt | head -20 | tee handoff/m205/close_sound.txt
git status -sb | head -5
```
Ожидается:
- после прогонов `start_morph: false`, `close_by: units`, `select: greedy` (файл вернулся);
- каждый прогон: код 0, у всех 7 `✓`, промахов 0;
- `compare.txt` — таблица сборок по источникам и разница a→b, b→c. «Алгоритм»: в s205a нет (как в m200), в s205b и s205c — взят;
- «учёт кандидатов» — 0 во всех трёх;
- `global.txt` — строки, где глобальный набор отличается от порядка (может быть пусто — тогда отбор по порядку уже был лучшим);
- `git status` чистый вне `handoff/`.

## Отчёт
`handoff/m205/REPORT.md`:
```
M205 — IMPLEMENTED, MEASURED
Коммит: <хэш>; pytest: N passed (было M)
Сборок всего: s205a <n>, s205b <n>, s205c <n>; по источникам — compare.txt
«Алгоритм или эмпатия»: s205a <нет/взят>, s205b <…>, s205c <…>
a→b (по звуку): + <n> / − <n>; b→c (глобально): + <n> / − <n>; global.txt: <строк>
Пропущено/не совпало: …
```
```bash
bash handoff/bin/report.sh m205 s205a.txt s205b.txt s205c.txt compare.txt global.txt close_sound.txt
```
Владельцу в чат — 3 строки:
1. статус и коммит;
2. «сборок: сейчас <a>, по звуку <b>, по звуку + глобально <c>; „Алгоритм“: <…>»;
3. «включить — close_by: sound, select: global (решение владельца после просмотра compare.txt)».
