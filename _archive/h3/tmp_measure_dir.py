# -*- coding: utf-8 -*-
"""量垂直运动方向：上半画面 Farneback 光流 dy 均值。dy>0 = 画面内容向下（下降感）"""
import sys, cv2, numpy as np

for path in sys.argv[1:]:
    cap = cv2.VideoCapture(path)
    g = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        g.append(cv2.cvtColor(cv2.resize(f, (736, 416)), cv2.COLOR_BGR2GRAY))
    cap.release()
    dys, mags = [], []
    for i in range(1, len(g)):
        flow = cv2.calcOpticalFlowFarneback(g[i-1], g[i], None, 0.5, 3, 15, 3, 5, 1.2, 0)
        top = flow[:249]                      # 上 60%：鲲所在区域
        dys.append(float(top[..., 1].mean()))
        mags.append(float(np.sqrt(top[..., 0]**2 + top[..., 1]**2).mean()))
    dys = np.array(dys); mags = np.array(mags)
    # 逐秒看方向漂移
    per = [dys[i:i+24].mean() for i in range(0, len(dys), 24)]
    print(f"{path.split('/')[-1]:12s} dy_mean={dys.mean():+.4f} |dy|/mag={abs(dys.mean())/max(mags.mean(),1e-9):.2f} "
          f"down_frames={int((dys>0).sum())}/{len(dys)}")
    print("   每秒 dy:", " ".join(f"{v:+.3f}" for v in per))
