# -*- coding: utf-8 -*-
import numpy as np, cv2, os
from insightface.app import FaceAnalysis
REF = r"D:/AIWorkflow/tmp/wzy/ref/junyi_ref1.jpg"
D = r"D:/AIWorkflow/tmp/wzy/dz0h"
app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"])
app.prepare(ctx_id=-1, det_size=(640, 640))

def get(p):
    im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    return im, app.get(im)

rim, rfs = get(REF)
re_ = rfs[0].normed_embedding
print("ref face_px=%dx%d det=%.2f" % (rfs[0].bbox[2]-rfs[0].bbox[0], rfs[0].bbox[3]-rfs[0].bbox[1], rfs[0].det_score))
for k in ("H1","H2","H3","H4","H5","H6"):
    p = os.path.join(D, k + ".png")
    if not os.path.exists(p):
        print("%-3s 缺文件" % k); continue
    im, fs = get(p)
    if not fs:
        print("%-3s 检出 0 张脸 -> 身份不可机判" % k); continue
    best = max(fs, key=lambda x: float(np.dot(re_, x.normed_embedding)))
    b = best.bbox.astype(int)
    sim = float(np.dot(re_, best.normed_embedding))
    print("%-3s det=%.2f face=%dx%d  sim(ref1)=%.3f %s" % (
        k, best.det_score, b[2]-b[0], b[3]-b[1], sim, "同人" if sim >= 0.5 else "不像"))
