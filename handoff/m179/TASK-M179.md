# TASK M179 (окно MAIN, Mac + ssh gamebox): замер — ложная ошибка целостности H.264 на gamebox

Файлы — ветка `handoff`, папка `handoff/m179/`: `TASK-M179.md`, `keep_render.py`, `probe_au.sh`. Около 20 минут. **gamebox должен быть включён.** Код не меняется: сначала замер, правка — после него.

## Зачем
При рендере на gamebox (`h264_vaapi`) часть клипов падает с ошибкой:

`[ERROR] rNN: integrity check failed — missing picture in access unit with size 12`

Клип при этом удаляется. На Mac те же файлы проверка проходит: в m165 было 28 клипов, 0 ошибок.

Проверка (`local/render.py _check_integrity`) — `ffmpeg -v error -i <клип> -codec copy -f null -`, любой вывод = ошибка. Сообщение пишет разборщик H.264, когда в пакете (access unit) из 12 байт нет кадра. Нужно выяснить три вещи:
1. какой это пакет и какие в нём NAL-единицы (AUD, SEI, конец потока?);
2. на каком шаге рендера он появляется;
3. почему ffmpeg Mac молчит: другая версия.

От ответа зависит правка: убрать такой пакет при кодировании или признать сообщение безвредным по точному признаку.

## Правила
- `sudo` не нужен.
- Рендер на gamebox — под общим замком, чужую работу не обрывать.
- Гейты m176/m163/m157 не трогать: пишем в `_gate/m179diag`.
- Шаг упал → СТОП с выводом.

## Шаг 1. Обычный удалённый рендер — какие клипы падают
```bash
cd /Users/danny/Documents/autoreels; git pull -q; git log --oneline -1; bash handoff/bin/take.sh m179; mkdir -p handoff/m179
ssh gamebox 'ffmpeg -version | head -1; uptime' | tee handoff/m179/gb.txt
.venv/bin/python -m autoreels render --manifest reviews/prew_isaev_anna_m176.review.json --reels 1-10 --gate m179diag --remote 2>&1 | grep -E "ERROR|готово|клип " | tee handoff/m179/remote.txt
```
Ожидается: строки рендера, среди них, возможно, `integrity check failed`. Если ни одной ошибки — повторить для `reviews/prew_isaev_danny_m176.review.json --reels 1-14`. Ошибок нет и там — в отчёт, шаги 2–3 на любом одном клипе.

## Шаг 2. Те же клипы с сохранением файла (на gamebox)
```bash
scp handoff/m179/keep_render.py handoff/m179/probe_au.sh gamebox:/mnt/data/autoreels/
ssh gamebox 'cd /mnt/data/autoreels && flock /mnt/data/locks/heavy.lock .venv/bin/python keep_render.py --manifest reviews/prew_isaev_anna_m176.review.json --reels 1-10 --gate m179keep --encoder h264_vaapi --profile h264 2>&1 | grep -E "INTEGRITY|ERROR"' | tee handoff/m179/keep.txt
```
(Если в шаге 1 ошибки были у `prew_isaev_danny` — взять его.) Ожидается: строки `INTEGRITY …` с файлами, `INTEGRITY total: N`.

## Шаг 3. Что за пакет
```bash
F=$(grep -oE "INTEGRITY [^:]+\.mp4" handoff/m179/keep.txt | head -2 | sed 's/INTEGRITY //')
for f in $F; do ssh gamebox "cd /mnt/data/autoreels && sh probe_au.sh '$f'"; done 2>&1 | tee handoff/m179/probe_gamebox.txt
mkdir -p handoff/m179/clips; for f in $F; do scp "gamebox:/mnt/data/autoreels/$f" handoff/m179/clips/; done
for f in handoff/m179/clips/*.mp4; do sh handoff/m179/probe_au.sh "$f"; done 2>&1 | tee handoff/m179/probe_mac.txt
```
Ожидается:
- в `probe_gamebox.txt`: сообщение integrity, маленький пакет (размер, время — в конце файла или нет), его NAL-единицы;
- в `probe_mac.txt`: тот же файл — есть ли сообщение на Mac, полное декодирование без ошибок?

## Шаг 4. На каком шаге появляется
Скрипт рендера пишет клип в несколько проходов: склейка окон, затем может быть звук перехода («whoosh») и концовка. Проверить промежуточный файл:
```bash
ssh gamebox 'cd /mnt/data/autoreels && ls reels-out/prew_isaev_anna/_gate/m179keep/ | head -30'
ssh gamebox 'cd /mnt/data/autoreels && ffmpeg -hide_banner -v error -f lavfi -i testsrc2=s=1080x1920:r=30 -t 5 -vaapi_device /dev/dri/renderD128 -vf format=nv12,hwupload -c:v h264_vaapi -b:v 5M /tmp/m179_raw.mp4 && ffmpeg -v error -i /tmp/m179_raw.mp4 -codec copy -f null - 2>&1 | head -3; echo "raw rc=$?"; ffprobe -v error -select_streams v:0 -show_entries packet=size -of csv=p=0 /tmp/m179_raw.mp4 | awk "\$1<64" | head'
```
Если в папке есть промежуточные файлы, прогнать `probe_au.sh` и на них. Пробное кодирование testsrc показывает, даёт ли маленький пакет уже сам `h264_vaapi`. Это не СТОП.

## Шаг 5. Отчёт
`handoff/m179/REPORT.md`: `gb.txt`, `remote.txt`, `keep.txt`, `probe_gamebox.txt`, `probe_mac.txt`, вывод шага 4, версии ffmpeg обеих машин.
`bash handoff/bin/report.sh m179 gb.txt remote.txt keep.txt probe_gamebox.txt probe_mac.txt`

Уборка:
```bash
ssh gamebox 'cd /mnt/data/autoreels && rm -rf reels-out/prew_isaev_anna/_gate/m179keep reels-out/prew_isaev_danny/_gate/m179keep keep_render.py probe_au.sh /tmp/m179_raw.mp4'
```
Локальные `_gate/m179diag` — в Корзину.

Владельцу — одна строка: «замер готов, ассистент делает правку».

Статус: замер.
