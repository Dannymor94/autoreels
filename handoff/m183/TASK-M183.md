# TASK M183 (окно MAIN, Mac): чистовик — крючки у интервью и у клипов разметки, перепрогон в m183, старые гейты в Корзину

Файлы — ветка `handoff`, папка `handoff/m183/`: `TASK-M183.md`, `m183-hooks.patch`, `hooks.py`. Около 2,5 ч (проба 10 мин + перепрогон в фоне).

**Начни с новой сессии агента (`/clear`). Отчёт — только на русском.** Перед шагом 1 обязательно `git pull` и `bash handoff/bin/take.sh m183`: в m182 был взят старый патч (без крючков для клипов разметки, 10 тестов вместо 11) и старая задача (без шага уборки).

## Зачем
Итог m182: крючки у 19 из 69 роликов. У disko_beach прибавилось, а у prew_isaev_anna по-прежнему 1 из 9, крючков из части фразы 0. Две причины:
1. **В m182 не вошли крючки для клипов разметки** (`autocut.label_hooks`): патч взят до обновления. Здесь они есть.
2. **Предложение, начинающееся на «А…», «То есть…», «Вот…», выбрасывалось из кандидатов целиком,** вместе со всеми его частями. В интервью так начинается большинство фраз. Теперь такое предложение само крючком не становится (как раньше), но его поздняя часть («…я понял главную вещь о себе,») — может.

Патч (поверх m182):
- `autocut.label_hooks`: клип разметки в `arl auto` получает крючок из своей второй половины — целое предложение нужной длины или часть длинного, лучший по `hook_score`, без модели;
- части фразы из предложений со ссылкой назад или склеенным началом;
- тесты: `tests/test_m182_hooks_starts.py` — 12 (было 10);
- выключенные флаги = прежний выход (тесты).

**Владелец 2026-10-29: «все видео должны быть готовы — перерендерим, старые удаляем, новые — чистовик».** Гейт `m183` — продакшн. Все остальные гейты уходят в Корзину в шаге 5, только после успешного прогона.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. `--install` не запускать. `reviews/*_answer*.txt`, `manifests/` не трогать. Гейты не трогать до шага 5.
3. Рендер один за раз; pytest — не во время рендера.

## Шаг 1. Патч, тесты, коммит
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m183; mkdir -p handoff/m183; grep -c "label_hooks" handoff/m183/m183-hooks.patch
git apply --check handoff/m183/m183-hooks.patch && git apply handoff/m183/m183-hooks.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3; .venv/bin/python -m pytest -q tests/test_m182_hooks_starts.py | tail -1
git add src tests config docs && git commit -m "Autocut (M183): label clips of arl auto get a cold open from their own second half (autocut.label_hooks); a sentence that points back still gives its later clauses as hooks (m182: prew_isaev_anna 0 clause hooks)" && git push && git log --oneline -1
```
Ожидается:
- `grep -c` больше 0;
- `applied`;
- pytest — всё прошло, кроме известных пяти (`test_menu_bash` под нагрузкой — отдельно);
- `test_m182_hooks_starts.py`: **12 passed**;
- коммит запушен.

## Шаг 2. Проба без рендера на prew_isaev_anna (10 минут)
```bash
.venv/bin/python -m autoreels auto prew_isaev_anna --gate m183pre --tag m183pre --no-render > handoff/m183/pre.txt 2>&1; tail -3 handoff/m183/pre.txt
grep -cE "h:[0-9x]+\.[0-9]+" reviews/prew_isaev_anna_auto_m183pre.txt; grep -c "^M" reviews/prew_isaev_anna_auto_m183pre.txt
grep -cE "@[0-9]+-[0-9]+" reviews/prew_isaev_anna_auto_m183pre.txt
grep -hE "крючки отброшены моделью|ни один из первых|без крючка|крючок " handoff/m183/pre.txt reviews/prew_isaev_anna_auto_m183pre.txt | head -20 | tee handoff/m183/pre_hooks.txt
```
Ожидается: строк `M` с `h:` — больше половины (в m182 — 1 из 8). Если меньше трёх — СТОП с `pre_hooks.txt`: значит, крючки отбрасывает модель-судья, правку делает ассистент.

## Шаг 3. Перепрогон всего в m183 (в фоне)
```bash
S7=(disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny)
nohup .venv/bin/python -m autoreels auto "${S7[@]}" --gate m183 --tag m183 --encoder hevc_videotoolbox > handoff/m183/auto.txt 2>&1 &
echo "pid $!"
```
Проверять раз в 10 минут до `=== auto: итог`. Затем:
```bash
sed -n '/=== auto: итог/,$p' handoff/m183/auto.txt | tee handoff/m183/itog.txt
.venv/bin/python handoff/m183/hooks.py > handoff/m183/hooks.txt; grep -E "^######|^== " handoff/m183/hooks.txt
grep -h "^  крючок " handoff/m183/auto.txt | wc -l
.venv/bin/python handoff/m173/measure_shots.py reviews/*_m183.review.json | tail -1
```
Ожидается:
- у всех 7 ✓;
- в `hooks.txt` «с крючком» в m183 — у большинства роликов каждого источника; у клипов разметки — строки «крючок …»;
- SLIVER 0.

## Шаг 4. Посты, выгрузка, сетка
Как шаг 4 m174, с гейтом `m183`:
- посты без `.post.txt` — `arl describe … --gate m183 --reels … --force --llm sonnet`, до двух раз;
- `export/crosspost/*` → Корзина, кроме `schedule.csv`; затем `arl crosspost` по 7 источникам;
- `python handoff/m174/grid2.py m183 --from m182`; новые клипы — по смыслу в `schedule.csv` (правила m171, «связь»), затем `grid2.py m183 --from m183`;
- `cp export/crosspost/grid.csv handoff/m183/grid.csv`.

## Шаг 5. Старые гейты — в Корзину (только если шаги 3–4 прошли)
```bash
mkdir -p ~/.Trash/autoreels-m183
for d in reels-out/*/_gate/*; do [ "$(basename "$d")" = m183 ] && continue; S=$(basename "$(dirname "$(dirname "$d")")"); mkdir -p ~/.Trash/autoreels-m183/$S; mv "$d" ~/.Trash/autoreels-m183/$S/; done
ls reels-out/*/_gate/ | sort | uniq -c | tee handoff/m183/gates_after.txt
```
Ожидается: в `reels-out/<источник>/_gate/` у всех 7 осталась только `m183`. Корзину не очищать.

## Шаг 6. Отчёт (на русском)
`handoff/m183/REPORT.md`:
- коммит, число тестов;
- проба шага 2;
- `itog.txt`;
- итог `hooks.txt` (строки «==»);
- сколько клипов разметки получили крючок;
- вспышки;
- клипов по источникам (m182 → m183);
- вывод `grid2.py`;
- `gates_after.txt`.

`bash handoff/bin/report.sh m183 pre_hooks.txt itog.txt hooks.txt gates_after.txt grid.csv`

Владельцу — две строки:
- «чистовик: N клипов в reels-out/<источник>/_gate/m183, крючок у X из N (в m182 — 19 из 69); старые гейты в Корзине»;
- «сетка — export/crosspost/grid.csv».

Статус: IMPLEMENTED, GATE PENDING.
