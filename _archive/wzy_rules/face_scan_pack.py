# -*- coding: utf-8 -*-
"""资产包逐图最大脸框短边 + 与候选脸锚的 ArcFace 比对（决定谁能当脸锚）。"""
import os, glob, json, numpy as np, cv2
from insightface.app import FaceAnalysis
D = r'E:\创作\武昭君仪\武昭君仪资产包'
app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
app.prepare(ctx_id=-1, det_size=(640, 640))
def load(p):
    return cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
rows = []
cands = sorted(glob.glob(os.path.join(D, '*.png')))
faces = {}
for p in cands:
    im = load(p)
    if im is None: continue
    r = 1024 / max(im.shape[:2]); small = cv2.resize(im, None, fx=r, fy=r)
    try: fs = app.get(small)
    except Exception as e: fs = []
    if not fs:
        rows.append((os.path.basename(p), 0, 0, None, im.shape[:2])); continue
    best = max(fs, key=lambda f: f.det_score * (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
    side = int(max(best.normed_embedding.shape[0:0] or [0], 0)) if False else int(round(max(best.bbox[2]-best.bbox[0], best.bbox[3]-best.bbox[1]) / r))
    rows.append((os.path.basename(p), len(fs), side, float(best.det_score), im.shape[:2]))
    faces[p] = best
for n, k, s, d, sh in sorted(rows, key=lambda x: -x[2]):
    print(f'{s:5d}px  faces={k}  det={d:.2f}  {sh[1]}x{sh[0]}  {n}')
# 互比：每张最大脸 vs 其它每张最大脸
ks = list(faces)
print('\n=== 与「古代白衣 A02 最大脸」的 ArcFace ===')
ref = [k for k in ks if 'A02' in os.path.basename(k)]
if ref:
    e0 = faces[ref[0]].normed_embedding
    for k in ks:
        if k == ref[0]: continue
        print(f'{float(np.dot(e0, faces[k].normed_embedding)):.3f}  {os.path.basename(k)[:44]}')
