# -*- coding: utf-8 -*-
"""Z-Image i2i 的 denoise 梯子（5 点），本机通道自标定，不借 FLUX 数字。"""
import os
import sys

import numpy as np
from PIL import Image

TMP = r"D:\AIWorkflow\tmp\Z-Image_编辑链冒烟_20261004"
OUT = os.path.join(TMP, "出图")
SRC = os.path.join(TMP, "smoke_in.png")
PTS = [("0.30", "03"), ("0.45", "045"), ("0.60", "06"),
       ("0.75", "075"), ("0.90", "09")]


def arr(p):
    return np.asarray(Image.open(p).convert("RGB"), dtype=np.float32)


def gray_grad(a):
    """简化边缘图：梯度幅值，用于看构图/轮廓是否还在。"""
    g = a.mean(2)
    dy = np.abs(np.diff(g, axis=0)).mean()
    dx = np.abs(np.diff(g, axis=1)).mean()
    return dy + dx


def main():
    src = arr(SRC)
    base_l1 = np.abs(src - src.mean()).mean()
    print("基准 %dx%d  平均绝对偏差=%.2f  梯度=%.3f"
          % (src.shape[1], src.shape[0], base_l1, gray_grad(src)))
    print("\n%-7s %-8s %-9s %-11s %-9s" %
          ("denoise", "MAD", "亮度相关", "轮廓保留", "平均色偏移"))
    rows = []
    for label, tag in PTS:
        p = os.path.join(OUT, "zedit_i2i_d%s_001_00001_.png" % tag)
        a = arr(p)
        d = np.abs(a - src)
        mad = float(d.mean())
        ga, gb = a.mean(2).reshape(-1), src.mean(2).reshape(-1)
        c = float(np.corrcoef(ga, gb)[0, 1])
        keep = gray_grad(a) / gray_grad(src)
        colshift = float(np.abs(a - src).mean(1).reshape(-1, 3).mean(0).max())
        print("%-7s %-8.2f %-9.4f %-11.3f %-9.2f" % (label, mad, c, keep, colshift))
        rows.append((label, mad, c, keep))
    print("\n注：轮廓保留 = 生成图梯度 / 输入图梯度，1.0 表示锐度持平；"
          "低于 1 表示细节被抹平（重画时改的是低频结构）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
