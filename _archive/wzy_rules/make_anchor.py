# -*- coding: utf-8 -*-
"""通用：从一张定妆候选里裁"无武器"的脸锚，写 sidecar。
用法: python make_anchor.py <src.png> <out_prefix> <编号说明>
"""
import json
import os
import sys
import numpy as np
import cv2
from insightface.app import FaceAnalysis

OUTD = r"E:/图像影音资源池/武昭君仪/素材/face_anchors"   # 2026-10-19：tmp 里那个 junction 已删，锚点正身只有资源池这一处；再往 tmp 写会把资产库分叉成两处
app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"])
app.prepare(ctx_id=-1, det_size=(640, 640))


def imread_u(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def main():
    src, pref, label = sys.argv[1], sys.argv[2], sys.argv[3]
    im = imread_u(src)
    h, w = im.shape[:2]
    faces = app.get(im)
    x = max(faces, key=lambda f: f.det_score)
    b = x.bbox.astype(int)
    bw, bh = b[2] - b[0], b[3] - b[1]
    cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
    x0, x1 = max(0, cx - int(bw * 1.35)), min(w, cx + int(bw * 1.35))
    y0, y1 = max(0, cy - int(bh * 1.55)), min(h, cy + int(bh * 2.15))
    crop = im[y0:y1, x0:x1]
    p = os.path.join(OUTD, pref + ".png")
    cv2.imencode(".png", crop)[1].tofile(p)
    cv2.imencode(".png", cv2.rectangle(im.copy(), (x0, y0), (x1, y1), (0, 0, 255), 10))[1].tofile(
        os.path.join(OUTD, pref + "_check.png"))
    cf = app.get(crop)
    f = max(cf, key=lambda f: f.det_score) if cf else None
    sim = float(np.dot(x.normed_embedding, f.normed_embedding)) if f else -1
    print("crop %dx%d @(%d,%d)-(%d,%d) det=%s sim=%.3f" % (
        crop.shape[1], crop.shape[0], x0, y0, x1, y1,
        "%.2f" % f.det_score if f else "None", sim))
    json.dump({
        "character": "武君仪",
        "role": "face_anchor",
        "source": label,
        "render_style": "高精度 3D 半写实国漫（挂参考画稿 style_bjd_art.png 出来的）",
        "crop_box": [int(x0), int(y0), int(x1), int(y1)],
        "crop_note": "裁切框按脸心左右各 1.35 倍脸宽，避开画面两侧的长矛；锚图内不含武器",
        "scrfd_det": float(f.det_score) if f else None,
        "arcface_sim_vs_source_full": sim,
        "status": "candidate（等挂它派生的那批被用户认可后才记 confirmed）",
    }, open(os.path.join(OUTD, pref + ".anchor.json"), "w", encoding="utf-8"),
        ensure_ascii=False, indent=2)
    print("wrote", pref + ".png +", pref + ".anchor.json")


main()
