# -*- coding: utf-8 -*-
"""抹掉 P3D 线稿首帧右上角霓虹招牌上的可读汉字「武君仪」v2。

v1 错在区域框偏左（框到左边全息广告牌，抹出一团糊）。v2 用自检图实测的坐标：
竖牌在整图 x≈0.90-0.96w、y≈0.06-0.30h；字是牌面上的亮白/亮粉像素，牌底板是暗紫。
只 inpaint 牌面内的亮像素，别处一律不碰。
"""
import cv2
import numpy as np
from pathlib import Path

D = Path(r'E:/创作/武昭君仪/首帧图/线稿机位图/h3first')
SRC = D / 'P3D_first.png'
BAK = D / 'P3D_first.bak-有字.png'

# 从备份恢复（v1 已把图弄脏）
img = cv2.imdecode(np.fromfile(str(BAK), dtype=np.uint8), cv2.IMREAD_COLOR)
h, w = img.shape[:2]
print('恢复自备份', img.shape)

x0, x1 = int(w * 0.895), int(w * 0.965)
y0, y1 = int(h * 0.050), int(h * 0.310)
roi = img[y0:y1, x0:x1]

hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
v, s = hsv[:, :, 2], hsv[:, :, 1]
# 字＝牌面内的**亮白**像素（高 v、低 s）；霓虹灯管是亮**品红**（高 v、高 s），要保住不抹
mask = ((v > 190) & (s < 140)).astype(np.uint8) * 255
mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)), iterations=2)
print('掩膜像素', int((mask > 0).sum()), '/', mask.size,
      '(%.1f%%)' % (100.0 * (mask > 0).sum() / mask.size))

fixed = cv2.inpaint(roi, mask, 9, cv2.INPAINT_TELEA)
img[y0:y1, x0:x1] = fixed
cv2.imencode('.png', img)[1].tofile(str(SRC))
print('已写回', SRC)

crop = img[0:int(h * 0.45), int(w * 0.62):w]
cv2.imencode('.png', crop)[1].tofile(r'D:/AIWorkflow/tmp/wzy/p3d_corner_fixed.png')
print('自检图 -> p3d_corner_fixed.png')
