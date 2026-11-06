# -*- coding: utf-8 -*-
"""J 批机检：这个画风下 SCRFD 还认不认脸、六张之间是不是同一张脸。"""
import itertools
import os
import numpy as np
import cv2
from insightface.app import FaceAnalysis

D = r"D:/AIWorkflow/tmp/wzy/dz0j"
app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"])
app.prepare(ctx_id=-1, det_size=(640, 640))


def get(p):
    im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    return im, app.get(im)


for arm in ("A", "B"):
    print("=== %s ===" % arm)
    embs = {}
    for i in range(1, 7):
        k = "%s%d" % (arm, i)
        p = os.path.join(D, k + ".png")
        if not os.path.exists(p):
            continue
        im, fs = get(p)
        if not fs:
            print("  %-3s 检出 0 张脸" % k)
            continue
        x = max(fs, key=lambda f: f.det_score)
        b = x.bbox.astype(int)
        embs[k] = x.normed_embedding
        print("  %-3s det=%.2f face=%dx%d  检出%d张" % (
            k, x.det_score, b[2]-b[0], b[3]-b[1], len(fs)))
    if len(embs) >= 2:
        sims = [float(np.dot(embs[a], embs[b])) for a, b in itertools.combinations(sorted(embs), 2)]
        print("  组内互判：min %.3f / 中位 %.3f / max %.3f（同人门槛 0.5）" % (
            min(sims), float(np.median(sims)), max(sims)))

# 与 50 号（写实挂脸锚）比：新画风还带不带得动那张脸
print("=== vs 50 号（写实挂 anchors/junyi_face.png）===")
_, rf = get(r"D:/AIWorkflow/tmp/wzy/anchors/junyi_face.png")
if rf:
    re_ = max(rf, key=lambda f: f.det_score).normed_embedding
    for arm in ("A", "B"):
        for i in range(1, 7):
            k = "%s%d" % (arm, i)
            p = os.path.join(D, k + ".png")
            if not os.path.exists(p):
                continue
            _, fs = get(p)
            if not fs:
                continue
            x = max(fs, key=lambda f: f.det_score)
            print("  %-3s sim(50号)=%.3f" % (k, float(np.dot(re_, x.normed_embedding))))
