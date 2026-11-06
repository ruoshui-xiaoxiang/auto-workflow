# -*- coding: utf-8 -*-
"""镜内场景漂移的对照：每条片取首/中/末三帧拼一张表，纯 cv2，不吃显存也不吃内存。
用途＝判断"H05 从林间漂成镇街"是 15 秒长镜的通病（Seedance 也漂）还是 H3 特有。"""
import os, sys, glob, cv2, numpy as np

OUT = r'D:\AIWorkflow\tmp\wzy\kf_out\drift_sheet.jpg'
PK = r'E:\创作\武昭君仪\武昭君仪资产包'
H3 = r'E:\图像影音资源池\武昭君仪\批次\20260926_022703\video\xn_20260926_022703_00001_.mp4'

srcs = [('H05·H3 362帧', H3)] + [('Seedance ' + os.path.basename(p)[:22], p)
                                 for p in sorted(glob.glob(os.path.join(PK, '*.mp4')))]
TW, TH = 300, 169
rows = []
for tag, p in srcs:
    if not os.path.isfile(p): continue
    c = cv2.VideoCapture(p)
    n = int(c.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    got = []
    for k in (0, n // 2, n - 2):
        c.set(cv2.CAP_PROP_POS_FRAMES, k)
        ok, f = c.read()
        got.append(cv2.resize(f, (TW, TH)) if ok else np.zeros((TH, TW, 3), np.uint8))
    c.release()
    # 首末帧的粗差异（同分辨率灰度直方图相关）：给"漂了多少"一个可排序的数
    g = [cv2.cvtColor(x, cv2.COLOR_BGR2GRAY) for x in (got[0], got[2])]
    h0 = cv2.calcHist([g[0]], [0], None, [32], [0, 256]); h0 /= h0.sum()
    h1 = cv2.calcHist([g[1]], [0], None, [32], [0, 256]); h1 /= h1.sum()
    d = float(cv2.compareHist(h0, h1, cv2.HISTCMP_BHATTACHARYYA))
    lab = np.full((TH, 150, 3), 255, np.uint8)
    cv2.putText(lab, '%.2f' % d, (8, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    cv2.putText(lab, tag[:12], (8, 125), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1)
    rows.append(np.hstack([lab] + got))
    print('%-30s 首末亮度直方图距离 %.3f' % (tag, d))
sheet = np.vstack(rows)
cv2.imencode('.jpg', sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tofile(OUT)
print('表：', OUT, sheet.shape)
