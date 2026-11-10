# TASK M218 (окно MAIN, Mac): закрыть висящие хвосты плана

**Ложится на:** `main` после M217 (`98dbfa9`). **Файлы:** `handoff/m218/` — `TASK-M218.md`, `m218-close-tails.patch`.
**Время:** ~3 минуты. Только `PLAN.md`: кода, конфигов и тестов не трогает. **Отчёт — только на русском.**

## Зачем
Владелец, 2026-11-10: «закрывать все хвосты». В плане числились три незакрытых пункта. Ассистент сверил каждый по репозиторию.

1. **Ветка `m16-score` «ждёт слияния»** с октября. Сверка: отстала от `main` на 359 коммитов; её датасет блоков беднее (9 строк против 25, 10 против 18, нет поля `text`); оценок владельца в ней 127 против 183 в `main`; схема под старую нарезку с отпечатками сегментации. Сам путь — оценка блоков ручной разметки отдельным вызовом модели — заменён автомонтажом по карте мыслей (M52–M209). Брать нечего: ни кода, ни данных.
2. **Границы блоков по карте речи** (M1.8, пункт 5) — числились «отложен», хотя замер M134 решение уже дал: по слышимым паузам совпали бы 13 границ из 72 и 19 из 92, а нумерация `B.k` сломала бы отпечатки разметки владельца, карты и черновики. Это решение, а не отложенная работа.
3. **PostgreSQL live-тест** — числился отдельным долгом, хотя относится к отложенной архитектуре масштабирования.

## Что вносит патч (`PLAN.md`)
- Этап 4 — «❌ ЗАКРЫТ (ветка `m16-score` не вливается, M218)» с цифрами сверки; ветка остаётся в репозитории как история, **не сливается и не удаляется**.
- Пункт 5 M1.8 — «❌ закрыт решением по замеру (M134, подтверждено 2026-11-10)».
- PostgreSQL — отнесён к отложенной архитектуре, отдельным долгом не числится.

## Правила
1. Любая строка `FAIL: …` или упавшая команда → **СТОП**: команда и последние 40 строк. Ничего не чинить.
2. Ничего, кроме `PLAN.md`. Ветку `m16-score` **не трогать**: не сливать, не удалять. Без рендера и без `arl auto`.
3. `data/token_scale.json` меняется сам авто-калибровкой: не коммитить и из подсчётов исключать. Неотслеживаемые файлы (манифесты, `inputs/`) — тоже не трогать и в счёт не брать.
4. Итог — «DOCUMENTED».

## Часть 1. Патч и коммит
```bash
cd /Users/danny/Documents/autoreels
bash handoff/bin/take.sh m218
base=$(git log --format=%h -1); test "$base" = "98dbfa9" && echo "OK база" || echo "FAIL: база $base, нужна 98dbfa9 (M217)"
git apply --check handoff/m218/m218-close-tails.patch && git apply handoff/m218/m218-close-tails.patch && echo "OK патч" || echo "FAIL: патч не лёг"
n=$(git diff --name-only | grep -v "^data/token_scale.json$" | grep -cv "^$")
test "$n" = 1 && echo "OK один файл" || { echo "FAIL: изменено файлов $n:"; git diff --name-only | grep -v "^data/token_scale.json$"; }
left=$(grep -c "ждёт слияния\|отложенный долг" PLAN.md)
test "$left" = 0 && echo "OK хвостов нет" || { echo "FAIL: осталось $left"; grep -n "ждёт слияния\|отложенный долг" PLAN.md; }
git add PLAN.md
git commit -q -m "Plan (M218): the three stale items closed — the m16-score branch is not merged (359 commits behind, its dataset poorer than main's: 127 owner scores against 183, no text field, the old segmentation schema; the path itself replaced by the autocut over the thought map), the block borders by the speech map closed by the M134 measurement, the PostgreSQL test folded into the deferred scaling architecture"
git push -q && echo "OK запушено" || echo "FAIL: push"
git log --oneline -1
dirty=$(git status -s | grep -v "^??" | grep -v "data/token_scale.json" | wc -l | tr -d " ")
test "$dirty" = 0 && echo "OK отслеживаемое закоммичено" || { echo "FAIL: осталось $dirty"; git status -s | grep -v "^??" | grep -v "data/token_scale.json"; }
```
Ожидается: шесть строк `OK`. Неотслеживаемые файлы (`??`) в счёт не идут — это прогоны владельца.

## Часть 2. Ветка цела
```bash
cd /Users/danny/Documents/autoreels
git ls-remote --heads origin m16-score | grep -q m16-score && echo "OK ветка на месте" || echo "FAIL: ветки m16-score нет"
```

## Отчёт
`handoff/m218/REPORT.md`:
```
M218 — DOCUMENTED
Коммит: <хэш>
Проверки: <все OK / какие FAIL>
```
```bash
bash handoff/bin/report.sh m218
```
Владельцу в чат — 1 строка: «M218 — DOCUMENTED, коммит <хэш>: хвосты плана закрыты, ветка m16-score оставлена как история».
