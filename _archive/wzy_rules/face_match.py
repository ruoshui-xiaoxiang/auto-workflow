# -*- coding: utf-8 -*-
"""资产包内所有"君仪候选脸"的互比矩阵（决定脸锚与跨线同一人）。"""
import os, glob, numpy as np, cv2
from insightface.app import FaceAnalysis
D = r'E:\创作\武昭君仪\武昭君仪资产包'
app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
app.prepare(ctx_id=-1, det_size=(640, 640))
SEL = ['A01', 'A02', 'A03', 'ST01', 'jimeng-2026-09-25-2156', 'jimeng-2026-09-25-5628',
       'jimeng-2026-09-25-6135', 'jimeng-2026-09-25-2313', 'jimeng-2026-09-25-9527',
       'jimeng-2026-09-25-4492', 'jimeng-2026-09-25-9374', 'jimeng-2026-09-25-9862',
       'A07', 'A06']
REAL = r'E:\图像影音资源池\武昭君仪\素材\face_anchors\dingzhuang\junyi_face_real.png'  # 2026-10-19 迁出 tmp：锚点定妆资产正身在资源池（tmp 不是落点，而旧文档还写着tmp「用完即清」——照做就毁掉这 58 个不可再生文件）。tmp/wzy/anchors 现是指向它的 junction。
items = []
for tag in SEL:
    for p in glob.glob(os.path.join(D, '*.png')):
        if os.path.basename(p).startswith(tag):
            items.append(p)
items.append(REAL)
emb = {}
for p in items:
    im = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
    r = 1024 / max(im.shape[:2]); sm = cv2.resize(im, None, fx=r, fy=r)
    fs = app.get(sm)
    if not fs:
        print('无脸:', os.path.basename(p)[:40]); continue
    b = max(fs, key=lambda f: (f.bbox[2]-f.bbox[0])*(f.bbox[3]-f.bbox[1]))
    emb[os.path.basename(p)[:26]] = b.normed_embedding
ks = list(emb)
print('\n互比矩阵（每行 vs 列，>0.6 判同一人，0.4–0.6 灰区，<0.4 不同人）\n')
print('%-28s' % '', ''.join('%7s' % k[:6] for k in ks))
for a in ks:
    print('%-28s' % a, ''.join('%7.3f' % float(np.dot(emb[a], emb[b])) for b in ks))
