# -*- coding: utf-8 -*-
"""新 5 张即梦正脸特写（用户自产 14:23）：SCRFD + 脸尺寸 + ArcFace 对比即梦原四张 + 互判 + 水印角检。"""
import itertools
import os
import numpy as np
import cv2
from insightface.app import FaceAnalysis

SRC = r"E:/创作/武昭君仪/即梦武君"
ORIG = r"D:/AIWorkflow/tmp/wzy/jimeng"
OUTJ = r"D:/AIWorkflow/tmp/wzy/jimeng_new"
os.makedirs(OUTJ, exist_ok=True)

app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"])
app.prepare(ctx_id=-1, det_size=(640, 640))


def imread_u(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def get(p):
    im = imread_u(p)
    return im, app.get(im)


new_ids = ["2156", "2313", "5628", "6135", "9527"]
print("=== 新 5 张 ===")
new = {}
for nid in new_ids:
    f = next(f for f in os.listdir(SRC) if f"-{nid}-" in f)
    im, fs = get(os.path.join(SRC, f))
    print(f"[{nid}] {f[:66]}... img={im.shape[1]}x{im.shape[0]} 检出{len(fs)}张脸")
    if fs:
        for k, x in enumerate(fs):
            b = x.bbox.astype(int)
            print(f"    face{k}: det={x.det_score:.2f} 脸={b[2]-b[0]}x{b[3]-b[1]}px bbox={b.tolist()}")
        new[nid] = (im, f, max(fs, key=lambda f: f.det_score))
    else:
        new[nid] = (im, f, None)

print()
print("=== 新图互判 ArcFace ===")
embs = {k: v[2].normed_embedding for k, v in new.items() if v[2] is not None}
for a, b in itertools.combinations(sorted(embs), 2):
    print(f"  {a} vs {b}: {float(np.dot(embs[a], embs[b])):.3f}")

print()
print("=== vs 即梦原四张（jm_4492 / jm_9374 / jm_9862，每张取 det 前3 的脸）===")
for f in ["jm_4492_two_suits_turnaround.png", "jm_9374_three_suits.png", "jm_9862_dual_look_labeled.png"]:
    p = os.path.join(ORIG, f)
    im, fs = get(p)
    if not fs:
        print(f"  {f[:24]}: 检出 0")
        continue
    fs_sorted = sorted(fs, key=lambda x: x.det_score, reverse=True)
    print(f"  {f[:24]}: 检出 {len(fs)} 张脸，最大 det={fs_sorted[0].det_score:.2f}")
    for nid in sorted(embs):
        sims = [float(np.dot(embs[nid], x.normed_embedding)) for x in fs_sorted[:3]]
        print(f"    vs {nid}: top3 = [{', '.join(f'{s:.3f}' for s in sims)}]")

print()
print("=== 四角水印检查（72px 角块亮度/文字粗判）===")
for nid, (im, f, _) in new.items():
    h, w = im.shape[:2]
    c = 72
    corners = [im[0:c, 0:c], im[0:c, w-c:w], im[h-c:h, 0:c], im[h-c:h, w-c:w]]
    means = [round(float(x.mean()), 1) for x in corners]
    print(f"  [{nid}] 四角均值 TL/TR/BL/BR = {means}")
