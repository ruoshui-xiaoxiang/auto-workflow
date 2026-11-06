# -*- coding: utf-8 -*-
"""ControlNet 几何遵守度（只量不判）。

三把尺子，全部以「同提示词不挂控制」为基线取差值：
  1) 边缘召回 recall：控制图上的边缘像素，有多少在输出图边缘的 r 邻域内找得到对应。
  2) 边缘精确 precision：反向——输出边缘有多少落在控制边缘邻域内（防"输出啥边缘都有"蒙分）。
  3) 布局相关 layout：把两张边缘图各降采样成 16×16 块密度，算 Pearson 相关。
     这把尺子对纹理/材质差异不敏感，量的就是"构图块面搬没搬过来"。

⚠ 换风格必然导致边缘不逐像素重合，所以绝对值不会高；有意义的是 CN 相对 no-CN 的差。
"""
import os
import sys

import cv2
import numpy as np

OUT = r"D:\AIWorkflow\tmp\Z-Image_ControlNet_冒烟_20261004"
GEN = os.path.join(OUT, "出图")
CTRL = {
    "hall": os.path.join(OUT, "hall_canny.png"),
    "p3a": os.path.join(OUT, "p3a_canny.png"),
}
# (标签, 组, 产物文件)
CASES = [
    ("hall 不挂控制(基线)", "hall", "zcn_hall_noCN_001_00001_.png"),
    ("hall canny s0.65", "hall", "zcn_hall_canny_s065_001_00001_.png"),
    ("hall canny s1.00", "hall", "zcn_hall_canny_s10_001_00001_.png"),
    ("hall canny s1.50", "hall", "zcn_hall_canny_s15_001_00001_.png"),
    ("p3a 不挂控制(基线)", "p3a", "zcn_p3a_noCN_001_00001_.png"),
    ("p3a canny s1.00", "p3a", "zcn_p3a_canny_s10_001_00001_.png"),
    ("p3a 灰模直喂 s0.80", "p3a", "zcn_p3a_gray_s08_001_00001_.png"),
]


def rd(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def edges(bgr):
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return cv2.Canny(g, 100, 200)


def dilate(mask, r):
    k = 2 * r + 1
    return cv2.dilate(mask, np.ones((k, k), np.uint8))


def blockden(m, n=16):
    d = cv2.resize((m > 0).astype(np.float32), (n, n), interpolation=cv2.INTER_AREA)
    return d.reshape(-1)


def pair_metrics(ctrl_e, out_e, r=3):
    c = ctrl_e > 0
    o = out_e > 0
    if c.sum() == 0 or o.sum() == 0:
        return float("nan"), float("nan")
    recall = float((c & dilate(out_e, r)).sum() / c.sum())
    precision = float((o & dilate(ctrl_e, r)).sum() / o.sum())
    return recall, precision


def layout_corr(a, b):
    x, y = blockden(a), blockden(b)
    if x.std() == 0 or y.std() == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def main():
    ctrl = {k: edges(rd(v)) for k, v in CTRL.items()}
    print("%-24s %-8s %-9s %-9s %-9s" % ("案例", "召回r3", "精确r3", "布局相关", "边缘密度比"))
    rows = []
    for label, grp, fn in CASES:
        p = os.path.join(GEN, fn)
        if not os.path.exists(p):
            print("%-24s 缺文件" % label)
            continue
        oe = edges(rd(p))
        ce = ctrl[grp]
        if oe.shape != ce.shape:
            oe = cv2.resize(oe, (ce.shape[1], ce.shape[0]), interpolation=cv2.INTER_NEAREST)
        rec, pre = pair_metrics(ce, oe)
        lay = layout_corr(ce, oe)
        dens = float((oe > 0).mean() / max(1e-6, (ce > 0).mean()))
        print("%-24s %-8.3f %-9.3f %-9.3f %-9.2f" % (label, rec, pre, lay, dens))
        rows.append((label, grp, rec, pre, lay))

    print("\n相对基线的净增益（同组内）：")
    for grp in ("hall", "p3a"):
        base = [r for r in rows if r[1] == grp and "基线" in r[0]]
        if not base:
            continue
        b = base[0]
        for r in rows:
            if r[1] == grp and "基线" not in r[0]:
                print("  %-22s Δ召回 %+.3f  Δ精确 %+.3f  Δ布局 %+.3f"
                      % (r[0], r[2] - b[2], r[3] - b[3], r[4] - b[4]))
    print("\n注：边缘密度比＝输出边缘占比／控制图边缘占比，≈1 说明没画出一堆控制图外的多余结构。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
