# TASK M158 (ВТОРОЙ агент, параллельно с m157; Mac + ssh gamebox): gamebox — битрейт и лица как на Mac

Файлы — ветка `handoff`, папка `handoff/m158/`: `TASK-M158.md`, `m158-vaapi-vbr.patch`. Около 20 минут.

## Зачем
По m156 рендер на видеокарте gamebox работает, длительности клипов совпали с Mac до миллисекунды. Два расхождения:
1. **Битрейт 7,0 Мбит/с против 4,9 у Mac** при том же профиле. Без режима скорости VAAPI на RX 580 кодирует с постоянным QP и не слушает `-b:v`/`-maxrate`. Патч: для `*_vaapi` добавляется `-rc_mode VBR`, остальные кодеры не меняются (тест).
2. **Лица не искались**: «нет OpenCV», рамка встала по источнику, а не по лицу, и картинка не та, что на Mac. `opencv-python-headless` есть в зависимостях проекта, значит установка в venv на gamebox прошла не полностью.

## Правила
Как в m156:
- основная папка Mac — только чтение (там идёт m157);
- патч, тесты и коммит — в своём worktree;
- на gamebox — всё в `/mnt/data/autoreels`, рендер под `flock /mnt/data/locks/heavy.lock`;
- `sudo` не нужен;
- шаг упал → **СТОП** с выводом;
- отчёт — `TMPDIR=$(mktemp -d) bash handoff/bin/report.sh …`.

## Шаг 1. Патч, тесты, коммит (worktree)
```bash
M=/Users/danny/Documents/autoreels; W=/Users/danny/Documents/autoreels-m158
cd "$M" && bash handoff/bin/take.sh m158 && git fetch -q origin && git worktree add -q --detach "$W" origin/main && cd "$W"
git apply --check "$M/handoff/m158/m158-vaapi-vbr.patch" && git apply "$M/handoff/m158/m158-vaapi-vbr.patch" && echo applied
python3.13 -m venv .venv && .venv/bin/pip install -q -e ".[dev]" && .venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -3
git add src tests docs && git commit -q -m "Render (M158): VAAPI gets -rc_mode VBR (RX 580 ignored the profile bitrate: 7.0 vs 4.9 Mbit/s on m156)" && git push origin HEAD:main && git log --oneline -1
```
Ожидается: `applied`; pytest — все прошли; push прошёл. Если main ушёл вперёд — `git pull --rebase origin main` и снова push.

## Шаг 2. gamebox: OpenCV в venv
```bash
ssh gamebox 'cd /mnt/data/autoreels && .venv/bin/python -c "import cv2; print(\"cv2\", cv2.__version__)" 2>&1 | tail -1'
ssh gamebox 'cd /mnt/data/autoreels && .venv/bin/pip install "opencv-python-headless>=4.8,<5" 2>&1 | tail -3; .venv/bin/python -c "import cv2; print(\"cv2\", cv2.__version__)"'
ssh gamebox 'cd /mnt/data/autoreels && .venv/bin/pip check 2>&1 | tail -5'
```
Ожидается строка `cv2 4.x`. Если колеса для Python 3.14 нет и pip собирает из исходников с ошибкой — СТОП с выводом pip. Решим: Python 3.13 через `uv` в `/mnt/data`.

`pip check` назовёт и другие недостающие зависимости. Их доставить тем же `pip install`, имена — в отчёт.

## Шаг 3. Код на gamebox и рендер тех же трёх клипов
```bash
rsync -a --delete --exclude .git --exclude .venv --exclude handoff --exclude inputs --exclude reels-out --exclude data \
  --exclude reviews --exclude transcripts --exclude config/render.local.yaml "$W/" gamebox:/mnt/data/autoreels/
ssh gamebox 'cd /mnt/data/autoreels && s=$(date +%s); flock /mnt/data/locks/heavy.lock .venv/bin/python -m autoreels render --manifest reviews/IMG_6848_m146b.review.json --reels 1-3 --gate m158 --encoder hevc_vaapi 2>&1 | grep -E "кадр|лицо|ERROR|готово"; echo "$(( $(date +%s) - s )) с"' | tee "$M/handoff/m158/render.txt"
cd "$M"; mkdir -p reels-out/IMG_6848/_gate/m158 && rsync -a gamebox:/mnt/data/autoreels/reels-out/IMG_6848/_gate/m158/ reels-out/IMG_6848/_gate/m158/
for g in m158 m146b; do for f in reels-out/IMG_6848/_gate/$g/r0[1-3].mp4; do echo "$f $(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,bit_rate -show_entries format=duration -of csv=p=0 "$f" | tr '\n' ' ')"; done; done | tee handoff/m158/probe.txt
```
Ожидается:
- в `render.txt` нет строк «лицо не искалось», есть строки рамки по лицу, как на Mac;
- `[ERROR]` нет;
- в `probe.txt` битрейт m158 около 5 Мбит/с (не 7);
- длительности — как у m146b.

## Шаг 4. Отчёт
`handoff/m158/REPORT.md`: коммит, pytest, версия cv2, `pip check`, `render.txt`, `probe.txt`, секунд на 3 клипа.
`TMPDIR=$(mktemp -d) bash handoff/bin/report.sh m158 render.txt probe.txt`; затем `git worktree remove "$W"`.
Владельцу — одна строка: «gamebox: битрейт X против 4,9 у Mac, лица находятся; сравни reels-out/IMG_6848/_gate/m158 и _gate/m146b — кадр и субтитры одинаковые?».

Статус: IMPLEMENTED, GATE PENDING.
