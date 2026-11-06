# -*- coding: utf-8 -*-
# 资产包体检：他新递来的 35 个文件，先量再表态（哪张能当锚、当哪种锚、身份链断没断）。
# 量四件事：①尺寸/画幅（能不能当竖屏首帧）②md5 查重（跟我已有的锚是不是同一张）
# ③人脸：SCRFD 检出框尺寸＝能不能当脸锚，ArcFace 对现行脸锚＝身份链通不通
# ④视频：分辨率/帧率/时长/帧数
import hashlib
import json
import os

import cv2
import numpy as np
from insightface.app import FaceAnalysis

PACK = r'E:/创作/武昭君仪/武昭君仪资产包'
MYANCHOR = r'E:/图像影音资源池/武昭君仪/素材/face_anchors/dingzhuang'  # 2026-10-19 迁出 tmp：锚点定妆资产正身在资源池（tmp 不是落点，而旧文档还写着tmp「用完即清」——照做就毁掉这 58 个不可再生文件）。tmp/wzy/anchors 现是指向它的 junction。
FACE_CUR = os.path.join(MYANCHOR, 'junyi_face_jm2156.png')

app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
app.prepare(ctx_id=0, det_size=(640, 640))


def im(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def md5(p):
    h = hashlib.md5()
    with open(p, 'r+b') as f:
        h.update(f.read())
    return h.hexdigest()[:12]


def big_face(a):
    fs = app.get(a)
    if not fs:
        return None, None, None
    f = max(fs, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))
    return f, [int(v) for v in f.bbox], len(fs)


ref = im(FACE_CUR)
rf, _, _ = big_face(ref)
print('基准脸锚 = %s  ArcFace 自比 1.000' % os.path.basename(FACE_CUR))
mine = {md5(os.path.join(MYANCHOR, f)): f for f in os.listdir(MYANCHOR) if f.lower().endswith('.png')}
print('我已有锚 %d 张在册\n' % len(mine))

rows = []
for f in sorted(os.listdir(PACK)):
    p = os.path.join(PACK, f)
    if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
        a = im(p)
        H, W = a.shape[:2]
        ratio = W / H
        m = md5(p)
        dup = mine.get(m, '')
        fa, box, n = big_face(a)
        fw = fh = 0
        sim = float('nan')
        if fa is not None:
            fw, fh = box[2] - box[0], box[3] - box[1]
            sim = float(np.dot(fa.normed_embedding, rf.normed_embedding)
                        / (np.linalg.norm(fa.normed_embedding) * np.linalg.norm(rf.normed_embedding)))
        rows.append(dict(file=f, kind='图', size='%dx%d' % (W, H), ar=round(ratio, 3),
                         md5=m, dup=dup, faces=n, facepx='%dx%d' % (fw, fh),
                         arc=round(sim, 3) if fa is not None else None))
    elif f.lower().endswith('.mp4'):
        c = cv2.VideoCapture(p)
        n = int(c.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = c.get(cv2.CAP_PROP_FPS) or 24.0
        W, H = int(c.get(3)), int(c.get(4))
        c.release()
        rows.append(dict(file=f, kind='视频', size='%dx%d' % (W, H), ar=round(W / H, 3),
                         md5=md5(p), dup='', faces='-', facepx='fps %.1f / %d 帧 / %.1fs' % (fps, n, n / fps),
                         arc=None))

print('%-46s %-4s %-11s %-6s %-10s %-6s %-14s %s'
      % ('文件', '类型', '尺寸', '画幅', 'md5', '脸数', '最大脸/规格', 'ArcFace对现行脸锚'))
print('-' * 118)
for r in rows:
    print('%-46s %-4s %-11s %-6s %-10s %-6s %-14s %s'
          % (r['file'][:44], r['kind'], r['size'], r['ar'], r['md5'], r['faces'],
             str(r['facepx'])[:14], r['arc']))
    if r['dup']:
        print('        ↑ 与我已有锚重复：%s' % r['dup'])
json.dump(rows, open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  'asset_pack_scan.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('\n明细写 asset_pack_scan.json')
