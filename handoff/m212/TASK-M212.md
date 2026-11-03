# TASK M212 (окно MAIN, Mac + ssh gamebox): ложная тревога целостности на gamebox — проверить и закрыть

Файлы — ветка `handoff`, папка `handoff/m212/`: `TASK-M212.md`, `m212-close.patch` (только `PLAN.md`, ложится на `main` после M210/M211).
Около 3 минут, только чтение + документация. Отчёт — только на русском.

## Зачем
Техдолг «ложная жалоба проверки целостности на gamebox для H.264» уже разобран:
- **m179:** не воспроизвелась — 41 клип `h264_vaapi` и пробное кодирование, 0 ошибок, маленьких пакетов в файлах нет;
- **M180:** проверка не удаляет клип, а оставляет `rNN.ERROR.mp4` и вывод ffmpeg в `rNN.integrity.txt`.

Осталось проверить, не появлялись ли такие файлы с тех пор, и закрыть строку в плане.

## Правила
1. Команда упала → **СТОП**: команда и последние 40 строк. Ничего не чинить.
2. Только чтение на обеих машинах. Без рендера. Ничего не удалять.
3. Если файлы `*.integrity.txt` **найдены** — патч не применять: в отчёт их пути и первые 5 строк каждого, итог «FOUND».
4. Если не найдены — применить патч, итог «CLOSED». `data/token_scale.json` не коммитить.

## Часть 1. Поиск
```bash
cd /Users/danny/Documents/autoreels
git status -sb | head -3; git log --oneline -2
bash handoff/bin/take.sh m212
{ echo "== Mac"; find reels-out -name '*.integrity.txt' 2>/dev/null; find reels-out -name '*.ERROR.mp4' 2>/dev/null | head -20
  echo "== gamebox"; ssh gamebox 'cd /mnt/data/autoreels && find reels-out -name "*.integrity.txt" 2>/dev/null; find reels-out -name "*.ERROR.mp4" 2>/dev/null | head -20'
} 2>&1 | tee handoff/m212/found.txt
grep -c "integrity.txt" handoff/m212/found.txt
```
Ожидается: `ssh` отвечает; число строк с `integrity.txt` — `0`. `.ERROR.mp4` могут быть по другим причинам (длительность звука и т. п.) — выписать, это не СТОП.

## Часть 2. Закрыть в плане (только если `integrity.txt` — 0)
```bash
cd /Users/danny/Documents/autoreels
git apply --check handoff/m212/m212-close.patch && git apply handoff/m212/m212-close.patch && echo applied
git add PLAN.md
git commit -m "Plan (M212): the gamebox integrity false alarm closed — not seen since m179 (41 h264_vaapi clips, 0 errors), M180 keeps a failing clip with ffmpeg's words, m212 found no integrity.txt on the Mac or gamebox"
git push; git log --oneline -1
git status -s | grep -v "handoff/\|data/token_scale.json" || echo "всё закоммичено"
```
Ожидается: `applied`; коммит запушен; «всё закоммичено».

## Отчёт
`handoff/m212/REPORT.md`:
```
M212 — CLOSED | FOUND
Коммит: <хэш или «нет — найдены файлы»>
integrity.txt: Mac <n>, gamebox <n>; .ERROR.mp4: Mac <n>, gamebox <n> (<причины, если видны по именам>)
```
```bash
bash handoff/bin/report.sh m212 found.txt
```
Владельцу в чат — 1 строка: «M212 — <CLOSED/FOUND>: integrity.txt — Mac <n>, gamebox <n>».
