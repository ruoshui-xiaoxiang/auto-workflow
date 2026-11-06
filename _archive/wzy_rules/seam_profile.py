# -*- coding: utf-8 -*-
"""逐行差异剖面：查 inpaint / outpaint 的掩膜边界接痕。

做法：对每一行求该行 RGB 与源图对应行的平均绝对差，输出洞上下边界的行号附近剖面。
判据：边界行若显著高于「洞外平台值」，说明掩膜边缘留下了可见接缝。
"""
import os
import sys

import numpy as np
from PIL import Image

S = r"D:\AIWorkflow\tmp\Z-Image_编辑链冒烟_20261004"
HOLE = (168, 599, 564, 833)


def arr(p):
    return np.asarray(Image.open(p).convert("RGB"), dtype=np.float32)


def row_profile(a, b, x0, x1):
    d = np.abs(a[:, x0:x1] - b[:, x0:x1]).mean(2)
    return d.mean(1)


def report(tag, out_path, x0, x1, edge_rows, plateau_rows):
    src = arr(os.path.join(S, "smoke_in.png"))
    out = arr(out_path)
    prof = row_profile(out, src, x0, x1)
    plateau = float(np.median(prof[list(plateau_rows)]))
    print("\n[%s]  取样列 x %d..%d   平台值（远离边界处中位）= %.2f" % (tag, x0, x1, plateau))
    worst = []
    for r in edge_rows:
        if 0 <= r < len(prof):
            worst.append((r, float(prof[r])))
    for r, v in sorted(worst, key=lambda t: -t[1])[:6]:
        print("   行 %-5d 差异 %6.2f   倍率 %5.2fx" % (r, v, v / max(1e-6, plateau)))
    top = sorted(((float(prof[r]), r) for r in range(HOLE[3] - 40, HOLE[3] + 40)),
                 reverse=True)[:3]
    print("   洞下边界 ±40 行内最大三处：",
          ", ".join("行%d=%.2f" % (r, v) for v, r in top))


def main():
    x0, x1, y0, y1 = HOLE
    plateaus = list(range(y0 - 120, y0 - 60)) + list(range(y1 + 60, y1 + 120))
    edges = [y for y in range(y0 - 12, y0 + 13)] + [y for y in range(y1 - 12, y1 + 13)]
    report("inpaint 洞上下边界",
           os.path.join(S, r"出图\zedit_inpaint_001_00001_.png"),
           x0 + 30, x1 - 30, edges, plateaus)

    # outpaint：原始区在 x 256..256+768，接缝在 x=256 与 x=256+768 两列
    out = arr(os.path.join(S, r"出图\zedit_outpaint_001_00001_.png"))
    src = arr(os.path.join(S, "smoke_in.png"))
    d = np.abs(out[:, 256:256 + src.shape[1]] - src).mean(2)
    colprof = d.mean(0)
    print("\n[outpaint] 原始区列向差异剖面（接缝应在列 0 与列 %d）" % (src.shape[1] - 1))
    print("   平台值（离边 60 列以上中位）= %.2f"
          % float(np.median(colprof[60:-60])))
    for label, idx in (("左边界列 0..12", colprof[:12]),
                       ("右边界列 末 12", colprof[-12:])):
        print("   %-16s 最大 %.2f  均值 %.2f" % (label, float(idx.max()), float(idx.mean())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
