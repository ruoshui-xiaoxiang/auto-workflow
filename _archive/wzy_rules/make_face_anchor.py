# -*- coding: utf-8 -*-
"""从 50 号（dz0i/I3.png）裁出脸锚：头肩胸，避开画面左侧的长枪。"""
import os
import numpy as np
import cv2
from insightface.app import FaceAnalysis

SRC = r"D:/AIWorkflow/tmp/wzy/dz0i/I3.png"
OUTD = r"E:/图像影音资源池/武昭君仪/素材/face_anchors"   # 2026-10-19：tmp 里那个 junction 已删，锚点正身只有资源池这一处；再往 tmp 写会把资产库分叉成两处
os.makedirs(OUTD, exist_ok=True)

app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"])
app.prepare(ctx_id=-1, det_size=(640, 640))


def imread_u(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def imwrite_u(p, im):
    cv2.imencode(".png", im)[1].tofile(p)


im = imread_u(SRC)
h, w = im.shape[:2]
fs = app.get(im)
x = max(fs, key=lambda f: f.det_score)
b = x.bbox.astype(int)
bw, bh = b[2] - b[0], b[3] - b[1]
cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
print("img %dx%d face bbox %s (%dx%d)" % (w, h, b.tolist(), bw, bh))

# 半幅预览：看长枪杆在哪个 x 区间，避免裁进去
for name, box in [("probe_left", (0, 0, w // 2, h)), ("probe_right", (w // 2, 0, w, h))]:
    x0, y0, x1, y1 = box
    imwrite_u(os.path.join(OUTD, name + ".png"), im[y0:y1, x0:x1])

# 候选锚：以脸心为基准的胸像
for tag, (sx, sy, ex, ey) in {
    "tight": (cx - int(bw * 2.2), cy - int(bh * 1.9), cx + int(bw * 2.2), cy + int(bh * 2.6)),
    "bust": (cx - int(bw * 3.0), cy - int(bh * 2.4), cx + int(bw * 3.0), cy + int(bh * 4.2)),
}.items():
    sx, sy = max(0, sx), max(0, sy)
    ex, ey = min(w, ex), min(h, ey)
    crop = im[sy:ey, sx:ex]
    p = os.path.join(OUTD, "junyi_face_%s.png" % tag)
    imwrite_u(p, crop)
    cf = app.get(crop)
    if cf:
        f = max(cf, key=lambda f: f.det_score)
        sim = float(np.dot(x.normed_embedding, f.normed_embedding))
        print("%-6s crop %dx%d @(%d,%d) det=%.2f sim_vs_src=%.3f" % (
            tag, crop.shape[1], crop.shape[0], sx, sy, f.det_score, sim))
    else:
        print("%-6s crop 检不出脸" % tag)
