# TASK M180 (окно MAIN, Mac): проверка целостности не удаляет клип

Файлы — ветка `handoff`, папка `handoff/m180/`: `TASK-M180.md`, `m180-integrity.patch`. Около 5 минут, без рендера.

## Зачем
Замер m179:
- 41 клип `h264_vaapi` и пробное кодирование дали 0 сообщений «missing picture in access unit with size 12»;
- маленьких пакетов в файлах нет.

Объяснение в отчёте m179 («AUD + EOS, 12 байт») — догадка: такой пакет ни разу не нашли. Поэтому сообщение не заглушается: правило по догадке спрятало бы настоящую порчу, если она будет.

Причина, по которой разобрать m165 было нельзя: проверка **удаляла** клип.

Патч:
- клип, не прошедший проверку, остаётся как `rNN.ERROR.mp4`, как при любой другой ошибке клипа (M47);
- полный вывод ffmpeg — в `rNN.integrity.txt` рядом;
- остальные клипы как раньше;
- тест `test_integrity_failure_keeps_the_clip_as_error_file` в `tests/test_render.py`; заметка в `docs/GAMEBOX.md`.

Если сообщение вернётся, файл будет на месте: разобрать его (`handoff/m179/probe_au.sh`) и делать правку по нему.

## Шаги
```bash
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; pgrep -fl "autoreels" || echo "не запущен"; bash handoff/bin/take.sh m180
git apply --check handoff/m180/m180-integrity.patch && git apply handoff/m180/m180-integrity.patch && echo applied
.venv/bin/python -m pytest -q 2>&1 | tail -3
git add src tests docs && git commit -m "Render (M180): a clip failing the integrity check is kept as .ERROR.mp4 with ffmpeg's words in <rid>.integrity.txt, not deleted (m179: m165's gamebox message could not be examined)" && git push && git log --oneline -1
```
Ожидается: `applied`. pytest: всё прошло, кроме известных пяти; `test_menu_bash` под нагрузкой иногда падает — тогда прогнать его отдельно. Коммит запушен.

## Отчёт
`handoff/m180/REPORT.md`: коммит, pytest. `bash handoff/bin/report.sh m180`. Владельцу — одна строка: «проверка целостности больше не удаляет клипы (коммит …)».

Статус: IMPLEMENTED.
