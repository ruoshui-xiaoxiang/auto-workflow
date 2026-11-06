#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
depth_referee.py — 深度对深度裁判 v1（估计器一致）

背景：边缘度量对 depth 腿不公平（depth 是平滑渐变、没有硬边缘，37.8% 被低估）。
公平的裁判是"深度对深度"：用同一个深度估计器（DepthAnythingV2）对灰模参考和各条
出图各估一次相对深度，再比空间布局的相似度。

- 参考深度 = DA2(灰模帧)
- 候选深度 = DA2(出图结果)
- 度量 = 两者归一化到 [0,1] 后的 Pearson 相关 + L1 差

（注：这不是 Godot 的"真深度"，而是"估计器一致"的深度；Godot 真深度是下一步升级，
它涉及绝对→相对尺度换算。本版已能公平回答"哪条通道更保住灰模的空间层次"。）

用法:
  py -3.12 depth_referee.py --ref 灰模.png --cand A.png --cand B.png ...
"""

import os, sys, json, time, shutil, argparse, urllib.request

import numpy as np
import cv2
import yaml

CFG = r"D:\AIWorkflow\engine\config.yaml"
INPUT_DIR = r"D:\AIWorkflow\ComfyUI_H3\ComfyUI\input"
OUT_DIR = r"D:\AIWorkflow\ComfyUI_H3\output"


def base_url():
    with open(CFG, encoding="utf-8") as f:
        return yaml.safe_load(f)["comfyui"]["base_url"].rstrip("/")


def submit(base, graph):
    req = urllib.request.Request(
        f"{base}/prompt",
        data=json.dumps({"prompt": graph, "client_id": "depth_referee"}).encode(),
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


def run_depth(base, img_name, tag):
    g = {
        "1": {"class_type": "LoadImage", "inputs": {"image": img_name}},
        "2": {"class_type": "DepthAnythingV2Preprocessor",
              "inputs": {"image": ["1", 0], "ckpt_name": "depth_anything_v2_vitl.pth",
                         "resolution": 1024}},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": f"dep_{tag}"}},
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


def read_gray(path, size):
    with open(path, "rb") as f:
        data = f.read()
    im = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if im is None:
        return None
    return cv2.resize(im, size, interpolation=cv2.INTER_AREA)


def norm01(m):
    mn, mx = m.min(), m.max()
    if mx - mn < 1e-6:
        return np.zeros_like(m, dtype=np.float32)
    return (m.astype(np.float32) - mn) / (mx - mn)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True)
    ap.add_argument("--cand", action="append", required=True)
    a = ap.parse_args()

    base = base_url()
    os.makedirs(INPUT_DIR, exist_ok=True)

    # 把图放进 input
    names = {}
    for tag, p in [("ref", a.ref)] + [(f"cand{i+1}", p) for i, p in enumerate(a.cand)]:
        if not os.path.isfile(p):
            print("缺文件:", p); sys.exit(2)
        n = f"depref_{tag}.png"
        shutil.copy2(p, os.path.join(INPUT_DIR, n))
        names[tag] = n

    # 逐张估深度
    dep = {}
    for tag, n in names.items():
        d = run_depth(base, n, tag)
        dep[tag] = d
        print(f"[深度] {tag} -> {d}")

    ref = read_gray(dep["ref"], (512, 288))
    if ref is None:
        print("[!] 参考深度没跑出来"); sys.exit(3)
    ref_n = norm01(ref)

    print(f"\n{'候选':24s} {'相关(r)':>9s} {'L1差':>9s}")
    rows = []
    for i, p in enumerate(a.cand):
        tag = f"cand{i+1}"
        m = read_gray(dep.get(tag), (512, 288))
        if m is None:
            print(f"{os.path.basename(p):24s}  (无深度)"); continue
        m_n = norm01(m)
        r = float(np.corrcoef(ref_n.ravel(), m_n.ravel())[0, 1])
        l1 = float(np.mean(np.abs(ref_n - m_n)))
        rows.append((os.path.basename(p), r, l1))
        print(f"{os.path.basename(p):24s} {r:9.3f} {l1:9.3f}")

    print("\n相关 r 越接近 1 = 空间层次越一致；L1 越小 = 越接近参考深度。")

    # 出图：参考深度 + 各候选深度 拼一行
    strip = [cv2.cvtColor(ref, cv2.COLOR_GRAY2BGR)]
    for i in range(len(a.cand)):
        m = read_gray(dep.get(f"cand{i+1}"), (512, 288))
        strip.append(cv2.cvtColor(m if m is not None else np.zeros_like(ref), cv2.COLOR_GRAY2BGR))
    sheet = np.hstack(strip)
    out = os.path.join(os.path.dirname(a.cand[0]), "对照_深度_各通道.png")
    ok, buf = cv2.imencode(".png", sheet)
    if ok:
        buf.tofile(out)
    print(f"\n[深度图] {out}（从左到右：参考 / 各候选）")


if __name__ == "__main__":
    main()
