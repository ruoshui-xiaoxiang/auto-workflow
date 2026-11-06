#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对照实验量尺：锚点帧 vs 各条成片的开场站位、全程漂移、人数。

用法：py h3_chain_compare.py <锚点png> <视频1> [视频2 ...]
每人每镜输出：采样点上的人脸数与中心 x（按 x 排序后与锚点逐一配对），
以及背景光流累计位移（镜头是否自己动了）。开场偏差越小 = 续跑接得越准。
"""
import sys, os, cv2, numpy as np

YUNET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "yunet.onnx")


def faces_at(det, img):
    _, f = det.detect(img)
    if f is None or len(f) == 0:
        return []
    h, w = img.shape[:2]
    return sorted([(b[0] + b[2] / 2) / w for b in ([list(map(float, x[:4])) for x in f])])


def bg_drift(prev_g, g):
    pts = cv2.goodFeaturesToTrack(prev_g, maxCorners=300, qualityLevel=0.01, minDistance=12)
    if pts is None or len(pts) < 10:
        return 0.0
    nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev_g, g, pts, None, winSize=(21, 21), maxLevel=3)
    if nxt is None:
        return 0.0
    good = (st.ravel() == 1)
    if good.sum() < 8:
        return 0.0
    return float(np.median((nxt.reshape(-1, 2)[:, 0] - pts.reshape(-1, 2)[:, 0])[good]))


def video_report(path, anchor_centers):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    ok, first = cap.read()
    if not ok:
        print("!! 打不开 %s" % path)
        return
    h, w = first.shape[:2]
    det = cv2.FaceDetectorYN.create(YUNET, "", (w, h), 0.6, 0.3, 5000)
    marks = sorted({0, int(total * .25), int(total * .5), int(total * .75), max(0, total - 2)})
    got = {}
    for m in marks:
        cap.set(cv2.CAP_PROP_POS_FRAMES, m)
        r, fr = cap.read()
        if r:
            got[m] = faces_at(det, fr)

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    prev = None
    cum = 0.0
    counts = []
    idx = 0
    while True:
        r, fr = cap.read()
        if not r:
            break
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        if prev is not None and idx % 4 == 0:
            cum += bg_drift(prev, g)
        prev = g
        idx += 1
    cap.release()

    name = os.path.basename(path)
    print("\n%s  (%dx%d, %.1fs)" % (name, w, h, total / fps))
    for m in marks:
        cs = got.get(m, [])
        off = ""
        if len(cs) == len(anchor_centers) and anchor_centers:
            d = [round(a - b, 3) for a, b in zip(cs, anchor_centers)]
            off = "  与锚点偏差 " + "/".join("%+.3f" % x for x in d)
        print("  帧%-4d t=%.2fs  人数=%d  中心x=%s%s"
              % (m, m / fps, len(cs), " ".join("%.2f" % c for c in cs) or "-", off))
    print("  背景累计位移 %+.1fpx (%+.1f%%宽)  人数最多=%d"
          % (cum, 100 * cum / w, max([len(v) for v in got.values()] or [0])))


if __name__ == "__main__":
    anchor_path, vids = sys.argv[1], sys.argv[2:]
    im = cv2.imdecode(np.fromfile(anchor_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    h, w = im.shape[:2]
    det = cv2.FaceDetectorYN.create(YUNET, "", (w, h), 0.6, 0.3, 5000)
    ac = faces_at(det, im)
    print("锚点 %s  人数=%d  中心x=%s" % (os.path.basename(anchor_path), len(ac),
                                          " ".join("%.2f" % c for c in ac)))
    for v in vids:
        video_report(v, ac)
