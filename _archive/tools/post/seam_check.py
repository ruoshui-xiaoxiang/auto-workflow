# -*- coding: utf-8 -*-
"""R11-02 接缝验收双尺（只报不拦，exit 恒 0）：互相关 NCC + Farneback 光流幅度。

对段边界（硬切或接力）取接缝两侧各 0.5s（12 帧@24fps）窗口：
  尺一 = 接缝帧对 NCC ÷ 窗内 lag-1 NCC 基线均值   （画面是否同一现场）
  尺二 = 接缝帧对光流幅值 ÷ 窗内 lag-1 光流基线均值（运动是否连续）
另报窗零延迟 NCC 与接缝 MAE。两把尺各自对比值，不跨尺比。

行口径（R11-02）：
  A_hardcut   --prev 尾 ↔ --next 头            （现役硬切基线）
  B_continuation --chain-prev 尾 ↔ --cont 剥前缀后头（接力臂）
  C_diag      --chain-prev 尾 ↔ --next 头       （隔离"重生成"混杂的零成本诊断）
跨分辨率对比行先统一缩放到两源较小边再量（比值口径不受画布差影响）。

用法：
  py -3.12 seam_check.py --prev s7.mp4 --next s8.mp4 --out r.json
  py -3.12 seam_check.py --prev s7.mp4 --next s8.mp4 --chain_prev chain_s7.mp4 --cont cont.mp4 --out r.json
续段输出若含上下文前缀，自动按与前段尾帧的相关性定位剥离（--ctx 可显式给帧数跳过检测）。
标定件：EP1v2 s7→s8（2026-10-15），复现读数见
  E:\\本地工作流规范手册\\20_通用规范层\\R11_段间接续生成.md R11-01/02。
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

WIN = 12  # 0.5s @24fps


def read_video(path):
    cap = cv2.VideoCapture(str(path))
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    if not frames:
        raise SystemExit(f"no frames: {path}")
    return np.stack(frames)


def gray(f):
    return cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float64)


def ncc(a, b):
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else 0.0


def flow_mag(a, b):
    g = cv2.calcOpticalFlowFarneback(
        gray(a).astype(np.uint8), gray(b).astype(np.uint8), None,
        0.5, 3, 15, 3, 5, 1.2, 0)
    return float(np.sqrt((g ** 2).sum(axis=-1)).mean())


def align_res(seg1, seg2):
    """跨分辨率对比：统一缩放到两源较小（偶数）边。"""
    if seg1.shape[1:] == seg2.shape[1:]:
        return seg1, seg2
    h = min(seg1.shape[1], seg2.shape[1]) // 2 * 2
    w = min(seg1.shape[2], seg2.shape[2]) // 2 * 2
    sz = (w, h)
    return (np.stack([cv2.resize(f, sz) for f in seg1]),
            np.stack([cv2.resize(f, sz) for f in seg2]))


def seam_stats(seg1, seg2):
    a, b = align_res(seg1[-WIN:], seg2[:WIN])
    seam_ncc = ncc(gray(a[-1]), gray(b[0]))
    base = [ncc(gray(a[i]), gray(a[i + 1])) for i in range(WIN - 1)]
    base += [ncc(gray(b[i]), gray(b[i + 1])) for i in range(WIN - 1)]
    seam_flow = flow_mag(a[-1], b[0])
    fbase = [flow_mag(a[i], a[i + 1]) for i in range(WIN - 1)]
    fbase += [flow_mag(b[i], b[i + 1]) for i in range(WIN - 1)]
    win_ncc = float(np.mean([ncc(gray(a[i]), gray(b[i])) for i in range(WIN)]))
    return {
        "seam_ncc": round(seam_ncc, 4),
        "baseline_ncc_mean": round(float(np.mean(base)), 4),
        "ncc_ratio": round(seam_ncc / max(np.mean(base), 1e-9), 3),
        "seam_flow": round(seam_flow, 3),
        "baseline_flow_mean": round(float(np.mean(fbase)), 3),
        "flow_ratio": round(seam_flow / max(np.mean(fbase), 1e-9), 3),
        "win_zero_lag_ncc": round(win_ncc, 4),
        "seam_mae": round(float(np.abs(gray(b[0]) - gray(a[-1])).mean()), 2),
    }


def strip_context_prefix(cont, prev_tail, ctx=None):
    """续段若含上下文前缀，按与前段尾末端帧的相关性定位剥离点；trim = best_k + 5。"""
    n = cont.shape[0]
    if ctx is not None:
        return cont[ctx:], {"trimmed": ctx, "frames": n, "mode": "explicit"}
    if n == prev_tail.shape[0] - (WIN - 1) * 2:  # 恰为新段长（无前缀）的常见口径
        pass
    probe = prev_tail[-5:]
    best_k, best_s = 0, -2.0
    # 搜索上限只要保证 k+5 不越界、剥完还剩得下测量窗即可；
    # 旧写法 min(24, n-100) 在短续段(<120帧)上只试 k=0，会剥错。
    for k in range(0, max(1, min(24, n - WIN - 5))):
        s = np.mean([ncc(gray(cont[k + i]), gray(probe[i])) for i in range(5)])
        if s > best_s:
            best_k, best_s = k, s
    trim = best_k + 5
    return cont[trim:], {"trimmed": trim, "frames": n,
                         "mode": "auto", "prefix_ncc": round(best_s, 4)}


def main():
    ap = argparse.ArgumentParser(description="R11-02 接缝双尺（只报不拦）")
    ap.add_argument("--prev", help="镜 N 成片（A 行左；缺省则不出 A 行）")
    ap.add_argument("--next", help="镜 N+1 成片（A 行右 / C 行右；缺省则不出 A/C 行）")
    ap.add_argument("--chain-prev", help="链内重生成的镜 N（B/C 行左；不给则只出 A 行）")
    ap.add_argument("--cont", help="EXPT8 续段输出（B 行右；须与 --chain-prev 同给）")
    ap.add_argument("--ctx", type=int, default=None,
                    help="续段上下文前缀帧数（缺省自动检测）")
    ap.add_argument("--out", help="结果 JSON 落盘路径（缺省只打印）")
    a = ap.parse_args()

    prev = read_video(a.prev) if a.prev else None
    nxt = read_video(a.next) if a.next else None
    if prev is None and not (a.chain_prev and a.cont):
        raise SystemExit("至少要给 --prev/--next（A 行）或 --chain-prev+--cont（B 行）")
    res = {
        "tool": "seam_check.py (R11-02)",
        "files": {"prev": a.prev, "next": a.next,
                  "chain_prev": a.chain_prev, "cont": a.cont},
        "frame_counts": {"prev": len(prev) if prev is not None else None,
                         "next": len(nxt) if nxt is not None else None},
    }
    if prev is not None and nxt is not None:
        res["A_hardcut"] = seam_stats(prev, nxt)
    if a.chain_prev:
        chain_prev = read_video(a.chain_prev)
        res["frame_counts"]["chain_prev"] = len(chain_prev)
        if a.cont:
            cont = read_video(a.cont)
            cont_t, trim = strip_context_prefix(cont, chain_prev, a.ctx)
            res["frame_counts"]["cont_raw"] = len(cont)
            res["frame_counts"]["cont_trimmed"] = len(cont_t)
            res["trim"] = trim
            res["B_continuation"] = seam_stats(chain_prev, cont_t)
        if nxt is not None:
            res["C_diag"] = seam_stats(chain_prev, nxt)

    text = json.dumps(res, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
