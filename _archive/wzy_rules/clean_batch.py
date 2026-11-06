# -*- coding: utf-8 -*-
'''通用 Seedream 右下角「AI生成」胶囊清洗（定稿口径，取代 clean_o*.py 一次性脚本）。

三条实测结论：
  1. 亮度超出法（jianlai 原版 clean_wm.py）对**半透明白压近白地面**是假阴性——
     mask 会抓到裙脚高光和画内物体，把矛尾铜鐏一起 TELEA 抹糊。判"干净没有"只能放大角区看。
  2. 正解＝**锁死胶囊占位矩形**（1536x2688 上约 x 0.855–1.00W、y 0.930–0.982H），
     再用「低饱和 S<55 且 高亮度 V>185」筛掉画内物体（青铜鐏＝饱和高、黑鞋＝亮度低，都被排除）。
  3. 阈值不能再放宽：v>150 / dif>1 那一档会把浅色裙脚一起吃掉（O 批第三遍实测），本脚本就是那一遍之前的版本。

用法: py clean_batch.py <子目录> <前缀字母> <张数>
例  : py clean_batch.py dz0p P 6
'''
import os
import sys
import numpy as np
import cv2

ROOT = r'D:/AIWorkflow/tmp/wzy'
RX = (0.855, 1.000)
RY = (0.930, 0.982)


def imread_u(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def main():
    sub, pre, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
    d = os.path.join(ROOT, sub)
    for i in range(1, n + 1):
        k = '%s%d' % (pre, i)
        a = os.path.join(d, k + '_raw.png')
        b = os.path.join(d, k + '.png')
        if not os.path.exists(a):
            print('SKIP', k)
            continue
        im = imread_u(a)
        h, w = im.shape[:2]
        x0, x1 = int(w * RX[0]), w
        y0, y1 = int(h * RY[0]), int(h * RY[1])
        g8 = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
        s, v = hsv[:, :, 1].astype(np.int16), hsv[:, :, 2].astype(np.int16)
        dif = np.abs(g8.astype(np.int16) - cv2.medianBlur(g8, 21).astype(np.int16))
        cand = ((dif > 2) & (s < 55) & (v > 185)).astype(np.uint8) * 255
        m = np.zeros((h, w), np.uint8)
        m[y0:y1, x0:x1] = cand[y0:y1, x0:x1]
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        m = cv2.dilate(m, np.ones((7, 7), np.uint8))
        cnt = int((m > 0).sum())
        if cnt < 800:
            cv2.imencode('.png', im)[1].tofile(b)
            print('NOPILL %s 命中 %d px' % (k, cnt))
        else:
            out = cv2.inpaint(im, m, 4, cv2.INPAINT_NS)
            cv2.imencode('.png', out)[1].tofile(b)
            print('OK %s 修补 %d px' % (k, cnt))
        cur = imread_u(b)
        crop = cur[int(h * 0.88):h, int(w * 0.70):w]
        crop = cv2.resize(crop, None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC)
        cv2.imencode('.png', crop)[1].tofile(os.path.join(d, k + '_corner.png'))


if __name__ == '__main__':
    main()
