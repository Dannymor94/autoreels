# TASK M155 (можно параллельным окном, Mac): можно ли выносить рендер на gamebox

Владелец: «можем вынести рендер на ПК — там Ubuntu server, доступ ssh gamebox». Сначала замер, кода нет. Около 5 минут.
На gamebox ничего не ставить и не менять. Озвучку книги и llama-server не трогать. Пробное кодирование идёт только при свободном общем замке, иначе пропускается.
Параллельно с m154 можно: скрипт только читает и кодирует 10 с синтетики в `/dev/null`. Если запускаешь параллельным агентом — отчёт через `TMPDIR=$(mktemp -d) bash handoff/bin/report.sh m155 probe.txt`.

## Шаг 1
```bash
cd /Users/danny/Documents/autoreels; bash handoff/bin/take.sh m155
bash handoff/m155/probe.sh 2>&1 | tee handoff/m155/probe.txt
```
Ожидается: все разделы заполнены. Ошибка ssh — СТОП с выводом.

## Шаг 2. Отчёт
`handoff/m155/REPORT.md` = `probe.txt` целиком + три строки: есть ли фильтр `ass`; какой кодер быстрее всего (секунды на 10 с видео против videotoolbox на Mac); скорость сети, МБ/с.
`bash handoff/bin/report.sh m155 probe.txt`
