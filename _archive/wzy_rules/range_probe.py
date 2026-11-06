# -*- coding: utf-8 -*-
r"""验「摆幅口径」这条：绕开 OpenCV 的 YUV→BGR 换算，直接读**编码后的 Y 平面**，
看这份抖音范例的亮度码值到底填满 0–255（=full 数据套了 tv 旗），
还是老实待在 16–235（=旗是对的，报表里 >100 IRE 是我自己解码链造的）。
同时把抽到的帧存成 PNG，给人眼看。"""
import os
import subprocess
import sys

import numpy as np

FFMPEG = r"D:\AIWorkflow\tools\ffmpeg.exe"
SRC = r"E:\图像影音资源池\_公共素材\中式色彩_20261004\范例\中式美学范例_抖音.mp4"
OUT = r"D:\AIWorkflow\tmp\range_probe"
FRAMES = [0, 45, 134, 268, 447, 670]
W, H = 1920, 1074          # ffprobe 实报（1074 是奇数高，raw 尺寸按 -s 输出的实际字节数反推）


def y_plane(n):
    raw = os.path.join(OUT, "f%d.yuv" % n)
    cmd = [FFMPEG, "-v", "error", "-i", SRC, "-vf", "select=eq(n\\,%d)" % n,
           "-frames:v", "1", "-pix_fmt", "yuv420p", "-f", "rawvideo", raw]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode or not os.path.isfile(raw):
        print("取帧 %s 失败：%s" % (n, r.stderr.decode("utf-8", "replace")[:200]))
        return None
    b = np.fromfile(raw, dtype=np.uint8)
    need = W * H * 3 // 2
    if b.size != need:
        print("字节数对不上：%d ≠ %d" % (b.size, need))
        return None
    y = b[:W * H].reshape(H, W).astype(np.float64)
    os.remove(raw)
    return y


def png(n):
    out = os.path.join(OUT, "f%d.png" % n)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", SRC,
                    "-vf", "select=eq(n\\,%d)" % n, "-frames:v", "1", out],
                   capture_output=True)
    return out if os.path.isfile(out) else None


def main():
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    print("码值刻度：limited 白=235 黑=16｜full 白=255 黑=0")
    print("帧   Y_p0.1  Y_p1   Y_p50  Y_p95  Y_p99.5  Y_max  ≥236%    ≤15%    >235像素数")
    for n in FRAMES:
        y = y_plane(n)
        if y is None:
            continue
        f = y.ravel()
        pc = lambda q: float(np.percentile(f, q))
        over = float((f > 235).mean() * 100)
        under = float((f < 16).mean() * 100)
        print("f%-4d %-8.1f %-6.1f %-6.1f %-6.1f %-8.1f %-6.0f %-8.3f %-8.3f %d"
              % (n, pc(0.1), pc(1), pc(50), pc(95), pc(99.5), f.max(), over, under,
                 int((f > 235).sum())))
    for n in FRAMES:
        p = png(n)
        if p:
            print("PNG：%s" % p)


if __name__ == "__main__":
    sys.exit(main())
