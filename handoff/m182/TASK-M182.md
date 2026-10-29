# TASK M182 (окно MAIN, Mac): чистовик — крючки, строгое начало, перепрогон всего в m182, старые гейты в Корзину

Файлы — ветка `handoff`, папка `handoff/m182/`: `TASK-M182.md`, `m182-hooks.patch`, `hooks.py`. Долго: перепрогон 7 источников с рендером (в фоне, около 2 ч). Сценарист — из кэша, судьи и посты — Sonnet из промо-кредитов (до 2026-11-02).

**Начни с новой сессии агента (`/clear`): в длинной сессии отчёты уходили на украинский. Язык отчёта — только русский (CLAUDE.md).**

## Зачем
Владелец о prew_isaev_anna m176: «r03, r14 — начало пустое»; «раньше хуки были лучше, сейчас пустые». Замер m181:
- крючок (холодный старт) у 1 ролика из 12, в m157 — у 1 из 20;
- крючком могло быть только целое предложение до `hook_max_sec`, а в интервью такие редки;
- начала вида «Каждый из них влияет…» (r14) или «Ты чувствуешь это…, Ласанна» (r10) правило только отодвигало в конец очереди.

Владелец выбрал «оба» (2026-10-29). Патч:
- **Крючок из части фразы** (`autocut.hook_clauses`). Холодный старт может быть законченным куском длинного предложения между паузами — `h:B.N@i-j`:
  - край куска — слово с «,;:—» и тишина не короче `hook_clause_pause`;
  - длина и число слов — как у обычного крючка;
  - в субтитрах крючка только эти слова, предложение целиком играет в теле;
  - модель выбирает среди кандидатов как раньше.
- **Строгое начало** (`autocut.start_strict`). Ролик сценариста не начинается со ссылки назад («Каждый из них», «Это», «То есть»…) или обращения к собеседнику («Ты…», «…, Ласанна»):
  - начало берётся на фразу-две раньше, если они идут подряд;
  - иначе ролика нет;
  - клип разметки с таким началом в `arl auto` убирается.
- **Крючок для клипов разметки** (`autocut.label_hooks`). У них крючка не было никогда, отсюда «пустые» начала. Теперь клип разметки в `arl auto` получает крючок из своей второй половины по тем же правилам: целое предложение нужной длины или часть длинного, лучший по `hook_score`, без модели.
- Все три флага выключены по умолчанию (тест), в `config/r0.yaml` включены.
- Тесты `tests/test_m182_hooks_starts.py` (11). Документы: REEL_SPEC §2 п. 4, README, PLAN.

Перепрогон заодно вносит M181 (ширина плашки и субтитров по шрифту) во все клипы.

**Владелец 2026-10-29: «все видео должны быть готовы — перерендерим, старые удаляем, новые — чистовик».** Гейт `m182` — новый продакшн. Старые гейты уходят в Корзину в шаге 5, только после успешного прогона.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. `--install` не запускать. `reviews/*_answer*.txt`, `manifests/` не трогать. Старые гейты не трогать до шага 5.
3. Рендер один за раз; pytest — не во время рендера.

## Шаг 1. Патч, тесты, коммит
```bash
arl() { .venv/bin/python -m autoreels "$@"; }
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"
bash handoff/bin/take.sh m182; mkdir -p handoff/m182
git apply --check handoff/m182/m182-hooks.patch && git apply handoff/m182/m182-hooks.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests config docs README.md PLAN.md && git commit -m "Autocut (M182): a cold open may be a clause of a long sentence (h:B.N@i-j, autocut.hook_clauses); a reel never opens on a line pointing back or at the interviewer — earlier start or none (autocut.start_strict)" && git push && git log --oneline -1
```
Ожидается: `applied`. pytest: всё прошло, кроме известных пяти (`test_menu_bash` под нагрузкой — отдельно). Коммит запушен.

## Шаг 2. Перепрогон (в фоне)
```bash
S7=(disko_beach_p1 disko_beach_p2 disko_beach_p3 day_yoga_p1 day_yoga_p2 prew_isaev_anna prew_isaev_danny)
nohup .venv/bin/python -m autoreels auto "${S7[@]}" --gate m182 --tag m182 --encoder hevc_videotoolbox > handoff/m182/auto.txt 2>&1 &
echo "pid $!"
```
Проверять раз в 10 минут до строки `=== auto: итог`. Сценарист должен взяться из кэша. Пошёл в модель — не СТОП: в отчёт сумму.

## Шаг 3. Замер: крючки, начала, скачки
```bash
sed -n '/=== auto: итог/,$p' handoff/m182/auto.txt | tee handoff/m182/itog.txt
.venv/bin/python handoff/m182/hooks.py > handoff/m182/hooks.txt; grep -E "^######|^== " handoff/m182/hooks.txt
grep -c "@[0-9]*-[0-9]*" reviews/*_auto_m182.txt | tee handoff/m182/clause_hooks.txt
grep -h "начало: «" handoff/m182/auto.txt | head -20 | tee handoff/m182/starts.txt
grep -h "раньше начать нельзя\|weak start" handoff/m182/auto.txt | wc -l
.venv/bin/python handoff/m173/measure_shots.py reviews/*_m182.review.json | tail -1
```
Ожидается:
- в `hooks.txt` у каждого источника «с крючком» в m182 заметно больше, чем в m176 (у prew_* было 1); у клипов разметки — строки «крючок …» в `auto.txt`;
- в `clause_hooks.txt` — сколько крючков из части фразы;
- `starts.txt` — примеры поправленных начал;
- вспышек (SLIVER) 0.

Если крючков почти не прибавилось — СТОП с `hooks.txt` и строками «крючки отброшены моделью» из `auto.txt`: значит, кандидатов отсекает судья, а не правило.

## Шаг 4. Посты, выгрузка, сетка
Как шаг 4 m174, с гейтом `m182`. В конце: `python handoff/m174/grid2.py m182 --from m176`. Новые клипы — по смыслу, затем `grid2.py m182 --from m182`. `cp export/crosspost/grid.csv handoff/m182/grid.csv`.

## Шаг 5. Старые гейты — в Корзину (только если шаги 2–4 прошли)
```bash
mkdir -p ~/.Trash/autoreels-m182
for d in reels-out/*/_gate/*; do [ "$(basename "$d")" = m182 ] && continue; S=$(basename "$(dirname "$(dirname "$d")")"); mkdir -p ~/.Trash/autoreels-m182/$S; mv "$d" ~/.Trash/autoreels-m182/$S/; done
ls reels-out/*/_gate/ | sort | uniq -c | tee handoff/m182/gates_after.txt
du -sh ~/.Trash/autoreels-m182 | tee -a handoff/m182/gates_after.txt
```
Ожидается: в `reels-out/<источник>/_gate/` осталась только `m182` у всех 7. Корзину не очищать — это решает владелец.

## Шаг 6. Отчёт (на русском)
`handoff/m182/REPORT.md`:
- коммит, pytest;
- `itog.txt`;
- итог `hooks.txt` (строки «==»);
- `clause_hooks.txt`, `starts.txt`;
- вспышки;
- клипов по источникам (m176 → m182);
- вывод `grid2.py`.

`bash handoff/bin/report.sh m182 itog.txt hooks.txt clause_hooks.txt starts.txt gates_after.txt grid.csv`

Владельцу — две строки:
- «перепрогон: N клипов в _gate/m182, крючок у X из N (в m176 — Y); листы reels-out/<источник>/_gate/m182/_review.html»;
- «чистовик — reels-out/<источник>/_gate/m182 (старые гейты в Корзине), сетка — export/crosspost/grid.csv».

Статус: IMPLEMENTED, GATE PENDING.
