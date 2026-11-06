# -*- coding: utf-8 -*-
"""为一批定妆候选生成审片页三种图：face 特写 / full 缩略 / big 原图。
用法: python build_dzweb_imgs.py <src_dir> <base_num> <K1> [K2 ...]
例  : python build_dzweb_imgs.py dz0i 48 I1 I2 ... I10
"""
import os
import sys
import numpy as np
import cv2
from insightface.app import FaceAnalysis

OUT = r"D:/AIWorkflow/tmp/wzy/dzweb"
app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection"])
app.prepare(ctx_id=-1, det_size=(640, 640))


def imread_u(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def imwrite_u(p, im, q=92):
    cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, q])[1].tofile(p)


def main():
    src, base = sys.argv[1], int(sys.argv[2])
    keys = sys.argv[3:]
    for i, k in enumerate(keys):
        n = base + i
        sp = os.path.join(src, k + ".png")
        if not os.path.exists(sp):
            print("skip", k)
            continue
        im = imread_u(sp)
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
            print("OK %02d %s face=%dx%d det=%.2f" % (n, k, bw, bh, x.det_score))
        else:
            imwrite_u(os.path.join(OUT, "f%02d_face.jpg" % n), full, 88)
            print("OK %02d %s 无脸，face 用缩略兜底" % (n, k))


main()
