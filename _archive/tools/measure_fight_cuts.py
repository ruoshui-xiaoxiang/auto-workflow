# -*- coding: utf-8 -*-
"""measure_fight_cuts.py · 自测：锐度/接缝/运动量（只读）"""
import json, subprocess, sys
from pathlib import Path

FF = r"D:\AIWorkflow\tools\ffmpeg.exe"
OUT = Path(r"D:\AIWorkflow\tmp\fight30v2\measure_out")
OUT.mkdir(parents=True, exist_ok=True)

def extract(video, tag, idxs):
    d = OUT / tag
    d.mkdir(exist_ok=True)
    for i in idxs:
        o = d / f"f{i:03d}.png"
        if not o.exists():
            subprocess.run([FF, "-y", "-i", str(video), "-vf", f"select=eq(n\\,{i})", "-vframes", "1", str(o)],
                           capture_output=True)
    return d

def sharpness(png):
    import cv2
    img = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    return float(cv2.Laplacian(img, cv2.CV_64F).var())

def mean_abs_diff(a, b):
    import cv2, numpy as np
    ia = cv2.imread(str(a), cv2.IMREAD_GRAYSCALE)
    ib = cv2.imread(str(b), cv2.IMREAD_GRAYSCALE)
    if ia is None or ib is None:
        return None
    if ia.shape != ib.shape:
        ib = cv2.resize(ib, (ia.shape[1], ia.shape[0]))
    return float(np.mean(cv2.absdiff(ia, ib)))

def shot_meta(p):
    # duration / size
    r = subprocess.run([FF, "-i", str(p)], capture_output=True, text=True)
    return r.stderr[-400:]

jobs = {
    "A_736": r"D:\AIWorkflow\ComfyUI_H3\output\r3f_s1_736.mp4",
    "B_tp": r"D:\AIWorkflow\ComfyUI_H3\output\r3f_s1_tp_00001_.mp4",
    "C_bunny": r"D:\AIWorkflow\ComfyUI_H3\output\r3f_s1_bunny_00001_.mp4",
    "D_tpbunny": r"D:\AIWorkflow\ComfyUI_H3\output\r3f_s1_tp_bunny_00001_.mp4",
    "s3c_4beat": r"D:\AIWorkflow\ComfyUI_H3\output\r3f_s3c_fast_00001_.mp4",
    "s3d_5beat": r"D:\AIWorkflow\ComfyUI_H3\output\r3f_s3d_5beat_00001_.mp4",
    "s3f_7beat": r"D:\AIWorkflow\ComfyUI_H3\output\r3f_s3f_draft7.mp4",
    "s3e_6beat": r"D:\AIWorkflow\ComfyUI_H3\output\r3f_s3e_draft6.mp4",
}
res = {}
idxs = [10, 40, 70, 100, 120]
for k, v in jobs.items():
    p = Path(v)
    if not p.exists():
        res[k] = {"missing": True}
        continue
    d = extract(p, k, idxs)
    sh = []
    for i in idxs:
        s = sharpness(d / f"f{i:03d}.png")
        if s is not None:
            sh.append(round(s, 1))
    res[k] = {"sharpness": sh, "sharp_mean": round(sum(sh)/len(sh), 1) if sh else None}

# 多镜接缝：hy / jm / chain
def joint_diffs(video, joints):
    # joints = list of frame idx near cut
    dtag = Path(video).stem
    vals = []
    for j in joints:
        d = extract(video, dtag + f"_j{j}", [j-1, j])
        a = d / f"f{j-1:03d}.png"
        b = d / f"f{j:03d}.png"
        vals.append(round(mean_abs_diff(a, b), 2))
    return vals

# 链式/独立/混接拼片均约 124*6
for name, path in [
    ("chain6", r"D:\AIWorkflow\tmp\fight30v2\chase\chase_draft_6shot_v6.mp4"),
    ("indep", r"D:\AIWorkflow\tmp\fight30v2\chase\chase_jm_independent.mp4"),
    ("hybrid", r"D:\AIWorkflow\tmp\fight30v2\chase\chase_hybrid_2x3.mp4"),
]:
    p = Path(path)
    if p.exists():
        # 切点约 124,248,372,496,620（若 124/镜）
        res[name] = {"joint_mad": joint_diffs(p, [124, 248, 372, 496, 620])}

print(json.dumps(res, ensure_ascii=False, indent=2))
(OUT / "measure_summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
