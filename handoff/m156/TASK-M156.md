# TASK M156 (ВТОРОЙ агент, параллельно с m154; Mac + ssh gamebox): рендер на видеокарте gamebox (VAAPI)

Файлы — ветка `handoff`, папка `handoff/m156/`: `TASK-M156.md`, `m156-vaapi.patch`. Около 40 минут.

## Зачем
Владелец: «видеокарта на gamebox пустая — нужно её использовать; пусть агент скачает и установит всё, что надо». На Linux у RX 580 нет AMF, зато есть VAAPI (драйвер Mesa): кодеры `hevc_vaapi` / `h264_vaapi`.

Патч:
- каждая команда ffmpeg с кодером `*_vaapi` получает устройство `-vaapi_device`, загрузку кадров в GPU в конце видеофильтра и не получает выходного `-pix_fmt` (`local/render.py _hw_argv`);
- другие кодеры — команда без изменений (инвариант 8, тест);
- тесты `tests/test_m156_vaapi.py` (10);
- `docs/GAMEBOX.md`, REEL_SPEC, CLAUDE.md («Машины»).

**Владелец разрешил ставить пакеты на gamebox для рендера** (2026-10-26). Только их: ffmpeg, драйвер VAAPI, python-venv, шрифты. Озвучку книги и llama-server не трогать. Всё тяжёлое на gamebox — под общим замком `flock /mnt/data/locks/heavy.lock`: занят — ждать, чужую работу не обрывать.

## Правила
1. Шаг упал или не совпал с «Ожидается» → **СТОП**: шаг, команда, последние 40 строк.
2. **Параллельно идёт m154 (основной агент):** `arl auto` рендерит в `reels-out/` основной папки. Поэтому:
   - в основной папке `/Users/danny/Documents/autoreels` **не менять отслеживаемые файлы, не запускать pytest и рендер**;
   - патч, тесты и коммит — в своём worktree `../autoreels-m156`: guard pytest смотрит только за своим корнем;
   - из основной папки только читаются данные (`reviews/`, `transcripts/`, `calibrations/`, `profiles/`, `data/models/`) и берётся исходник IMG_6848;
   - отчёт — `TMPDIR=$(mktemp -d) bash handoff/bin/report.sh …`.
3. Ключи и пароли не печатать. На gamebox `sudo` — только `sudo -n` (без пароля). Пароль нужен → СТОП, владельцу команду для `ssh -t gamebox`.

## Шаг 1. gamebox: пакеты, видеокарта, проба
```bash
cd /Users/danny/Documents/autoreels; bash handoff/bin/take.sh m156; mkdir -p handoff/m156
ssh gamebox 'lsb_release -ds; python3 --version; sudo -n true && echo "sudo без пароля: да" || echo "sudo без пароля: НЕТ"' | tee handoff/m156/gb.txt
```
- **sudo без пароля: да:**
  ```bash
  ssh gamebox 'sudo -n apt-get update -qq && sudo -n DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ffmpeg mesa-va-drivers vainfo python3-venv python3-pip rsync fonts-liberation && sudo -n usermod -aG render,video "$USER" && echo установлено' 2>&1 | tail -3 | tee -a handoff/m156/gb.txt
  ```
- **НЕТ:** СТОП. Владельцу одной строкой:
  `ssh -t gamebox 'sudo apt-get update && sudo apt-get install -y ffmpeg mesa-va-drivers vainfo python3-venv python3-pip rsync fonts-liberation && sudo usermod -aG render,video $USER'`

  После его «готово» — дальше.

По замеру m155 почти всё уже стоит (Ubuntu 26.04, ffmpeg 8 с `ass`, Mesa для RX 580, Python 3.14, пользователь в группе `render`): apt поставит недостающее или ничего.

Проба (новая сессия ssh, чтобы группа `render` подхватилась):
```bash
ssh gamebox 'vainfo 2>&1 | grep -E "Driver version|HEVC|H264" | head -10; ffmpeg -hide_banner -filters 2>/dev/null | grep -w ass | head -1; ffmpeg -hide_banner -encoders 2>/dev/null | grep vaapi' | tee -a handoff/m156/gb.txt
ssh gamebox 'flock /mnt/data/locks/heavy.lock sh -c "for c in hevc_vaapi h264_vaapi; do s=\$(date +%s.%N); ffmpeg -hide_banner -loglevel error -y -f lavfi -i testsrc2=s=1080x1920:r=30 -t 10 -vaapi_device /dev/dri/renderD128 -vf format=nv12,hwupload -c:v \$c -b:v 5M -f null - && echo \"\$c: \$(python3 -c \"import time;print(round(time.time()-\$s,1))\") с на 10 с видео\" || echo \"\$c: ОШИБКА\"; done"' | tee -a handoff/m156/gb.txt
```
Ожидается:
- в `vainfo` есть `HEVC…` и `H264…` с `VAEntrypointEncSlice` (в m155 строки HEVC обрезал `head -8`, теперь `head -10` после фильтра — если опять не видно, `vainfo | grep -c EncSlice`);
- есть фильтр `ass`;
- в списке кодеров есть `hevc_vaapi`;
- оба пробных кодирования проходят, по секундам.

`hevc_vaapi: ОШИБКА` при рабочем `h264_vaapi` — не СТОП: дальше `h264_vaapi`.

## Шаг 2. Патч, тесты, коммит — в своём worktree
```bash
M=/Users/danny/Documents/autoreels; W=/Users/danny/Documents/autoreels-m156
cd "$M" && git fetch -q origin && git worktree add -q --detach "$W" origin/main && cd "$W" && git log --oneline -1
git apply --check "$M/handoff/m156/m156-vaapi.patch" && git apply "$M/handoff/m156/m156-vaapi.patch" && echo applied
"$M/.venv/bin/python" -m pytest -q -p no:cacheprovider 2>&1 | tail -3
git add src tests config docs CLAUDE.md && git commit -q -m "Render (M156): VAAPI encoders (gamebox RX 580) — device, GPU upload at the end of the video filter, no output pix_fmt; other encoders unchanged" && git push origin HEAD:main && git log --oneline -1
```
pytest берёт пакет из `.venv` основной папки, а он установлен editable из основной папки. Поэтому сначала проверить: `"$M/.venv/bin/python" -c "import autoreels,sys;print(autoreels.__file__)"`. Если путь указывает на основную папку (без патча), тесты VAAPI упадут на импорте. Тогда — отдельный venv в worktree: `python3.13 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"` и `.venv/bin/python -m pytest -q`.

Ожидается: `applied`; pytest — все прошли; `git push origin HEAD:main` прошёл. main за это время мог уйти вперёд, тогда push отказан: `git pull --rebase origin main` в worktree и снова push. Основному агенту после m154 — обычный `git pull`.

## Шаг 3. Проект на gamebox и пробный рендер трёх клипов
**Проект — на HDD: `/mnt/data/autoreels`** (владелец; SSD системный, там 157 ГБ, исходники и клипы туда не класть). venv, исходники и клипы — там же. Нет прав на `/mnt/data` (mkdir упал) → СТОП, владельцу: `ssh -t gamebox 'sudo mkdir -p /mnt/data/autoreels && sudo chown $USER: /mnt/data/autoreels'`.
Код — rsync из worktree (с патчем), данные — из основной папки (только чтение). Репозиторий для gamebox может быть закрыт, поэтому git там не нужен. Гигабайтные папки не копируются, исходник — только IMG_6848.
```bash
M=/Users/danny/Documents/autoreels; W=/Users/danny/Documents/autoreels-m156; cd "$M"
ssh gamebox 'mkdir -p ~/.local/share/fonts /mnt/data/autoreels/inputs && ls -ld /mnt/data/autoreels'
rsync -a --delete --exclude .git --exclude .venv --exclude handoff --exclude inputs --exclude reels-out --exclude data \
  --exclude reviews --exclude transcripts --exclude config/render.local.yaml "$W/" gamebox:/mnt/data/autoreels/
rsync -aR reviews/IMG_6848_m146b.review.json transcripts/IMG_6848.* calibrations profiles data/models gamebox:/mnt/data/autoreels/ 2>&1 | tail -2
scp /System/Library/Fonts/Supplemental/Arial*.ttf gamebox:.local/share/fonts/ && ssh gamebox 'fc-cache -f >/dev/null; fc-match Arial'
F=$(.venv/bin/python -c "
import json; from pathlib import Path; from autoreels.core.models import Manifest; from autoreels.local.render import resolve_source
m = Manifest.model_validate_json(Path('reviews/IMG_6848_m146b.review.json').read_text()); print(resolve_source(m, 'inputs'))")
echo "исходник: $F"; rsync -a --progress "$F" gamebox:/mnt/data/autoreels/inputs/ | tail -1
ssh gamebox 'cd /mnt/data/autoreels && python3 -m venv .venv && .venv/bin/pip install -q -e . 2>&1 | tail -3; printf "role: both\n" > config/render.local.yaml; .venv/bin/python -m autoreels doctor 2>&1 | tail -5'
ssh gamebox 'cd /mnt/data/autoreels && s=$(date +%s); flock /mnt/data/locks/heavy.lock .venv/bin/python -m autoreels render --manifest reviews/IMG_6848_m146b.review.json --reels 1-3 --gate m156 --encoder hevc_vaapi 2>&1 | tail -8; echo "$(( $(date +%s) - s )) с (с ожиданием замка)"' | tee handoff/m156/render.txt
mkdir -p reels-out/IMG_6848/_gate/m156 && rsync -a gamebox:/mnt/data/autoreels/reels-out/IMG_6848/_gate/m156/ reels-out/IMG_6848/_gate/m156/
for f in reels-out/IMG_6848/_gate/m156/r0[1-3]*.mp4 reels-out/IMG_6848/_gate/m146b/r0[1-3]*.mp4; do echo "$f $(ffprobe -v error -show_entries stream=codec_name,width,height,bit_rate -show_entries format=duration -of csv=p=0 "$f" | tr '\n' ' ')"; done | tee handoff/m156/probe.txt
```
pip на Python 3.14 не нашёл колёс какого-то пакета (ошибка сборки) — СТОП с выводом pip: решим, ставить ли отдельный Python.

Ожидается:
- `fc-match Arial` → Arial;
- doctor без ошибок ffmpeg;
- рендер трёх клипов без `[ERROR]`, строка `N с`;
- в `probe.txt` у m156 `hevc 1080 1920` и та же длительность, что у m146b (±0.05 с).

Если рендер ушёл на запасной кодер (в выводе «fallback» или кодер не vaapi) — в отчёт, это не успех VAAPI.

## Шаг 4. Отчёт
`handoff/m156/REPORT.md`:
- `gb.txt`, `render.txt`, `probe.txt` целиком;
- коммит, pytest;
- скорость: секунд на клип, gamebox VAAPI против Mac (из m155, если он сделан).

`TMPDIR=$(mktemp -d) bash handoff/bin/report.sh m156 gb.txt render.txt probe.txt`
Worktree удалить после отчёта: `cd /Users/danny/Documents/autoreels && git worktree remove /Users/danny/Documents/autoreels-m156`.

Владельцу — две строки:
- «gamebox рендерит на видеокарте: N с на клип (Mac — M с)»;
- «сравни reels-out/IMG_6848/_gate/m156 (gamebox) и _gate/m146b (Mac) — картинка и субтитры те же?».

Статус: IMPLEMENTED, GATE PENDING.
