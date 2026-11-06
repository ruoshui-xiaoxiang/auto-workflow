# -*- coding: utf-8 -*-
'''O 批裙面色偏实测：不靠肉眼判"泛不泛粉紫"，在亮部低饱和区取 Lab 的 a*/b*。

a* > 0 偏红（粉），b* < 0 偏蓝（紫）。月白应当是 a* 略负或近 0、b* 略正或近 0 的冷灰白。
取样＝右下角以外的整幅亮部（V>200 且 S<70），排除背景要用脸部位置吗——
背景也是浅灰，会把结果拉平。所以只取"人物列带"：横向 x 0.25–0.75W、纵向 y 0.35–0.95H，
这块基本是衣服+地面投影，地面是中性灰，偏色主要来自衣服反光。
'''
import os
import numpy as np
import cv2

D = r'D:/AIWorkflow/tmp/wzy/dz0n'
for i in range(1, 7):
    k = 'N%d' % i
    im = cv2.imdecode(np.fromfile(os.path.join(D, k + '.png'), dtype=np.uint8), cv2.IMREAD_COLOR)
    h, w = im.shape[:2]
    band = im[int(h * 0.35):int(h * 0.95), int(w * 0.25):int(w * 0.75)]
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(band, cv2.COLOR_BGR2Lab).astype(np.int16) - np.array([128, 128, 128])
    sel = (hsv[:, :, 2] > 190) & (hsv[:, :, 1] < 70)
    n = int(sel.sum())
    if n < 5000:
        print('%s 亮部样本不足 %d' % (k, n))
        continue
    a = lab[:, :, 1][sel].mean()
    b = lab[:, :, 2][sel].mean()
    print('%s 亮部 %6d px  a*=%+.1f (%s)  b*=%+.1f (%s)' % (
        k, n, a, '偏粉' if a > 2 else ('偏绿' if a < -3 else '中性'),
        b, '偏紫' if b < -3 else ('偏暖黄' if b > 3 else '中性')))
