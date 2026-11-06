# -*- coding: utf-8 -*-
"""为 H 批（编号 42-47）生成审片页三种图：face 特写 / full 缩略 / big 原图。"""
import os
import numpy as np
import cv2
from insightface.app import FaceAnalysis

SRC = r"D:/AIWorkflow/tmp/wzy/dz0h"
OUT = r"D:/AIWorkflow/tmp/wzy/dzweb"
BASE = 42
KEYS = ["H1", "H2", "H3", "H4", "H5", "H6"]

app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection"])
app.prepare(ctx_id=-1, det_size=(640, 640))


def imread_u(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def imwrite_u(p, im, q=92):
    ok, buf = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, q])
    buf.tofile(p)


for i, k in enumerate(KEYS):
    n = BASE + i
    src = os.path.join(SRC, k + ".png")
    if not os.path.exists(src):
        print("skip", k)
        continue
    im = imread_u(src)
    h, w = im.shape[:2]
    imwrite_u(os.path.join(OUT, "f%02d_big.jpg" % n), im)
    full = cv2.resize(im, (int(w * 760.0 / h), 760), interpolation=cv2.INTER_AREA)
    imwrite_u(os.path.join(OUT, "f%02d_full.jpg" % n), full, 88)
    fs = app.get(im)
    if fs:
        x = max(fs, key=lambda f: f.det_score)
        b = x.bbox.astype(int)
        bw, bh = b[2] - b[0], b[3] - b[1]
        cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
        s = int(max(bw, bh) * 1.9)
        x0, y0 = max(0, cx - s), max(0, cy - int(s * 1.05))
        x1, y1 = min(w, cx + s), min(h, cy + int(s * 1.05))
        crop = im[y0:y1, x0:x1]
        ch, cw = crop.shape[:2]
        sc = 600.0 / max(ch, cw)
        crop = cv2.resize(crop, (int(cw * sc), int(ch * sc)), interpolation=cv2.INTER_AREA)
        imwrite_u(os.path.join(OUT, "f%02d_face.jpg" % n), crop, 90)
        print("OK %02d %s face=%dx%d det=%.2f" % (n, k, b[2]-b[0], b[3]-b[1], x.det_score))
    else:
        imwrite_u(os.path.join(OUT, "f%02d_face.jpg" % n), full, 88)
        print("OK %02d %s 无脸，face 用缩略兜底" % (n, k))
