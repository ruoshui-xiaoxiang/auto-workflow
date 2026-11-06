#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
temporal_referee.py — 时间维裁判（第 4 条）：量"漂不漂"

为什么需要它：边缘闸/骨架闸/深度闸全是**单帧**结构度量，没有一条量帧间。
而"漂移/闪烁"恰是 AI 为主路线的头号敌人（也是 DLSS 5 那套唯一把它当核心卖点的维度）。

三项指标（都不依赖新模型，OpenCV 就够）：
  flicker      帧间平均绝对差（越高越闪）
  flow_resid   光流对齐残差：用 t→t+1 的光流把 t warp 过去，与实际 t+1 比
               残差大 = 帧间不是"同一个东西在动"，而是画面在乱变（漂移）
  color_drift  全片逐帧平均色（RGB）的波动（越大越说明调子不稳）
  motion_curve 每对帧的平均光流幅度 → 运动节奏曲线（可跟参考片对齐，量"节奏复现"）

用法:
  py -3.12 temporal_referee.py --clip A.mp4 --clip B.mp4 [--ref R.mp4] [--fps 8]
"""

import os, sys, json, glob, shutil, argparse, subprocess, tempfile

import numpy as np
import cv2

FFMPEG = r"D:\AIWorkflow\tools\ffmpeg.exe"
W, H = 320, 180


def extract_frames(path, fps, dst):
    os.makedirs(dst, exist_ok=True)
    for f in glob.glob(os.path.join(dst, "*.png")):
        os.remove(f)
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-i", path,
           "-vf", f"fps={fps},scale={W}:{H}", "-y", os.path.join(dst, "f_%04d.png")]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"抽帧失败: {r.stderr.decode('utf-8', 'ignore')[:200]}")
    return sorted(glob.glob(os.path.join(dst, "f_*.png")))


def load(p):
    with open(p, "rb") as f:
        d = f.read()
    im = cv2.imdecode(np.frombuffer(d, np.uint8), cv2.IMREAD_COLOR)
    return im


def analyze(frames):
    g = [cv2.cvtColor(load(p), cv2.COLOR_BGR2GRAY).astype(np.float32) for p in frames]
    c = [load(p).astype(np.float32) for p in frames]
    flick, resid, motion = [], [], []
    for i in range(len(g) - 1):
        a, b = g[i], g[i + 1]
        flick.append(float(np.mean(np.abs(a - b))))
        flow = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        motion.append(float(np.mean(np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2))))
        h, w = a.shape
        xx, yy = np.meshgrid(np.arange(w), np.arange(h))
        mx = (xx + flow[..., 0]).astype(np.float32)
        my = (yy + flow[..., 1]).astype(np.float32)
        warped = cv2.remap(a, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        resid.append(float(np.mean(np.abs(warped - b))))
    means = [np.array([x[..., ch].mean() for ch in range(3)]) for x in c]
    col = float(np.std(np.stack(means), axis=0).mean())
    return {
        "n_frames": len(frames),
        "flicker": round(float(np.mean(flick)), 3) if flick else None,
        "flow_resid": round(float(np.mean(resid)), 3) if resid else None,
        "color_drift": round(col, 3),
        "motion_curve": [round(x, 3) for x in motion],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", action="append", required=True)
    ap.add_argument("--ref", default=None, help="参考片（如 previz 灰模），用来对齐节奏")
    ap.add_argument("--fps", type=int, default=8)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="tref_")
    res = {}
    print(f"{'片':38s} {'帧数':>5s} {'闪烁':>8s} {'光流残差':>9s} {'色漂':>7s} {'平均运动':>9s}")
    try:
        for p in a.clip:
            fr = extract_frames(p, a.fps, os.path.join(tmp, os.path.basename(p)))
            d = analyze(fr)
            mc = d["motion_curve"] or [0]
            res[os.path.basename(p)] = d
            print(f"{os.path.basename(p):38s} {d['n_frames']:5d} {d['flicker']:8.3f} "
                  f"{d['flow_resid']:9.3f} {d['color_drift']:7.3f} {np.mean(mc):9.3f}")

        if a.ref:
            fr = extract_frames(a.ref, a.fps, os.path.join(tmp, "_ref"))
            r = analyze(fr)
            res["__ref__"] = r
            print(f"\n--- 与参考片对齐（{os.path.basename(a.ref)}，{r['n_frames']} 帧）---")
            rc = np.array(r["motion_curve"])
            for k, d in res.items():
                if k in ("__ref__",):
                    continue
                mc = np.array(d["motion_curve"])
                n = min(len(rc), len(mc))
                if n < 4:
                    continue
                x, y = rc[:n], mc[:n]
                if x.std() < 1e-6 or y.std() < 1e-6:
                    continue
                corr = float(np.corrcoef(x, y)[0, 1])
                # 关键拍（运动峰值）时间点偏移
                pk_r, pk_c = int(np.argmax(x)), int(np.argmax(y))
                print(f"  {k:38s} 节奏相关 r={corr:6.3f}  峰位偏移={abs(pk_r-pk_c)}/{n} 帧"
                      f"（{(abs(pk_r-pk_c)/a.fps):.2f}s）")
                res[k]["rhythm_corr"] = round(corr, 3)
                res[k]["peak_offset_frames"] = abs(pk_r - pk_c)
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=2)
            print(f"\n[JSON] {a.out}")

        # 自动推荐：闪烁 + 光流残差 的加权（越小越稳）。供 best-of-N 自动挑用。
        cand = {k: v for k, v in res.items() if k != "__ref__" and v.get("flicker") is not None}
        if len(cand) >= 2:
            def score(v):
                return (v["flicker"] or 0) + (v["flow_resid"] or 0)
            w = min(cand.items(), key=lambda kv: score(kv[1]))
            print("\n--- 自动推荐（闪烁+光流残差 最小 = 最稳）---")
            for k, v in sorted(cand.items(), key=lambda kv: score(kv[1])):
                tag = "  ← 推荐" if k == w[0] else ""
                print(f"  {score(v):8.3f}  {k}{tag}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
