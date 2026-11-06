# -*- coding: utf-8 -*-
"""边界外侧衰减表：区分「洞内内容变了」与「掩膜边缘留了接缝」。

只认边界外侧的值：外侧若回落到平台，说明没有接缝；外侧持续偏高才是接痕。
outpaint 同理看原始区内侧被 feather 吃掉的带宽。
"""
import os

import numpy as np
from PIL import Image

S = r"D:\AIWorkflow\tmp\Z-Image_编辑链冒烟_20261004"
HOLE = (168, 599, 564, 833)


def arr(p):
    return np.asarray(Image.open(p).convert("RGB"), dtype=np.float32)


def main():
    src = arr(os.path.join(S, "smoke_in.png"))
    x0, x1, y0, y1 = HOLE

    out = arr(os.path.join(S, r"出图\zedit_inpaint_001_00001_.png"))
    rowd = np.abs(out[:, x0 + 30:x1 - 30] - src[:, x0 + 30:x1 - 30]).mean(2).mean(1)
    plateau = float(np.median(np.r_[rowd[y0 - 150:y0 - 60], rowd[y1 + 60:y1 + 150]]))
    print("inpaint：平台值 %.2f（洞外远处中位）" % plateau)
    print("  洞上边界 y=%d 外侧 6 行：%s" % (y0,
          " ".join("%.1f" % rowd[y0 + 1 + k] for k in range(6))))
    print("  洞上边界 y=%d 内侧 6 行：%s" % (y0,
          " ".join("%.1f" % rowd[y0 - 1 - k] for k in range(6))))
    print("  洞下边界 y=%d 外侧 6 行：%s" % (y1,
          " ".join("%.1f" % rowd[y1 + 1 + k] for k in range(6))))
    print("  洞下边界 y=%d 内侧 6 行：%s" % (y1,
          " ".join("%.1f" % rowd[y1 - 1 - k] for k in range(6))))
    far = float(np.r_[rowd[y1 + 20:y1 + 60]].mean())
    print("  洞下 20..60 行均值 %.2f  → 相对平台 %.2fx" % (far, far / max(1e-6, plateau)))

    o2 = arr(os.path.join(S, r"出图\zedit_outpaint_001_00001_.png"))
    W = src.shape[1]
    cold = np.abs(o2[:, 256:256 + W] - src).mean(2).mean(0)
    plat2 = float(np.median(cold[120:-120]))
    print("\noutpaint：平台值 %.2f（原始区中部中位）" % plat2)
    print("  左边缘向内 8 列：%s" % " ".join("%.1f" % cold[k] for k in range(0, 40, 5)))
    print("  右边缘向内 8 列：%s" % " ".join("%.1f" % cold[W - 1 - k] for k in range(0, 40, 5)))
    inside_band = cold[:40].mean()
    print("  左 40 列均值 %.2f（=%.1fx 平台）；40..80 列均值 %.2f（=%.1fx）"
          % (inside_band, inside_band / plat2,
             cold[40:80].mean(), cold[40:80].mean() / plat2))
    print("  ⇒ feather=40 时，原始区被吃掉的带宽约 40 列（与 FLUX 侧同机制）")


if __name__ == "__main__":
    main()
