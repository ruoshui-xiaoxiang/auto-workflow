#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""整幕轴线审计（第二版，修了两处量错的地方）。

朝向：鼻尖相对两眼中点的水平偏移 **除以脸宽**（旧版除瞳距，侧脸时瞳距趋零，
数值会炸到十几，不可用）。负=转向画面左，正=转向画面右。
位移：按"从左到右第几个人"分槽跟踪，各槽单独算 x 跨度（旧版把所有人混在一起
取 max-min，双人镜天然就有 0.35 的跨度，等于没测）。

用法：py h3_axis_audit.py <视频1> ...
"""
import sys, os, cv2, numpy as np

YUNET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "yunet.onnx")
SAMPLES = 7


def detect(im):
    h, w = im.shape[:2]
    det = cv2.FaceDetectorYN.create(YUNET, "", (w, h), 0.6, 0.3, 5000)
    _, f = det.detect(im)
    out = []
    if f is None:
        return out
    for row in f:
        x, y, fw, fh = [float(v) for v in row[:4]]
        e1x, e1y, e2x, e2y, nx, ny = [float(v) for v in row[5:11]]
        emx = (e1x + e2x) / 2.0
        out.append({"cx": (x + fw / 2) / w, "scale": fh / h,
                    "yaw": max(-1.0, min(1.0, (nx - emx) / max(1.0, fw)))})
    return sorted(out, key=lambda d: d["cx"])


def bg_flow(prev_g, g):
    pts = cv2.goodFeaturesToTrack(prev_g, maxCorners=250, qualityLevel=0.01, minDistance=12)
    if pts is None or len(pts) < 10:
        return 0.0
    nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev_g, g, pts, None, winSize=(21, 21), maxLevel=3)
    if nxt is None:
        return 0.0
    good = (st.ravel() == 1)
    if good.sum() < 8:
        return 0.0
    return float(np.median((nxt.reshape(-1, 2)[:, 0] - pts.reshape(-1, 2)[:, 0])[good]))


def audit(path):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    ok, first = cap.read()
    cap.release()
    if not ok:
        print("!! 打不开 %s" % path)
        return
    h, w = first.shape[:2]
    marks = [min(max(0, int(total * k / (SAMPLES - 1.0))), total - 2) for k in range(SAMPLES)]

    rows = []
    for m in marks:
        c = cv2.VideoCapture(path)
        c.set(cv2.CAP_PROP_POS_FRAMES, m)
        r, im = c.read()
        c.release()
        rows.append((m / fps, detect(im) if r else []))

    cap = cv2.VideoCapture(path)
    ok, p = cap.read()
    pg = cv2.cvtColor(p, cv2.COLOR_BGR2GRAY)
    cum = 0.0
    while True:
        ok, im = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        cum += bg_flow(pg, g)
        pg = g
    cap.release()

    tag = os.path.basename(path)
    sid = tag.split("H3_")[1][:3] if "H3_" in tag else tag[:6]
    counts = [len(fs) for _, fs in rows]
    print("\n### %s  %.1fs  人数采样=%s  背景位移 %+.1f%%宽"
          % (sid, total / fps, counts, 100 * cum / w))

    slots = max(counts) if counts else 0
    for k in range(min(slots, 2)):
        xs = [fs[k]["cx"] for _, fs in rows if len(fs) > k]
        ys = [fs[k]["yaw"] for _, fs in rows if len(fs) > k]
        sc = [fs[k]["scale"] for _, fs in rows if len(fs) > k]
        if len(xs) < 3:
            continue
        head = "  左起第%d人: x %.2f→%.2f (跨度 %.3f)  尺寸 %.3f→%.3f  朝向 %+.2f→%+.2f" % (
            k + 1, xs[0], xs[-1], max(xs) - min(xs), sc[0], sc[-1], ys[0], ys[-1])
        swing = max(ys) - min(ys)
        if swing > 0.35:
            head += "  朝向中途摆动 %.2f" % swing
        print(head)
        print("     x 轨迹 " + " ".join("%.2f" % v for v in xs))
        print("     朝向轨迹 " + " ".join("%+.2f" % v for v in ys))

    cam_moving = abs(cum) > 0.06 * w
    if cam_moving:
        print("  ⚠ 镜头在移动（背景累计 %.1f%%画宽）" % (100 * cum / w))
    for k in range(min(slots, 2)):
        xs = [fs[k]["cx"] for _, fs in rows if len(fs) > k]
        if len(xs) > 2 and not cam_moving and (max(xs) - min(xs)) > 0.08:
            print("  ⚠ 第%d人自己横移 %.3f 画宽（背景基本静止）" % (k + 1, max(xs) - min(xs)))
    if max(counts or [0]) > 2:
        print("  ⚠ 有 %d 个采样点检出 3 张以上人脸（疑似多出人）" % sum(1 for c in counts if c > 2))


if __name__ == "__main__":
    for p in sys.argv[1:]:
        audit(p)
