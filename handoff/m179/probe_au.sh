#!/bin/sh
# M179: what the 12-byte access unit is. Usage: sh probe_au.sh <clip.mp4>  (gamebox or Mac)
f="$1"
echo "== $f"
echo "-- ffmpeg $(ffmpeg -version | head -1 | cut -d' ' -f3)"
echo "-- integrity (copy):"; ffmpeg -v error -i "$f" -codec copy -f null - 2>&1 | head -5
echo "-- full decode errors:"; ffmpeg -v error -i "$f" -f null - 2>&1 | head -5
echo "-- small video packets (size < 64):"
ffprobe -v error -select_streams v:0 -show_entries packet=pts_time,dts_time,size,flags -of csv=p=0 "$f" | awk -F, '$3<64' | head -10
echo "-- packets: $(ffprobe -v error -select_streams v:0 -show_entries packet=size -of csv=p=0 "$f" | wc -l), frames: $(ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=nb_read_frames,nb_frames -of csv=p=0 "$f")"
echo "-- NAL units of packets under 64 bytes (and the packet before):"
ffmpeg -hide_banner -loglevel info -i "$f" -c:v copy -an -bsf:v trace_headers -f null - 2>&1 \
  | awk '/Packet: /{keep=0; split($0,a,"Packet: "); split(a[2],b," "); if (b[1]+0<64) {keep=1; print prev}; prev=$0} keep && /nal_unit_type|Packet: /' | head -30
