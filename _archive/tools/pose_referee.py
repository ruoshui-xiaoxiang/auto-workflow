#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pose_referee.py — 像素层裁判 v0：用"骨骼图重合度"量化控制通道锁不锁得住结构

思路（为什么这么绕）：
  SDPoseKeypointExtractor 要挂 MODEL+VAE（扩散模型）才能出 keypoints，太重；
  而 OpenposePreprocessor（DWPose，onnxruntime）已经在本地、也不需要扩散模型，
  它输出的是**画好骨架的图**。骨架图是 keypoints 的确定性渲染，
  所以"比两张骨架图的重合度" ≈ "比 keypoints"，只是多了一点检测噪声。
  → 用 IoU / 覆盖率 做第一次量化，不靠眼睛。

用法:
  py -3.12 pose_referee.py --ref 灰模帧.png --cand A.png --cand B.png
输出:
  ① 数值表（每个候选 vs 参考的 IoU、覆盖率、骨架像素占比）
  ② 对照图（参考 | 各候选，每张下面带自己的骨架图）
"""

import os, sys, json, time, shutil, argparse, urllib.request

import yaml
import numpy as np
from PIL import Image

CFG = r"D:\AIWorkflow\engine\config.yaml"
INPUT_DIR = r"D:\AIWorkflow\ComfyUI_H3\ComfyUI\input"
OUT_DIR = r"D:\AIWorkflow\ComfyUI_H3\output"


def base_url():
    with open(CFG, encoding="utf-8") as f:
        return yaml.safe_load(f)["comfyui"]["base_url"].rstrip("/")


def submit(base, graph):
    req = urllib.request.Request(
        f"{base}/prompt",
        data=json.dumps({"prompt": graph, "client_id": "pose_referee"}).encode(),
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())["prompt_id"]


def wait(base, pid, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(3)
        try:
            h = json.loads(urllib.request.urlopen(f"{base}/history/{pid}", timeout=15).read())
        except Exception:
            continue
        if pid in h:
            return h[pid]
    return None


def skeleton(base, img_name, tag):
    """跑一次 OpenposePreprocessor，返回写出的骨架图路径"""
    g = {
        "1": {"class_type": "LoadImage", "inputs": {"image": img_name}},
        "2": {"class_type": "OpenposePreprocessor",
              "inputs": {"image": ["1", 0], "detect_hand": "enable", "detect_body": "enable",
                         "detect_face": "enable", "resolution": 1024,
                         "scale_stick_for_xinsr_cn": "disable"}},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": f"skel_{tag}"}},
    }
    pid = submit(base, g)
    h = wait(base, pid)
    if not h:
        return None
    for node in (h.get("outputs") or {}).values():
        for im in (node.get("images") or []):
            p = os.path.join(OUT_DIR, im.get("subfolder", ""), im["filename"])
            if os.path.isfile(p):
                return p
    return None


def mask_of(path):
    """骨架图 → 布尔掩码（骨架是有色笔画，背景近黑）"""
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(np.int16)
    sat = a.max(axis=2) - a.min(axis=2)
    val = a.max(axis=2)
    return (sat > 40) & (val > 60)


def dilate(m, r):
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy > r * r:
                continue
            out |= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True, help="参考帧（previz/灰模帧）")
    ap.add_argument("--cand", action="append", required=True, help="候选出图，可多次")
    ap.add_argument("--tol", type=int, default=24, help="骨架重合容差（像素膨胀半径）")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    base = base_url()
    os.makedirs(INPUT_DIR, exist_ok=True)

    items = [("ref", a.ref)] + [(f"cand{i+1}", p) for i, p in enumerate(a.cand)]
    skels = {}
    for tag, p in items:
        if not os.path.isfile(p):
            print(f"缺文件: {p}"); sys.exit(2)
        name = f"referee_{tag}.png"
        shutil.copy2(p, os.path.join(INPUT_DIR, name))
        s = skeleton(base, name, tag)
        skels[tag] = s
        print(f"[骨架] {tag} -> {s}")

    if not skels.get("ref"):
        print("[!] 参考帧没跑出骨架图"); sys.exit(3)
    mref = mask_of(skels["ref"])
    print(f"\n参考骨架像素占比 {mref.mean()*100:.3f}%")
    if mref.sum() < 200:
        print("[!] 参考帧几乎提不出骨骼 —— 灰模/占位图 DWPose 认不出来。")
        print("    这条本身就是结论：像素层裁判不能用 DWPose 读 previz，要么换模型式姿态估计，要么 previz 渲得更拟人。")

    mref_d = dilate(mref, a.tol)
    rows = []
    for tag, p in items[1:]:
        s = skels.get(tag)
        if not s:
            rows.append((tag, None, None, None)); continue
        m = mask_of(s)
        inter = (m & mref_d).sum()
        cov = inter / max(mref.sum(), 1)              # 参考骨架被覆盖的比例
        iou = (m & mref).sum() / max((m | mref).sum(), 1)
        rows.append((tag, cov, iou, m.mean()))

    print(f"\n{'候选':10s} {'覆盖率':>8s} {'IoU':>8s} {'骨架占比':>9s}")
    for tag, cov, iou, dens in rows:
        if cov is None:
            print(f"{tag:10s}  (无骨架)"); continue
        print(f"{tag:10s} {cov*100:7.1f}% {iou*100:7.1f}% {dens*100:8.3f}%")
    print("\n覆盖率＝参考骨架有多少落在候选骨架的 ±%dpx 内；IoU＝直接重叠度。" % a.tol)

    # 对照图：原图 + 骨架图，逐行
    panels = []
    for tag, p in items:
        for path in (p, skels.get(tag)):
            if path and os.path.isfile(path):
                panels.append(Image.open(path).convert("RGB").resize((768, 432)))
    if panels:
        W, H = 768, 432
        sh = Image.new("RGB", (W, H * len(panels)), (16, 16, 16))
        for i, im in enumerate(panels):
            sh.paste(im, (0, i * H))
        out = a.out or os.path.join(OUT_DIR, "pose_referee_sheet.png")
        sh.save(out)
        print(f"[对照图] {out}（逐行：参考原图/参考骨架，候选1 原图/骨架，…）")


if __name__ == "__main__":
    main()
