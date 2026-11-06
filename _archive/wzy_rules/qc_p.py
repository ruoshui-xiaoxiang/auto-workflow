# -*- coding: utf-8 -*-
'''O 批身份核对：对 77 号脸锚的 ArcFace 相似度 + 六张互比（跨镜身份是否自洽）。'''
import os
import numpy as np
import cv2
from insightface.app import FaceAnalysis

ANCH = r'D:/AIWorkflow/tmp/wzy/anchors/junyi_face_v2.png'
D = r'D:/AIWorkflow/tmp/wzy/dz0p'
app = FaceAnalysis(name='buffalo_l', allowed_modules=['detection', 'recognition'])
app.prepare(ctx_id=-1, det_size=(640, 640))


def faces(p):
    im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    return im, app.get(im)


aim, afs = faces(ANCH)
a = afs[0].normed_embedding
print('anchor  face=%dx%d det=%.2f' % (
    afs[0].bbox[2] - afs[0].bbox[0], afs[0].bbox[3] - afs[0].bbox[1], afs[0].det_score))

emb = {}
for i in range(1, 7):
    k = "P%d" % i
    p = os.path.join(D, k + '.png')
    if not os.path.exists(p):
        print('%-3s 缺文件' % k)
        continue
    im, fs = faces(p)
    if not fs:
        print('%-3s 检出 0 张脸 -> 身份不可机判' % k)
        continue
    b = max(fs, key=lambda x: float(np.dot(a, x.normed_embedding)))
    bb = b.bbox.astype(int)
    emb[k] = b.normed_embedding
    print('%-3s det=%.2f face=%dx%d  sim(脸锚)=%.3f %s' % (
        k, b.det_score, bb[2] - bb[0], bb[3] - bb[1],
        float(np.dot(a, b.normed_embedding)),
        '同人' if float(np.dot(a, b.normed_embedding)) >= 0.5 else '不像'))

ks = sorted(emb)
print('\n六张互比（最低 / 平均）：')
sims = []
for i, x in enumerate(ks):
    row = []
    for y in ks[i + 1:]:
        s = float(np.dot(emb[x], emb[y]))
        row.append('%.2f' % s)
        sims.append(s)
    print('  %s vs %s' % (x, ' '.join(row)))
if sims:
    print('  跨张 min=%.3f  mean=%.3f  max=%.3f  n=%d' % (min(sims), sum(sims) / len(sims), max(sims), len(sims)))
