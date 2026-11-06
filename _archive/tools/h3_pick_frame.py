#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从一条成片里挑"最稳的一帧"当下一镜的开场锚。

打分项（都要，缺一个就扣分）：
  * 两张脸都在画内，且离左右边有安全余量
  * 背景光流静止（镜头没在漂）
  * 拉普拉斯清晰度高（不是运动模糊帧）
  * 时间上偏后：越接近结尾越能接得上，但只在后 45% 里挑

用法：py h3_pick_frame.py <视频> <输出 png> [--tail 0.45] [--step 2]
"""
import sys, os, cv2, numpy as np

YUNET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "yunet.onnx")


def pick(video, out_png, tail=0.45, step=2):
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    ret, first = cap.read()
    if not ret:
        print("打不开视频")
        return 1
    h, w = first.shape[:2]
    det = cv2.FaceDetectorYN.create(YUNET, "", (w, h), 0.6, 0.3, 5000)
    start = int(total * (1.0 - tail))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)

    prev_g, idx, rows = None, start, []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if idx % step:
            idx += 1
            continue
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        _, faces = det.detect(fr)
        faces = [] if faces is None else faces
        flow = 0.0
        if prev_g is not None and len(faces):
            pts = cv2.goodFeaturesToTrack(prev_g, maxCorners=300, qualityLevel=0.01, minDistance=12)
            if pts is not None and len(pts) > 10:
                nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev_g, g, pts, None, winSize=(21, 21), maxLevel=3)
                if nxt is not None:
                    good = (st.ravel() == 1)
                    if good.sum() > 8:
                        flow = float(np.median(np.abs((nxt.reshape(-1, 2)[:, 0] - pts.reshape(-1, 2)[:, 0])[good])))
        sharp = float(cv2.Laplacian(g, cv2.CV_64F).var())
        boxes = [[float(v) for v in f[:4]] for f in faces]
        inside = [b for b in boxes if b[0] > w * 0.04 and b[1] > h * 0.04
                  and b[0] + b[2] < w * 0.96 and b[1] + b[3] < h * 0.96]
        score = (2.0 * len(inside)
                 - 0.35 * flow
                 + min(sharp, 900.0) / 300.0
                 + 0.6 * (idx - start) / max(1, total - start))
        rows.append((score, idx, len(inside), flow, sharp, boxes))
        prev_g = g
        idx += 1
    cap.release()
    if not rows:
        print("没有可用帧")
        return 1
    rows.sort(key=lambda r: -r[0])
    score, n, nf, flow, sharp, boxes = rows[0]
    cap = cv2.VideoCapture(video)
    cap.set(cv2.CAP_PROP_POS_FRAMES, n)
    ok, fr = cap.read()
    cap.release()
    if not ok:
        print("回读失败")
        return 1
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    ok_enc, buf = cv2.imencode(os.path.splitext(out_png)[1], fr)
    if not ok_enc:
        print("编码失败")
        return 1
    with open(out_png, "wb") as f:
        f.write(buf.tobytes())
    if not os.path.isfile(out_png) or os.path.getsize(out_png) == 0:
        print("落盘校验失败: %s" % out_png)
        return 1
    print("选中 帧%d  t=%.2fs  在画脸=%d/%d  背景位移=%.2fpx  清晰度=%.0f  得分=%.2f"
          % (n, n / fps, nf, max(len(b) for b in [boxes]) if boxes else 0, flow, sharp, score))
    print("中心 x 归一化: " + " ".join("%.2f" % ((b[0] + b[2] / 2) / w) for b in boxes))
    print("落盘: %s  (%dx%d)" % (out_png, fr.shape[1], fr.shape[0]))
    print("候选前五: " + " ".join("帧%d/%.2f" % (r[1], r[0]) for r in rows[:5]))
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    tail = 0.45
    step = 2
    if "--tail" in a:
        i = a.index("--tail"); tail = float(a[i + 1]); del a[i:i + 2]
    if "--step" in a:
        i = a.index("--step"); step = int(a[i + 1]); del a[i:i + 2]
    sys.exit(pick(a[0], a[1], tail, step))
