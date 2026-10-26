#!/usr/bin/env bash
# M155: можно ли рендерить на gamebox (Ubuntu, Ryzen 7, RX 580). Только смотрит; файлов в проекте не меняет.
# Пробное кодирование 10 с синтетики — только если общий замок свободен (озвучку книги и llama-server не трогаем).
set -u
H=gamebox; L=/mnt/data/locks/heavy.lock
say() { printf '\n== %s\n' "$*"; }
say "система"
ssh $H 'lsb_release -ds 2>/dev/null; uname -r; nproc; free -g | head -2; df -h ~ /mnt/data 2>/dev/null | tail -n +1'
say "ffmpeg и libass"
ssh $H 'command -v ffmpeg && ffmpeg -hide_banner -version | head -1; ffmpeg -hide_banner -filters 2>/dev/null | grep -wE "ass|subtitles" | head -2 || echo "фильтра ass НЕТ"'
say "кодеры"
ssh $H 'ffmpeg -hide_banner -encoders 2>/dev/null | grep -E "hevc_vaapi|h264_vaapi|hevc_amf|h264_amf|libx265|libx264" || echo "нет"'
say "GPU (VAAPI)"
ssh $H 'ls -l /dev/dri 2>/dev/null; groups; command -v vainfo >/dev/null && vainfo 2>&1 | grep -E "Driver|HEVC|H264" | head -8 || echo "vainfo не установлен"'
say "python, git, проект"
ssh $H 'python3 --version; git --version; ls -d ~/autoreels ~/Documents/autoreels 2>/dev/null || echo "проекта нет"'
say "занятость (замок, llama-server, озвучка)"
ssh $H "flock -n $L true && echo 'замок свободен' || echo 'ЗАМОК ЗАНЯТ'; systemctl is-active llama-server; pgrep -fl 'run.sh|synth' | head -3 || true"
say "пробное кодирование 1080x1920, 10 с (только при свободном замке)"
ssh $H "flock -n $L sh -c '
  t(){ s=\$(date +%s.%N); \"\$@\" >/tmp/m155.log 2>&1; rc=\$?; e=\$(date +%s.%N); echo \"rc=\$rc \$(echo \"\$e - \$s\" | bc) с\"; [ \$rc = 0 ] || tail -3 /tmp/m155.log; }
  echo -n \"hevc_vaapi 5M: \"; t ffmpeg -hide_banner -y -f lavfi -i testsrc2=s=1080x1920:r=30 -t 10 -vaapi_device /dev/dri/renderD128 -vf format=nv12,hwupload -c:v hevc_vaapi -b:v 5M -f null -
  echo -n \"h264_vaapi 8M: \"; t ffmpeg -hide_banner -y -f lavfi -i testsrc2=s=1080x1920:r=30 -t 10 -vaapi_device /dev/dri/renderD128 -vf format=nv12,hwupload -c:v h264_vaapi -b:v 8M -f null -
  echo -n \"libx265 medium 5M: \"; t ffmpeg -hide_banner -y -f lavfi -i testsrc2=s=1080x1920:r=30 -t 10 -c:v libx265 -preset medium -b:v 5M -f null -
  echo -n \"libx264 medium 8M: \"; t ffmpeg -hide_banner -y -f lavfi -i testsrc2=s=1080x1920:r=30 -t 10 -c:v libx264 -preset medium -b:v 8M -f null -
' || echo 'замок занят — кодирование пропущено'"
say "сеть Mac → gamebox (500 МБ)"
s=$(date +%s); dd if=/dev/zero bs=1m count=500 2>/dev/null | ssh $H 'cat > /dev/null'; e=$(date +%s); d=$((e - s)); [ $d -gt 0 ] && echo "$((500 / d)) МБ/с ($d с)" || echo "< 1 с"
say "то же на Mac для сравнения (videotoolbox)"
s=$(date +%s); ffmpeg -hide_banner -y -f lavfi -i testsrc2=s=1080x1920:r=30 -t 10 -c:v hevc_videotoolbox -b:v 5M -f null - >/dev/null 2>&1; echo "hevc_videotoolbox: rc=$? $(( $(date +%s) - s )) с"
