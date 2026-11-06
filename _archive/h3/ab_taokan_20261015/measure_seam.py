# -*- coding: utf-8 -*-
"""段间接缝双尺测量: 互相关 NCC + Farneback 光流幅度。
用法: py -3.12 measure_seam.py <out.json>
对三组对比各报一把尺:
  A) 现役s7尾巴 | 现役s8脑袋   (臂① 硬切 = 真出片)
  B) 链s7尾巴   | 接力s8脑袋   (臂② EXPT8 接力)
  C) 链s7尾巴   | 现役s8脑袋   (零成本诊断: 隔离"链内重生成s7"混杂)
每组: 接缝NCC / 两侧窗内lag-1 NCC基线; 接缝光流幅度 / 窗内lag-1光流基线。
接力输出若含22帧上下文前缀(166帧), 自动检测并剥除后再测。
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

OUT_DIR = Path(r"D:/AIWorkflow/ComfyUI_H3/output")
WORK = Path(r"D:/AIWorkflow/ComfyUI_H3/ab_taokan_20261015")
PROD_S7 = OUT_DIR / "ep1v2_s7.mp4"
PROD_S8 = OUT_DIR / "ep1v2_s8.mp4"
CHAIN = OUT_DIR / "minimax_h3_t8_long_video" / "ab_taokan_h768"
WIN = 12  # 0.5s @24fps
CTX = 22


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


def seam_stats(seg1, seg2):
    if seg1.shape[1:] != seg2.shape[1:]:  # 跨分辨率对比(链768×448 vs 现役736×416): 统一缩放
        h = min(seg1.shape[1], seg2.shape[1]) // 2 * 2
        w = min(seg1.shape[2], seg2.shape[2]) // 2 * 2
        sz = (w, h)
        seg1 = np.stack([cv2.resize(f, sz) for f in seg1])
        seg2 = np.stack([cv2.resize(f, sz) for f in seg2])
    a, b = seg1[-WIN:], seg2[:WIN]
    seam_ncc = ncc(gray(a[-1]), gray(b[0]))
    base = [ncc(gray(a[i]), gray(a[i + 1])) for i in range(WIN - 1)]
    base += [ncc(gray(b[i]), gray(b[i + 1])) for i in range(WIN - 1)]
    seam_flow = flow_mag(a[-1], b[0])
    fbase = [flow_mag(a[i], a[i + 1]) for i in range(WIN - 1)]
    fbase += [flow_mag(b[i], b[i + 1]) for i in range(WIN - 1)]
    win_ncc = float(np.mean([ncc(gray(a[i]), gray(b[i])) for i in range(WIN)]))
    mae = float(np.abs(gray(b[0]) - gray(a[-1])).mean())
    return {
        "seam_ncc": round(seam_ncc, 4),
        "baseline_ncc_mean": round(float(np.mean(base)), 4),
        "ncc_ratio": round(seam_ncc / max(np.mean(base), 1e-9), 3),
        "seam_flow": round(seam_flow, 3),
        "baseline_flow_mean": round(float(np.mean(fbase)), 3),
        "flow_ratio": round(seam_flow / max(np.mean(fbase), 1e-9), 3),
        "win_zero_lag_ncc": round(win_ncc, 4),
        "seam_mae": round(mae, 2),
    }


def strip_context_prefix(cont, parent_tail):
    """接力输出若含 ctx 前缀(帧数>新段长), 用与父尾末端帧的相关性定位真实起点。
    前缀末尾(cont[trim-5:trim])应≈父尾最后5帧 → trim=best_k+5。"""
    n = cont.shape[0]
    if n == 144:
        return cont, {"trimmed": 0, "frames": n}
    best_k, best_s = 0, -2.0
    probe = parent_tail[-5:]
    for k in range(0, min(CTX, n - 100)):
        s = np.mean([ncc(gray(cont[k + i]), gray(probe[i])) for i in range(5)])
        if s > best_s:
            best_k, best_s = k, s
    trim = best_k + 5
    info = {"trimmed": trim, "frames": n, "prefix_ncc": round(best_s, 4)}
    return cont[trim:], info


def main():
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else WORK / "seam_results.json"
    # 找链内 s7 candidate (manifest)
    manifest = json.loads((CHAIN / "manifest.json").read_text(encoding="utf-8"))
    segs = manifest["segments"] if "segments" in manifest else manifest
    entry = segs["0"] if isinstance(segs, dict) else segs[0]
    vp = Path(entry["video_path"])
    chain_s7 = vp if vp.is_absolute() else (CHAIN / vp)
    # 找接力 s8 输出
    cands = sorted(OUT_DIR.glob("AB_taokan_s8_cont*.mp4"),
                   key=lambda p: p.stat().st_mtime)
    if not cands:
        raise SystemExit("no AB_taokan_s8_cont*.mp4 found")
    cont_s8 = cands[-1]

    prod_s7 = read_video(PROD_S7)
    prod_s8 = read_video(PROD_S8)
    c_s7 = read_video(chain_s7)
    c_s8_raw = read_video(cont_s8)
    c_s8, trim_info = strip_context_prefix(c_s8_raw, c_s7)

    results = {
        "files": {"prod_s7": str(PROD_S7), "prod_s8": str(PROD_S8),
                  "chain_s7": str(chain_s7), "chain_s8": str(cont_s8)},
        "frame_counts": {"prod_s7": len(prod_s7), "prod_s8": len(prod_s8),
                         "chain_s7": len(c_s7), "chain_s8_raw": len(c_s8_raw),
                         "chain_s8_trimmed": len(c_s8)},
        "trim": trim_info,
        "A_prod_hardcut": seam_stats(prod_s7, prod_s8),
        "B_chain_continuation": seam_stats(c_s7, c_s8),
        "C_diag_chainS7_to_prodS8": seam_stats(c_s7, prod_s8),
    }
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
