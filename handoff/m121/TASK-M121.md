# TASK M121 (окно MAIN, Mac): включить новую автосборку по умолчанию — по замерам m120

Файлы — в ветке `handoff`, папка `handoff/m121/`: `TASK-M121.md`, `decide.py`, `m121-defaults-mixed.patch`, `m121-defaults-montage.patch`.

**Только после M120**: коммит M120 в `main`, файлы `handoff/m120/gen.txt` и `handoff/m120/drafts.txt` на месте. Около 10 минут, без модели.

## Зачем
Владелец (2026-10-20): «собери» — флаги M119/M120 включить по умолчанию, не дожидаясь просмотра. Откат — строки `autocut:` в `config/r0.yaml`.

**Включаются в обоих вариантах:**
- `lean_depth: 1` — одно звено сносок;
- `rhythm: true` — правило скачков;
- `context_judge: false` — судья первой фразы вне отбора;
- `clips_every_min: 3.5` — сборок по длине видео.

**Генератор** выбирает `decide.py` по правилу, объявленному заранее. Включается `mixed` (вместе с `seed_roles` explanation/address и `target_sec: 35`), если выполнены оба условия:
- (a) без модели на всех источниках X покрывает клипов владельца не меньше, чем R;
- (b) с моделью на трёх источниках у m120-mixed сборок не меньше, чем у m120-montage.

Иначе остаётся `montage` (`target_sec` прежний).

Тесты `test_cmd_autocut_writes_a_draft_that_applies` и `test_m119_cmd_autocut…` поправлены, чтобы не зависеть от значений по умолчанию: проходят и со старыми, и с новыми.

## Правила
1. Любой шаг упал или не совпал с «Ожидается» → **СТОП**: номер шага, команда, последние 40 строк. Ничего не чинить.
2. Перед стартом не должно идти других `arl` и рендера. Если в pytest упал только `tests/test_menu_bash.py::test_menu_settings_profile_picker_and_cancel` — перезапустить этот тест один раз; прошёл — не СТОП, отметить в отчёте.
3. Не трогать `reviews/*_answer.txt`, `reviews/*.review.json`, `reviews/verdicts.jsonl`, черновики прошлых задач, манифест `PXL_20260729_085910095_34f06abf.json`. Черновик проверки — новый файл `reviews/IMG_6848_auto_m121-check.txt`. `arl auto`, `arl render`, `arl export` не запускать.
4. Псевдонима `arl` в оболочке агента нет: первая строка блока определяет функцию. Блок запускать целиком.

## Шаг 1. Выбор генератора
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -1; git log --oneline -1; pgrep -fl "arl " || echo "arl не запущен"
.venv/bin/python handoff/m121/decide.py | tee handoff/m121/decide.txt
```
Ожидается:
- последний коммит — M120;
- строки (a) и (b) с числами, последняя строка — `mixed` или `montage`.

Ошибка «нет замеров m120» — СТОП.

## Шаг 2. Патч выбранного варианта, тесты, коммит
```bash
cd /Users/danny/Documents/autoreels
V=$(tail -1 handoff/m121/decide.txt); echo "вариант: $V"
git apply --check handoff/m121/m121-defaults-$V.patch && git apply handoff/m121/m121-defaults-$V.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add config/r0.yaml docs/REEL_SPEC.md tests/test_autocut.py
git commit -m "Autocut (M121): new autocut on by default — generator $V, lean_depth 1, the jump rule, no start judge, clips by length (owner: «собери», before viewing; revert = config lines)"
git push; git log --oneline -1
```
Ожидается: `applied`; pytest — все прошли (с оговоркой правила 2); коммит запушен.

## Шаг 3. Проверка, что значения по умолчанию действуют
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels
arl autocut IMG_6848 --llm none --no-check --out reviews/IMG_6848_auto_m121-check.txt 2>&1 | grep -E "^autocut|сборок: до|ошибка" | tee handoff/m121/check.txt
git status --short
```
Ожидается:
- `сборок: до 10 (источник 35 мин ÷ 3.5)`;
- `autocut IMG_6848: предложено сборок N …`, где N > 6 (было 6);
- новых строк в `git status` нет.

## Шаг 4. Отчёт в ветку
Записать `handoff/m121/REPORT.md`:
1. `decide.txt` целиком.
2. Коммит, строка pytest.
3. `check.txt`.

```bash
cd /Users/danny/Documents/autoreels
bash handoff/bin/report.sh m121 decide.txt check.txt
```
Владельцу в чат — одна строка: какой генератор включён, числа (a) и (b), «теперь `arl auto` собирает по-новому; откат — строки autocut в config/r0.yaml».

Статус: IMPLEMENTED (значения по умолчанию включены по указанию владельца). Гейт — просмотр рендеров владельцем.
