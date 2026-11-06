# -*- coding: utf-8 -*-
# 写实挂第一步：从 A01 基线锁脸，重出一张高清君仪近景脸锚。
# 为什么要这一步（实测，不是我猜）：
#   A01 是 2048x1152 的四格三视图，里面最大的脸只有 77x98 px；
#   三格互判 ArcFace 只有 0.381 / 0.444 / 0.694 —— 连它自己都不算"同一个人"（我们那条线是 ≥0.5）。
#   ST01 里君仪那张脸（55px）对 A01 最佳只有 0.483。
#   ⇒ 直接拿这批当锚跑视频，身份链从第一镜就是断的；72 镜会逐镜漂。
#   脸锚要 ≥约280px（实测 189px 仍保住身份、128px 偏弱），所以必须先补一张近景。
# 用法：py run_r1_face.py            出图
#       py run_r1_face.py --measure  只量已有产物
import io
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, r'D:/AIWorkflow/tmp/jianlai_test')
OUT = r'D:/AIWorkflow/tmp/wzy/r1_face'
A01 = r'E:/创作/武昭君仪/武昭君仪资产包/A01 武君仪·赛博红衣基线.png'
os.makedirs(OUT, exist_ok=True)

PROMPT = '''**只用于锁定这张脸的骨相与五官**：窄长脸、骨骼成熟、下颌利落、尖下巴；
狭长凤眸（内眼角尖、外眼角微上挑）、眉形细而利落、唇形薄而轮廓清楚、眼神沉静冷。
**不要采用参考图的横屏构图、四格排版、同一人物多次出现。**
**服装按参考图**：深红暗纹交领劲装、腰束带、黑色皮革护臂、高马尾配银簪、垂落长披发。
高精度 CG 半写实，皮肤与织物材质写实、颗粒细腻，明暗层次密；
光：一侧暖橙霓虹、一侧冷蓝全息，体积光，湿润空气。
竖幅胸像特写，脸占画面高度约三分之一到二分之一；背景虚化为霓虹巷道散景。
无文字、无水印、无签名、无排版。'''
SEEDS = [2026105001, 2026105002]
W, H = 1152, 1536


def faces(p, det=960):
    from insightface.app import FaceAnalysis
    app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
    app.prepare(ctx_id=0, det_size=(det, det))
    a = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    out = []
    for x in app.get(a):
        b = [int(v) for v in x.bbox]
        out.append((b, x.normed_embedding.copy(), round(float(x.det_score), 3)))
    return a, out


def measure():
    ref = faces(A01)[1]
    if not ref:
        print('A01 检不到脸，先修参照')
        return
    rmax = max(ref, key=lambda r: (r[0][2] - r[0][0]) * (r[0][3] - r[0][1]))
    print('参照 = A01 最大脸 %dx%d px' % (rmax[0][2] - rmax[0][0], rmax[0][3] - rmax[0][1]))
    rows = []
    for f in sorted(os.listdir(OUT)):
        if not f.endswith('.png') or 'crop' in f:
            continue
        a, fs = faces(os.path.join(OUT, f))
        if not fs:
            print('  %-14s 检不到脸' % f)
            continue
        b, e, d = max(fs, key=lambda r: (r[0][2] - r[0][0]) * (r[0][3] - r[0][1]))
        w, h = b[2] - b[0], b[3] - b[1]
        sim = max(float(np.dot(e, r)) for _, r, _ in [(0, x[1], 0) for x in ref])
        ok = '脸锚可用' if (w >= 280 and sim >= 0.60) else ('偏弱' if sim >= 0.5 else '身份没锁住')
        print('  %-14s 脸 %3dx%-3d px  det %.2f  ArcFace对A01 %.3f  → %s' % (f, w, h, d, sim, ok))
        rows.append(dict(file=f, facepx=[w, h], det=d, arc=round(sim, 3), verdict=ok))
        cv2.imencode('.png', a[max(0, b[1]):b[3], max(0, b[0]):b[2]])[1].tofile(
            os.path.join(OUT, f[:-4] + '_crop.png'))
    json.dump(rows, io.open(os.path.join(OUT, 'measure.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if '--measure' in sys.argv:
    measure()
    sys.exit(0)

import ark_img
uris = [ark_img.data_uri(A01)]
for i, sd in enumerate(SEEDS, 1):
    k = 'R1_%d' % i
    p = os.path.join(OUT, k + '.png')
    if os.path.exists(p):
        print(k, '已存在')
        continue
    urls = ark_img.call(PROMPT, uris, sd, W, H)
    ark_img.fetch(urls[0], p)
    print('OK', k, os.path.getsize(p) // 1024, 'KB')
print('\n出完接着量：py run_r1_face.py --measure')
