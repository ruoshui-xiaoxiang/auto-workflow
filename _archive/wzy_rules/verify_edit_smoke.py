# -*- coding: utf-8 -*-
"""Z-Image 编辑链冒烟的机械核验（只量不判）。

量三件事：
  1. 尺寸：i2i/inpaint 应等于输入尺寸；outpaint 应等于输入 + 垫宽。
  2. 掩膜遵守度：以「无洞原图」为基准，洞外差异应≈VAE 往返地板，洞内差异应显著大。
  3. 构图保持度：i2i 两档 denoise 与输入的逐像素差异 + 亮度相关。

地板参照：同图做「VAEEncode→VAEDecode 往返」的最小差异。这里用「掩膜外」自身
的分布做参照，不引入外部数字。
"""
import os
import sys

import numpy as np
from PIL import Image

TMP = r"D:\AIWorkflow\tmp\Z-Image_编辑链冒烟_20261004"
OUT = os.path.join(TMP, "出图")
SRC = os.path.join(TMP, "smoke_in.png")
MSK = os.path.join(TMP, "smoke_mask.png")

HOLE = (168, 599, 564, 833)      # x0 x1 y0 y1，与 prep_edit_smoke.py 一致
GROW = 6


def arr(p, mode="RGB"):
    return np.asarray(Image.open(p).convert(mode), dtype=np.float32)


def mad(a, b):
    return float(np.abs(a - b).mean())


def corr(a, b):
    a = a.reshape(-1)
    b = b.reshape(-1)
    if a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def hole_rect(grow=0, pad=0):
    x0, x1, y0, y1 = HOLE
    return (max(0, x0 - grow - pad), min(4096, x1 + grow + pad),
            max(0, y0 - grow - pad), min(4096, y1 + grow + pad))


def band_split(shape, rect):
    h, w = shape[:2]
    inb = np.zeros((h, w), dtype=bool)
    x0, x1, y0, y1 = rect
    inb[y0:y1, x0:x1] = True
    return inb


def main():
    src = arr(SRC)
    msk = arr(MSK, "RGBA")
    h, w = src.shape[:2]
    print("基准输入 %dx%d；alpha 全 255 的像素占比 %.1f%%"
          % (w, h, 100.0 * (msk[:, :, 3] > 250).mean()))

    # ---- 1. i2i 两档 ----
    print("\n[1] i2i 构图保持度（对输入逐像素）")
    for d in ("03", "06"):
        p = os.path.join(OUT, "zedit_i2i_d%s_001_00001_.png" % d)
        a = arr(p)
        print("  denoise %s  尺寸 %dx%d  MAD=%6.2f  亮度相关=%.4f"
              % (d, a.shape[1], a.shape[0], mad(a, src),
                 corr(a.mean(2), src.mean(2))))

    # ---- 2. inpaint 掩膜遵守度 ----
    print("\n[2] inpaint 掩膜遵守度（对无洞原图；洞外≈VAE往返地板，洞内应显著大）")
    p = os.path.join(OUT, "zedit_inpaint_001_00001_.png")
    a = arr(p)
    print("  尺寸 %dx%d" % (a.shape[1], a.shape[0]))
    for grow, tag in ((0, "洞本体"), (GROW, "洞+grow6"), (GROW + 24, "洞+grow6+24安全边")):
        rect = hole_rect(grow=grow)
        inb = band_split(a.shape, rect)
        d = np.abs(a - src).mean(2)
        print("  %-18s 内 MAD=%6.2f | 外 MAD=%6.2f | 内外比=%5.2f"
              % (tag, d[inb].mean(), d[~inb].mean(),
                 d[inb].mean() / max(1e-6, d[~inb].mean())))

    # ---- 3. outpaint ----
    print("\n[3] outpaint（左右各垫 256；原始区应≈地板，垫出区有内容）")
    p = os.path.join(OUT, "zedit_outpaint_001_00001_.png")
    a = arr(p)
    print("  尺寸 %dx%d  期望 %dx%d  %s"
          % (a.shape[1], a.shape[0], w + 512, h,
             "OK" if (a.shape[1], a.shape[0]) == (w + 512, h) else "不符"))
    if (a.shape[1], a.shape[0]) == (w + 512, h):
        centre = a[:, 256:256 + w]
        d = np.abs(centre - src).mean(2)
        print("  原始区 MAD=%6.2f" % d.mean())
        for tag, reg in (("左垫条", a[:, :256]), ("右垫条", a[:, 256 + w:])):
            g = reg.mean(2)
            print("  %s：均值=%5.1f 标准差=%5.1f 最亮%%=%.1f%% 最暗%%=%.1f%%"
                  % (tag, g.mean(), g.std(),
                     100.0 * (g > 240).mean(), 100.0 * (g < 8).mean()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
