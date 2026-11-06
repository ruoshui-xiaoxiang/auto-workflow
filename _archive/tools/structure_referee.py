#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
structure_referee.py — 结构裁判 v1：Canny 边缘重合度

背景：DWPose 读不出灰模（灰模不是人），所以"骨骼重合度"没法拿灰模当参考。
但**灰模的边缘是能提的**（Canny 只看梯度，不看人）。于是：
  参考 = Canny(previz 灰模帧)
  候选 = Canny(生成结果)
  比 = 参考边缘有多少被候选边缘覆盖（覆盖率）+ 直接 IoU

它直接回答"灰模的结构被生成结果锁住多少"，而且纯 OpenCV、不需要 ComfyUI、不需要骨骼。

用法:
  py -3.12 structure_referee.py --ref 灰模帧.png --cand A.png --cand B.png [--tol 6]
"""

import os, sys, argparse
import numpy as np
import cv2


def edge_mask(path, size, lo=100, hi=200):
    # 中文路径：cv2.imread 和 np.fromfile 都不可靠，用 open('rb') + np.frombuffer
    with open(path, "rb") as f:
        data = f.read()
    im = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if im is None:
        return None
    im = cv2.resize(im, size, interpolation=cv2.INTER_AREA)
    e = cv2.Canny(im, lo, hi)
    return (e > 0).astype(np.uint8)


def dilate(m, r):
    k = np.ones((2 * r + 1, 2 * r + 1), np.uint8)
    return cv2.dilate(m, k, iterations=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True)
    ap.add_argument("--cand", action="append", required=True)
    ap.add_argument("--tol", type=int, default=6)
    ap.add_argument("--size", default="1024x576")
    a = ap.parse_args()
    w, h = (int(x) for x in a.size.split("x"))
    size = (w, h)

    ref = edge_mask(a.ref, size)
    if ref is None or ref.sum() < 50:
        print("[!] 参考帧提不出边缘（可能不是有效的灰模帧）")
        sys.exit(3)
    ref_d = dilate(ref, a.tol)
    ref_cnt = ref.sum()

    print(f"参考边缘像素 {ref_cnt}（占比 {ref.mean()*100:.2f}%）\n")
    print(f"{'候选':24s} {'覆盖率':>8s} {'IoU':>8s} {'边缘密度':>9s}")
    panels = []
    rows = []
    for i, p in enumerate(a.cand):
        m = edge_mask(p, size)
        if m is None:
            print(f"{os.path.basename(p):24s}  (读不出)"); continue
        cov = (ref & dilate(m, a.tol)).sum() / ref_cnt
        iou = (ref & m).sum() / max((ref | m).sum(), 1)
        dens = m.mean()
        rows.append((os.path.basename(p), cov, iou, dens, m))
        print(f"{os.path.basename(p):24s} {cov*100:7.1f}% {iou*100:7.1f}% {dens*100:8.2f}%")

    print(f"\n覆盖率＝参考边缘有百分之几落在候选边缘 ±{a.tol}px 内（越高＝结构锁得越牢）")
    print("IoU＝直接重叠度（受候选新增边缘影响，会偏低，看相对值）")

    # 出图：参考 Canny + 各候选 Canny 拼一行
    rv = (ref * 255).astype(np.uint8)
    rv = cv2.cvtColor(rv, cv2.COLOR_GRAY2BGR)
    strip = [rv]
    for _, _, _, _, m in rows:
        v = (m * 255).astype(np.uint8)
        strip.append(cv2.cvtColor(v, cv2.COLOR_GRAY2BGR))
    sheet = np.hstack(strip)
    out = a.ref.rsplit("/", 1)[-1].replace(".png", "_edges.png")
    out = os.path.join(os.path.dirname(a.cand[0]), out)
    # cv2.imwrite 也写不了中文路径，用 imencode + tofile
    ok, buf = cv2.imencode(".png", sheet)
    if ok:
        buf.tofile(out)
    print(f"\n[边缘图] {out}（从左到右：参考 / 各候选）" + ("" if ok else " [写入失败]"))


if __name__ == "__main__":
    main()
