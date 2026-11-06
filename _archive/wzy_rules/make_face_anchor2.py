# -*- coding: utf-8 -*-
"""50 号 → 纯脸锚（裁掉画面左侧的长枪杆，避免锚图把武器一起带进派生）。"""
import json
import os
import numpy as np
import cv2
from insightface.app import FaceAnalysis

SRC = r"D:/AIWorkflow/tmp/wzy/dz0i/I3.png"
OUTD = r"D:/AIWorkflow/tmp/wzy/anchors"
app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"])
app.prepare(ctx_id=-1, det_size=(640, 640))


def imread_u(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def imwrite_u(p, im):
    cv2.imencode(".png", im)[1].tofile(p)


im = imread_u(SRC)
h, w = im.shape[:2]
src_face = max(app.get(im), key=lambda f: f.det_score)
b = src_face.bbox.astype(int)
bw, bh = b[2] - b[0], b[3] - b[1]
cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2

x0, x1 = cx - int(bw * 1.35), cx + int(bw * 1.35)
y0, y1 = cy - int(bh * 1.55), cy + int(bh * 2.15)
x0, y0 = max(0, x0), max(0, y0)
x1, y1 = min(w, x1), min(h, y1)
crop = im[y0:y1, x0:x1]
p = os.path.join(OUTD, "junyi_face.png")
imwrite_u(p, crop)
imwrite_u(os.path.join(OUTD, "junyi_face_check.png"),
          cv2.rectangle(im.copy(), (x0, y0), (x1, y1), (0, 0, 255), 10))

cf = app.get(crop)
f = max(cf, key=lambda f: f.det_score) if cf else None
sim = float(np.dot(src_face.normed_embedding, f.normed_embedding)) if f else -1
print("crop %dx%d @(%d,%d)-(%d,%d) det=%s sim=%.3f" % (
    crop.shape[1], crop.shape[0], x0, y0, x1, y1,
    "%.2f" % f.det_score if f else "None", sim))

json.dump({
    "character": "武君仪",
    "role": "face_anchor",
    "source": "50 号 = dz0i/I3.png（I 批，用户点名用这张脸）",
    "source_seed": 2026100303,
    "derived_from": "纯文生图，写实电影级 CG 挂",
    "crop_box": [int(x0), int(y0), int(x1), int(y1)],
    "crop_note": "裁掉画面左侧的长枪杆，锚图内不含武器；武器另有道具锚",
    "face_px": [int(crop.shape[1]), int(crop.shape[0])],
    "scrfd_det": float(f.det_score) if f else None,
    "arcface_sim_vs_source_full": sim,
    "status": "candidate（等批 0b 派生验证后才算 confirmed）",
}, open(os.path.join(OUTD, "junyi_face.anchor.json"), "w", encoding="utf-8"),
    ensure_ascii=False, indent=2)
print("wrote junyi_face.png + junyi_face.anchor.json")
