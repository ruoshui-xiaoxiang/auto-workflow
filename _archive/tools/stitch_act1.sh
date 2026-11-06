#!/usr/bin/env bash
# 把 U01–U12 当前最优条拼成整幕粗剪（统一 1024x576 / 24fps，直拼不加转场）。
set -euo pipefail
FF="D:/AIWorkflow/tools/ffmpeg.exe"
J1="C:/Temp/fanxing_runs/canvas_job_20261103_051836_288d0e/run"
J2="C:/Temp/fanxing_runs/canvas_job_20261103_061953_8ce3c5/run"
OUT="C:/Users/若水/Movies/Hub/Projects/第二十三星区/h3/out/U01-U12_整幕粗剪v2_20261103.mp4"

FILES=(
  "C:/Temp/fanxing_runs/u0103_low_1103/run/H3_U01_H3_U01_00005-audio.mp4.mp4"
  "$J1/H3_U02_H3_U02_00010-audio.mp4.mp4"
  "$J1/H3_U03_H3_U03_00013-audio.mp4.mp4"
  "$J1/H3_U04_H3_U04_00006-audio.mp4.mp4"
  "C:/Temp/fanxing_runs/u05_4ref_1103b/run/H3_U05_H3_U05_00004-audio.mp4.mp4"
  "$J2/H3_U06_H3_U06_00002-audio.mp4.mp4"
  ""C:/Temp/fanxing_runs/canvas_job_20261103_074829_da2221/run/H3_U07_H3_U07_00004-audio.mp4.mp4""
  "$J2/H3_U08_H3_U08_00001-audio.mp4.mp4"
  "$J2/H3_U09_H3_U09_00002-audio.mp4.mp4"
  "$J2/H3_U10_H3_U10_00002-audio.mp4.mp4"
  "$J2/H3_U11_H3_U11_00002-audio.mp4.mp4"
  "$J2/H3_U12_H3_U12_00001-audio.mp4.mp4"
)

ARGS=()
for f in "${FILES[@]}"; do
  [ -f "$f" ] || { echo "缺文件: $f" >&2; exit 1; }
  ARGS+=(-i "$f")
done

FC=""
MAP=""
n=${#FILES[@]}
for ((i=0;i<n;i++)); do
  FC+="[$i:v]scale=1024:576:force_original_aspect_ratio=increase,crop=1024:576,setsar=1,fps=24[v$i];"
  MAP+="[v$i][$i:a]"
done
FC+="${MAP}concat=n=$n:v=1:a=1[outv][outa]"

"$FF" -y -hide_banner -loglevel error "${ARGS[@]}" \
  -filter_complex "$FC" -map "[outv]" -map "[outa]" \
  -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p \
  -c:a aac -b:a 128k -ar 32000 -movflags +faststart "$OUT"

echo "wrote: $OUT"
"$FF" -hide_banner -i "$OUT" 2>&1 | grep -E "Duration|Stream #"
