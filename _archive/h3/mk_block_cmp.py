# -*- coding: utf-8 -*-
"""生成「原片 vs 复刻」站位对比图：同一拍位，上排=原片，下排=复刻。
按每段累计起始时间对齐取帧（两片总时长不等，不能按全局秒数硬对）。
原片路径含 emoji/中文 → 一律用 ffmpeg（list 参数直传 Unicode）抽帧，再读 PNG。
用法: py mk_block_cmp.py
"""
import os, subprocess, sys, tempfile
import cv2
import numpy as np

FF = r"D:\AIWorkflow\tools\ffmpeg.exe"
SRC = r"C:\Users\若水\Desktop\无音_复刻参考片段\【45】张凌赫甘愿受刑108鞭🥺也不肯和田曦薇一刀两断！｜ 逐玉 Pursuit of Jade ｜ ✦ 爱奇艺东方奇幻 ✦.mp4"
REPLICA = r"D:\AIWorkflow\ComfyUI_H3\output\复刻_逐玉_247-289.mp4"
OUT = r"D:\AIWorkflow\ComfyUI_H3\output\_站位对比.jpg"
TMP = tempfile.mkdtemp(prefix="blockcmp_")

T0 = 247.12  # 原片整段起点（绝对秒）

# (名字, 原片段时长s, 复刻帧数)
SEGS = [
    ("seg01", 7.12, 158),
    ("seg02", 7.64, 175),
    ("seg03", 4.48, 107),
    ("seg04", 4.44, 107),
    ("seg05", 4.28,  90),
    ("seg06", 3.04,  73),
    ("seg07", 4.84, 107),
    ("seg08", 6.08, 141),
]

W = 480  # 每格宽

def starts():
    o, r = [], []
    co = cr = 0.0
    for _, dur, fr in SEGS:
        o.append(co); r.append(cr)
        co += dur
        cr += fr / 24.0
    return o, r

def grab_ff(video, t, tag):
    """用 ffmpeg 精确抽一帧（-ss 放 -i 后保证精确到该时间点）"""
    p = os.path.join(TMP, tag + ".png")
    cmd = [FF, "-y", "-v", "error", "-i", video, "-ss", "%.3f" % t,
           "-frames:v", "1", p]
    r = subprocess.run(cmd, capture_output=True)
    if not os.path.exists(p):
        raise RuntimeError("抽帧失败 %s @%.2fs: %s" % (video, t,
                           r.stderr.decode("utf-8", "ignore")[:300]))
    img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("解码失败: " + p)
    h = int(img.shape[0] * W / img.shape[1])
    return cv2.resize(img, (W, h), interpolation=cv2.INTER_AREA)

def label(img, text):
    out = img.copy()
    cv2.rectangle(out, (0, 0), (out.shape[1], 32), (0, 0, 0), -1)
    cv2.putText(out, text, (8, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (255, 255, 255), 2, cv2.LINE_AA)
    return out

def main():
    o_st, r_st = starts()
    # 3 个拍位：seg03 中段（双人）、seg05 中段（单人）、seg07 中段（双人）
    picks = [(2, "配对点A"), (4, "配对点B"), (6, "配对点C")]

    orig_row, rep_row = [], []
    for seg_i, name in picks:
        odur = SEGS[seg_i][1]
        to = T0 + o_st[seg_i] + odur * 0.5
        tr = r_st[seg_i] + odur * 0.5
        a = grab_ff(SRC, to, "o%d" % seg_i)
        b = grab_ff(REPLICA, tr, "r%d" % seg_i)
        orig_row.append(label(a, "原片  %.1fs" % to))
        rep_row.append(label(b, "复刻  %.1fs" % tr))

    grid = np.vstack([np.hstack(orig_row), np.hstack(rep_row)])
    ok, buf = cv2.imencode(".jpg", grid, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    buf.tofile(OUT)
    print("写出:", OUT, grid.shape, flush=True)

main()
