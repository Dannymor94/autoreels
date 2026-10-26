#!/usr/bin/env bash
# M159: что ломает картинку VAAPI на gamebox (m158: r01 — зелёные блоки). Ничего в проекте не меняет.
# 1) Mac: ошибки декодирования готовых клипов m156 (без -rc_mode) и m158 (VBR), m146b (Mac) для сравнения.
# 2) gamebox: 10 с настоящего исходника IMG_6848 тем же кропом в разных режимах кодера; PSNR против несжатого
#    кадра того же фильтра (битая картинка < 25 dB, нормальная > 35 dB) + ошибки декодирования.
set -u
M=/Users/danny/Documents/autoreels; cd "$M"
echo "== 1. декодирование клипов на Mac (строк ошибок; 0 = чисто)"
for g in m146b m156 m158; do for f in reels-out/IMG_6848/_gate/$g/r0[1-3].mp4; do
  [ -f "$f" ] || continue
  e=$(ffmpeg -v error -i "$f" -f null - 2>&1 | wc -l | tr -d ' ')
  t=$(ffprobe -v error -select_streams v:0 -show_entries frame=pict_type -of csv=p=0 "$f" 2>/dev/null | sort | uniq -c | tr '\n' ' ')
  p=$(ffprobe -v error -select_streams v:0 -show_entries stream=profile,pix_fmt,has_b_frames -of csv=p=0 "$f")
  echo "  $f: ошибок $e | $p | кадры: $t"
done; done
echo "== 2. gamebox: режимы кодера на 10 с исходника (PSNR, ошибки декодирования)"
ssh gamebox 'cd /mnt/data/autoreels && SRC=$(ls inputs/IMG_6848* | head -1) && echo "исходник: $SRC" && \
VF="crop=ih*9/16:ih,scale=1080:1920" && \
flock /mnt/data/locks/heavy.lock bash -c "
run(){ n=\$1; shift; ffmpeg -hide_banner -loglevel error -y -ss 300 -t 10 -i \"$SRC\" -vaapi_device /dev/dri/renderD128 -vf \"$VF,format=nv12,hwupload\" \"\$@\" -an /tmp/m159_\$n.mp4 || { echo \"  \$n: КОДЕР ОШИБКА\"; return; }
  e=\$(ffmpeg -v error -i /tmp/m159_\$n.mp4 -f null - 2>&1 | wc -l)
  ps=\$(ffmpeg -hide_banner -i /tmp/m159_\$n.mp4 -ss 300 -t 10 -i \"$SRC\" -lavfi \"[1:v]$VF,format=yuv420p[r];[0:v]format=yuv420p[e];[e][r]psnr\" -f null - 2>&1 | grep -o \"average:[0-9.inf]*\")
  b=\$(ffprobe -v error -select_streams v:0 -show_entries stream=bit_rate,has_b_frames -of csv=p=0 /tmp/m159_\$n.mp4)
  echo \"  \$n: PSNR \$ps | ошибок декодирования \$e | битрейт,b \$b\"; }
run hevc_default  -c:v hevc_vaapi -b:v 5M
run hevc_vbr      -c:v hevc_vaapi -rc_mode VBR -b:v 5M -maxrate 5M -bufsize 10M
run hevc_vbr_bf0  -c:v hevc_vaapi -rc_mode VBR -b:v 5M -maxrate 5M -bufsize 10M -bf 0
run hevc_cbr      -c:v hevc_vaapi -rc_mode CBR -b:v 5M
run hevc_cqp      -c:v hevc_vaapi -rc_mode CQP -qp 24
run h264_vbr      -c:v h264_vaapi -rc_mode VBR -b:v 7M -maxrate 7M -bufsize 14M -profile:v high
run h264_vbr_bf0  -c:v h264_vaapi -rc_mode VBR -b:v 7M -maxrate 7M -bufsize 14M -bf 0 -profile:v high
"'
echo "== 3. те же файлы — декодирование на Mac (как у владельца)"
mkdir -p /tmp/m159 && rsync -a gamebox:/tmp/m159_*.mp4 /tmp/m159/ 2>/dev/null
for f in /tmp/m159/m159_*.mp4; do echo "  $(basename "$f"): ошибок $(ffmpeg -v error -i "$f" -f null - 2>&1 | wc -l | tr -d ' ')"; done
echo "файлы для глаз: /tmp/m159/ (открыть в QuickTime)"
