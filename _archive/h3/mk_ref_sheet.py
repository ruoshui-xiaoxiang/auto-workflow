# -*- coding: utf-8 -*-
"""8 段参考片各抽 4 帧，拼成一张校对表（核对每段实际出场人物/景别/朝向）。
用法: py mk_ref_sheet.py
"""
import os, subprocess, tempfile
import cv2
import numpy as np

FF = r"D:\AIWorkflow\tools\ffmpeg.exe"
SRC = (r"E:\图像影音资源池\无音_镜1镜2_对照\无音_复刻参考片段\整段_逐玉")
OUT = r"D:\AIWorkflow\ComfyUI_H3\output\_参考段校对表.jpg"
TMP = tempfile.mkdtemp(prefix="refsheet_")
W = 360
NCOL = 4

SEGS = [
    ("seg01", "ref_01_247.12-254.24.mp4", 7.12),
    ("seg02", "ref_02_254.24-261.88.mp4", 7.64),
    ("seg03", "ref_03_261.88-266.36.mp4", 4.48),
    ("seg04", "ref_04_266.36-270.8.mp4",  4.44),
    ("seg05", "ref_05_270.8-275.08.mp4",  4.28),
    ("seg06", "ref_06_275.08-278.12.mp4", 3.04),
    ("seg07", "ref_07_278.12-282.96.mp4", 4.84),
    ("seg08", "ref_08_282.96-289.04.mp4", 6.08),
]

def grab(video, t, tag):
    p = os.path.join(TMP, tag + ".png")
    r = subprocess.run([FF, "-y", "-v", "error", "-i", video, "-ss", "%.3f" % t,
                        "-frames:v", "1", p], capture_output=True)
    if not os.path.exists(p):
        raise RuntimeError("抽帧失败 %s: %s" % (video, r.stderr.decode("utf-8","ignore")[:200]))
    img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    h = int(img.shape[0] * W / img.shape[1])
    return cv2.resize(img, (W, h), interpolation=cv2.INTER_AREA)

def lab(img, text, color=(255, 255, 255)):
    out = img.copy()
    cv2.rectangle(out, (0, 0), (out.shape[1], 30), (0, 0, 0), -1)
    cv2.putText(out, text, (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
    return out

rows = []
for name, fn, dur in SEGS:
    pics = []
    for j, frac in enumerate([0.06, 0.35, 0.65, 0.94]):
        try:
            pic = grab(SRC + fn, dur * frac, "%s_%d" % (name, j))
        except Exception as e:
            print("跳过", name, j, e, flush=True)
            continue
        t = frac * dur
        pics.append(lab(pic, "%s  +%.1fs" % (name, t), (120, 255, 120)))
    if len(pics) == NCOL:
        rows.append(np.hstack(pics))

grid = np.vstack(rows)
ok, buf = cv2.imencode(".jpg", grid, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
buf.tofile(OUT)
print("写出:", OUT, grid.shape, flush=True)
