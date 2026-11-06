# -*- coding: utf-8 -*-
"""成片运动画像（留痕期，只报警不拦批）。

两把尺成对用（2026-10-07 第 1 集 32 镜实测教训）：
  speed     = 逐帧平均位移（量"速度"）
  amplitude = lag 12 帧≈0.5 秒的平均位移（量"幅值"）
口径：736×416 强制拉伸 + Farneback(0.5,3,15,3,5,1.2,0)，与 motion_ab.py 一致。
逐帧单尺会把慢速连续运动（说话、缓缓抬头）误判成冻结——32 镜里 15 条如此、真静止只有 1 条。
判定：双低=真静止；speed 低 amplitude 够=慢速连续；否则=明显运动。
竖屏素材拉伸各向异性约 3.1 倍，跨项目对比前必须重声明口径。
"""
import cv2
import numpy as np

GRID = (736, 416)
FROZEN = 0.35
LAG = 12


def profile(path):
    c = cv2.VideoCapture(str(path))
    fs = []
    while True:
        ok, f = c.read()
        if not ok:
            break
        fs.append(f)
    c.release()
    if len(fs) < LAG + 2:
        return None
    g = [cv2.cvtColor(cv2.resize(f, GRID, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
         for f in fs]

    def flow(lag):
        out = []
        for i in range(len(g) - lag):
            fl = cv2.calcOpticalFlowFarneback(g[i], g[i + lag], None, 0.5, 3, 15, 3, 5, 1.2, 0)
            out.append(float(np.mean(np.sqrt(fl[..., 0] ** 2 + fl[..., 1] ** 2))))
        return np.array(out)

    sp, am = flow(1), flow(LAG)
    if sp.mean() < FROZEN and am.mean() < FROZEN:
        verdict = "真静止"
    elif sp.mean() < FROZEN:
        verdict = "慢速连续"
    else:
        verdict = "明显运动"
    return dict(speed=round(float(sp.mean()), 3),
                speed_frozen_pct=round(float((sp < FROZEN).mean()) * 100, 1),
                amplitude=round(float(am.mean()), 3),
                amplitude_min=round(float(am.min()), 3),
                amplitude_frozen_pct=round(float((am < FROZEN).mean()) * 100, 1),
                verdict=verdict, frames=len(fs),
                ruler="736x416拉伸+Farneback(0.5,3,15,3,5,1.2,0)；lag1=速度，lag12=幅值；alarm_only")
