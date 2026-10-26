# TASK M160 (второй агент, Mac + ssh gamebox): зелёные блоки — где именно ломается

Замер m159:
- **кодер исправен**: семь режимов на 10 с исходника — PSNR 35–36 dB, 0 ошибок;
- **в настоящих клипах gamebox есть ошибки декодирования** (m156 r02 — 1, m158 r01 — 2);
- **ключевых кадров в клипах gamebox в 10 раз меньше**: 37 I-кадров на 4334 против 362 у Mac. VAAPI-кодеру не задан интервал ключевых кадров (`-g` ставится только софтверным x26x), а плеер, потерявший опорный кадр, показывает зелень до следующего ключевого.

Пробы m159 отличаются от рендера: нет тега `hvc1`, нет склеек и пост-проходов (хвост, концовка), нет субтитров. Задача — найти, что из этого ломает. Кода нет, около 15 минут.

## Правила
- Проект не менять. На gamebox — только `/tmp/m160*` и рендер в `--gate m160*` под замком.
- Шаг упал → **СТОП**.
- Отчёт: `TMPDIR=$(mktemp -d) bash handoff/bin/report.sh m160 diag.txt`.

## Шаг 1. Сами ошибки и где они
```bash
cd /Users/danny/Documents/autoreels; bash handoff/bin/take.sh m160
for f in reels-out/IMG_6848/_gate/m158/r01.mp4 reels-out/IMG_6848/_gate/m156/r02.mp4; do
  echo "== $f"; ffmpeg -v error -i "$f" -f null - 2>&1 | head -5
  ffprobe -v error -select_streams v:0 -show_entries frame=pts_time,pict_type,key_frame -of csv=p=0 "$f" | awk -F, '$3=="I"||$2==1{print}' | head -8
done 2>&1 | tee handoff/m160/diag.txt
```

## Шаг 2. Перепаковка без перекодирования (владельцу — в QuickTime)
```bash
mkdir -p /tmp/m160; F=reels-out/IMG_6848/_gate/m158/r01.mp4
ffmpeg -v error -y -i "$F" -c copy -tag:v hev1 /tmp/m160/r01_hev1.mp4
ffmpeg -v error -y -i "$F" -c copy -tag:v hvc1 -movflags +faststart /tmp/m160/r01_hvc1_remux.mp4
ffmpeg -v error -y -ss 5 -i "$F" -c copy -tag:v hvc1 /tmp/m160/r01_from5s.mp4
ls -la /tmp/m160 | tee -a handoff/m160/diag.txt
```

## Шаг 3. Тот же клип на gamebox — три варианта рендера
```bash
ssh gamebox 'cd /mnt/data/autoreels && for v in "m160h264 --encoder h264_vaapi --profile h264" "m160hevc --encoder hevc_vaapi --profile hevc"; do set -- $v; g=$1; shift;
  flock /mnt/data/locks/heavy.lock .venv/bin/python -m autoreels render --manifest reviews/IMG_6848_m146b.review.json --reels 1 --gate $g "$@" 2>&1 | grep -E "ERROR|готово|fallback";
  f=reels-out/IMG_6848/_gate/$g/r01.mp4; echo "$g: ошибок $(ffmpeg -v error -i $f -f null - 2>&1 | wc -l), I-кадров $(ffprobe -v error -select_streams v:0 -show_entries frame=pict_type -of csv=p=0 $f | grep -c I)"; done' | tee -a handoff/m160/diag.txt
for g in m160h264 m160hevc; do mkdir -p reels-out/IMG_6848/_gate/$g && rsync -a gamebox:/mnt/data/autoreels/reels-out/IMG_6848/_gate/$g/ reels-out/IMG_6848/_gate/$g/; done
```
Ожидается: оба рендера без `[ERROR]`, по строке «ошибок N, I-кадров M».

## Шаг 4. Отчёт
`handoff/m160/REPORT.md` = `diag.txt` + 2 строки вывода.

Владельцу — открыть в QuickTime и сказать, где нормальная картинка:
- `/tmp/m160/r01_hev1.mp4`, `r01_hvc1_remux.mp4`, `r01_from5s.mp4` (тот же поток m158, только перепакован);
- `reels-out/IMG_6848/_gate/m160h264/r01.mp4` (H.264 на видеокарте);
- `reels-out/IMG_6848/_gate/m160hevc/r01.mp4` (HEVC заново).
