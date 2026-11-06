# -*- coding: utf-8 -*-
"""为 Z-Image 编辑链冒烟准备输入图：原图 + 带 alpha 洞的版本。

洞开在中下部（人物躯干区），面积足够大，能一眼看出掩膜内被重画、掩膜外没动。
"""
import os
import sys

import numpy as np
from PIL import Image

SRC = r"D:\AIWorkflow\tmp\Z-Image_冒烟_20261004\zsmoke_cn_竖屏_001_00001_.png"
OUT = r"D:\AIWorkflow\tmp\Z-Image_编辑链冒烟_20261004"

def main():
    os.makedirs(OUT, exist_ok=True)
    im = Image.open(SRC).convert("RGB")
    w, h = im.size
    print("源图 %dx%d" % (w, h))
    print("8 的倍数：w=%s h=%s" % (w % 8 == 0, h % 8 == 0))

    flat = os.path.join(OUT, "smoke_in.png")
    im.save(flat)

    rgba = np.array(im.convert("RGBA"))
    alpha = rgba[:, :, 3]
    y0, y1 = int(h * 0.42), int(h * 0.62)
    x0, x1 = int(w * 0.22), int(w * 0.78)
    alpha[y0:y1, x0:x1] = 0
    rgba[:, :, 3] = alpha
    masked = Image.fromarray(rgba)
    mk = os.path.join(OUT, "smoke_mask.png")
    masked.save(mk)
    print("掩膜洞：x %d..%d  y %d..%d  面积 %d px（占 %.1f%%）"
          % (x0, x1, y0, y1, (x1 - x0) * (y1 - y0),
             100.0 * (x1 - x0) * (y1 - y0) / (w * h)))
    print("落盘：")
    for f in sorted(os.listdir(OUT)):
        print("  ", f)
    return 0

if __name__ == "__main__":
    sys.exit(main())
