# -*- coding: utf-8 -*-
r"""单位错配探针：检光用 cv2.VideoCapture 读视频，再按 `--range` 的公式把 BGR 亮度折成 IRE。
问题：**解码链自己有没有把 tv(16–235) 展到 full(0–255)**？
如果有，那 `auto` 读到容器的 tv 旗后再套一次 limited 公式＝**同一个摆幅换算做了两遍**，
报表里就会出现「负 IRE」「108 IRE」这种不可能的数——那是我的尺子造的，不是片子的。

做法：造一张已知**码值**的条纹片（Y=0/16/235/255 四条，U=V=128），
用 -color_range tv 旗编码；然后 (a) 绕开换算直接读编码回来的 Y，验证码值没被动过；
(b) 用 cv2.VideoCapture 读 BGR，看每条落在几。
  · 若 16→0、235→255 ＝ 解码链已经展幅 ⇒ 后续只能按 full 算，limited 公式是二次换算。
  · 若 16→16、235→235 ＝ 解码链没动幅 ⇒ limited 公式站得住。
"""
import os
import subprocess

import cv2
import numpy as np

FFMPEG = r"D:\AIWorkflow\tools\ffmpeg.exe"
OUT = r"D:\AIWorkflow\tmp\range_probe"
W = H = 64
BANDS = [0, 16, 235, 255]


def write_raw_yuv(path):
    y = np.zeros((H, W), dtype=np.uint8)
    for i, v in enumerate(BANDS):
        y[i * (H // 4):(i + 1) * (H // 4), :] = v
    uv = np.full((H // 2, W // 2), 128, dtype=np.uint8)
    with open(path, "wb") as f:
        f.write(y.tobytes())
        f.write(uv.tobytes())
        f.write(uv.tobytes())


def main():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    raw = os.path.join(OUT, "bands.yuv")
    mp4 = os.path.join(OUT, "bands_tv.mp4")
    write_raw_yuv(raw)
    r = subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "yuv420p",
                        "-s", "%dx%d" % (W, H), "-i", raw, "-frames:v", "1",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high",
                        "-color_range", "tv", "-colorspace", "bt709",
                        "-color_trc", "bt709", "-color_primaries", "bt709", mp4],
                       capture_output=True)
    print("编码：", "ok" if r.returncode == 0 else r.stderr.decode("utf-8", "replace")[:200])
    print("旗：", subprocess.run([r"D:\AIWorkflow\LivePortrait-main\bin\ffprobe.exe", "-v", "error",
                                 "-select_streams", "v:0", "-show_entries",
                                 "stream=color_range,color_space", "-of", "csv=p=0", mp4],
                                capture_output=True).stdout.decode().strip())

    # (a) 绕开换算读回来的码值 Y
    rr = subprocess.run([FFMPEG, "-v", "error", "-i", mp4, "-frames:v", "1",
                         "-pix_fmt", "yuv420p", "-f", "rawvideo", os.path.join(OUT, "back.yuv")],
                        capture_output=True)
    b = np.fromfile(os.path.join(OUT, "back.yuv"), dtype=np.uint8)
    yb = b[:W * H].reshape(H, W)
    print("回来的 Y 码值（每条中位数）：",
          [int(np.median(yb[i * (H // 4):(i + 1) * (H // 4), :])) for i in range(4)])

    # (b) 走检光那条链：cv2.VideoCapture → BGR
    cap = cv2.VideoCapture(mp4)
    ok, fr = cap.read()
    cap.release()
    if not ok:
        print("cv2 读不到帧")
        return 1
    print("cv2 读到的 BGR（每条均值，B/G/R 同值时＝纯灰）：")
    for i, v in enumerate(BANDS):
        band = fr[i * (H // 4):(i + 1) * (H // 4), :]
        print("  写 %3d → BGR %s" % (v, [int(round(x)) for x in band.reshape(-1, 3).mean(axis=0)]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
