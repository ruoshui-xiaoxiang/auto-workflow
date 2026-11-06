#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
annotate_shot.py — 逐帧出图 → 裁判打分 → 标废片（previz 结构标注流程）

把「灰模关键帧 → lineart 锁构图出图 → 裁判打分 → 标废片」固化成一个可复跑的命令。
这是裁判层（L3）从"一次性实验"变成"生产 QC 门"的那一步：机器先筛，人只看标红的。

流程（每帧）：
  1. 灰模关键帧 → Canny 提边 → FLUX ControlNet lineart 出图（ComfyUI）
  2. 边缘覆盖率打分（纯 OpenCV，快）—— 结构锁住没有
  3. 低于阈值 → 标「废片」，进 contact sheet 红框标出
  可选 --skeleton：再跑 DWPose 骨架闸（检测有没有人形，慢，逐帧 +~15s）

产物：
  annotations.csv —— 帧号 / 边缘覆盖率 / 骨架占比 / 判定 / 产物路径
  contact_sheet.png —— 逐帧「灰模帧 | 出图」，废片红框标出

用法：
  py -3.12 annotate_shot.py --frames "<灰模帧通配>" --prompt "<提示词>" --out <输出目录> [--threshold 0.3] [--skeleton]
"""

import os, sys, csv, json, time, shutil, argparse, urllib.request, glob

import numpy as np
import cv2
import yaml
from PIL import Image, ImageDraw

CFG = r"D:\AIWorkflow\engine\config.yaml"
INPUT_DIR = r"D:\AIWorkflow\ComfyUI_H3\ComfyUI\input"
OUT_DIR = r"D:\AIWorkflow\ComfyUI_H3\output"
MODEL = "flux1-dev-fp8.safetensors"
CLIP1, CLIP2 = "clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors"
VAE = "flux-vae-bf16.safetensors"
CN = "FLUX.1-dev-ControlNet-Union-Pro-fp8.safetensors"


def _flux_line_alive(base="http://127.0.0.1:8189"):
    """FLUX 线还在不在＝**问运行时**，不猜路径（本机模型树是 junction 指
    D:\\AIWorkflow\\models\\comfyui\\*，从没挂过 E:\\Models\\ComfyUI）。
    返回 (能跑?, 给人看的一句话)。"""
    try:
        with urllib.request.urlopen(base + "/object_info/UNETLoader", timeout=15) as r:
            d = json.loads(r.read().decode("utf-8"))
        opts = ((d.get("UNETLoader") or {}).get("input", {}).get("required", {}) or {}).get("unet_name")
        names = opts[0] if (isinstance(opts, list) and opts and isinstance(opts[0], list)) else (opts or [])
        if MODEL in list(names):
            return True, "UNETLoader 枚举里有 %s ⇒ 放行" % MODEL
        return False, "UNETLoader 枚举里只有 %d 项、没有 %s（实测本机扫到的：%s）" % (
            len(list(names)), MODEL, ", ".join(str(x) for x in list(names)[:4]))
    except Exception as e:
        return False, "问不到 /object_info（8189 没在跑或不通）：%s" % e


# ⚠ 2026-10-19 第⑫条(b) 尾巴 · 停料守卫（用户裁『打包归档移出 tools\\』，但五条判据里这个没过：
# `E:\公共记忆\skills\cinematic-video-production\references\previz-control-referee.md` 第 24/35 行还把它
# 当技能步骤在用（含命令示例 `py -3.12 annotate_shot.py`）⇒ 文件留在原位不搬走，只拦执行）。
# 判据故意做成**活的**：哪天按 engine/comfy/_已退役_FLUX_20261019.md 的六步把 E:\Models\ComfyUI
# （权重整套约 27GB，本轮一个字节没动）挂进模型树并重启，这里自动放行，不用回来改代码。
_ok, _why = _flux_line_alive()
if not _ok:
    print("!! 已停料：本脚本走 FLUX 线，而这条线在 2026-10-19 被判退役。依据：%s" % _why)
    print("   技能文档（previz-control-referee.md）里的命令示例此刻跑不通——文档未被修改，也未被判定作废。")
    print("   要复活看 engine/comfy/_已退役_FLUX_20261019.md 的六步；要出图改走 Z-Image 腿。")
    sys.exit(78)   # EX_CONFIG：路封了，不是脚本自己崩了

SESSION = None


def _requests():
    global SESSION
    if SESSION is None:
        import requests
        SESSION = requests.Session()
        SESSION.trust_env = False
    return SESSION


def base_url():
    with open(CFG, encoding="utf-8") as f:
        return yaml.safe_load(f)["comfyui"]["base_url"].rstrip("/")


def graph(img_name, prompt, strength, w, h, seed, steps):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": MODEL, "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": CLIP1, "clip_name2": CLIP2, "type": "flux"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
        "5": {"class_type": "FluxGuidance", "inputs": {"guidance": 3.5, "conditioning": ["3", 0]}},
        "9": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "14": {"class_type": "LoadImage", "inputs": {"image": img_name}},
        "15": {"class_type": "CannyEdgePreprocessor", "inputs": {"image": ["14", 0], "low_threshold": 100, "high_threshold": 200, "resolution": 1024}},
        "16": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": CN}},
        "17": {"class_type": "FluxUnionControlNetMode", "inputs": {"control_net": ["16", 0], "mode": "0: canny / lineart"}},
        "18": {"class_type": "ControlNetApplyAdvanced", "inputs": {"positive": ["5", 0], "negative": ["4", 0], "control_net": ["17", 0], "image": ["15", 0], "strength": strength, "start_percent": 0.0, "end_percent": 1.0, "vae": ["9", 0]}},
        "6": {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": steps, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0, "model": ["1", 0], "positive": ["18", 0], "negative": ["4", 0], "latent_image": ["6", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["9", 0]}},
        "12": {"class_type": "SaveImage", "inputs": {"filename_prefix": "anno", "images": ["8", 0]}},
    }


def generate(base, src_path, prompt, strength, w, h, seed, steps):
    os.makedirs(INPUT_DIR, exist_ok=True)
    nm = f"anno_{os.path.basename(src_path)}"
    shutil.copy2(src_path, os.path.join(INPUT_DIR, nm))
    g = graph(nm, prompt, strength, w, h, seed, steps)
    r = _requests().post(base + "/prompt", json={"prompt": g}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"提交失败 {r.status_code}: {r.text[:200]}")
    pid = r.json()["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < 900:
        time.sleep(4)
        try:
            h = _requests().get(f"{base}/history/{pid}", timeout=15).json().get(pid)
        except Exception:
            continue
        if not h:
            continue
        if (h.get("status") or {}).get("status_str") == "error":
            raise RuntimeError(json.dumps(h["status"].get("messages", []), ensure_ascii=False)[:400])
        for node in (h.get("outputs") or {}).values():
            for im in node.get("images", []):
                p = os.path.join(OUT_DIR, im.get("subfolder", ""), im["filename"])
                if os.path.isfile(p):
                    return p
    raise RuntimeError("超时无输出")


def edge_coverage(ref_path, cand_path, tol=6, size=(1024, 576)):
    def _e(p):
        with open(p, "rb") as f:
            data = f.read()
        im = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
        im = cv2.resize(im, size, interpolation=cv2.INTER_AREA)
        return (cv2.Canny(im, 100, 200) > 0).astype(np.uint8)
    ref, cand = _e(ref_path), _e(cand_path)
    if ref.sum() < 50:
        return None  # 参考无边缘（全黑帧等），标记为不可测
    cd = cv2.dilate(cand, np.ones((2 * tol + 1, 2 * tol + 1), np.uint8))
    return float((ref & cd).sum() / ref.sum())


def skeleton_ratio(base, path):
    """DWPose 骨架占比（0=提不出人形）。需一次 ComfyUI 往返。"""
    os.makedirs(INPUT_DIR, exist_ok=True)
    nm = f"anno_skel_{os.path.basename(path)}"
    shutil.copy2(path, os.path.join(INPUT_DIR, nm))
    g = {
        "1": {"class_type": "LoadImage", "inputs": {"image": nm}},
        "2": {"class_type": "OpenposePreprocessor", "inputs": {"image": ["1", 0], "detect_hand": "enable", "detect_body": "enable", "detect_face": "enable", "resolution": 1024, "scale_stick_for_xinsr_cn": "disable"}},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": "anno_skel"}},
    }
    r = _requests().post(base + "/prompt", json={"prompt": g}, timeout=30)
    pid = r.json()["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < 600:
        time.sleep(3)
        try:
            h = _requests().get(f"{base}/history/{pid}", timeout=15).json().get(pid)
        except Exception:
            continue
        if not h:
            continue
        for node in (h.get("outputs") or {}).values():
            for im in node.get("images", []):
                p = os.path.join(OUT_DIR, im.get("subfolder", ""), im["filename"])
                if os.path.isfile(p):
                    with open(p, "rb") as f:
                        d = f.read()
                    a = cv2.imdecode(np.frombuffer(d, np.uint8), cv2.IMREAD_COLOR).astype(np.int16)
                    sat = a.max(2) - a.min(2)
                    val = a.max(2)
                    m = (sat > 40) & (val > 60)
                    return float(m.mean())
    raise RuntimeError("骨架闸超时")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", required=True, help="灰模关键帧通配，如 E:/.../shot04_v5/shot04_v5_0*.png")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True, help="标注产物输出目录")
    ap.add_argument("--threshold", type=float, default=0.30, help="边缘覆盖率低于此值标废片")
    ap.add_argument("--skeleton", action="store_true", help="加跑骨架闸（慢）")
    ap.add_argument("--strength", type=float, default=0.8)
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--w", type=int, default=1024)
    ap.add_argument("--h", type=int, default=576)
    a = ap.parse_args()

    frames = sorted(glob.glob(a.frames))
    if not frames:
        print("没匹配到帧:", a.frames); sys.exit(2)
    os.makedirs(a.out, exist_ok=True)
    base = base_url()

    rows, panels = [], []
    for i, src in enumerate(frames):
        fid = os.path.splitext(os.path.basename(src))[0].split("_")[-1]
        t0 = time.time()
        try:
            out = generate(base, src, a.prompt, a.strength, a.w, a.h, a.seed, a.steps)
            cov = edge_coverage(src, out)
            skel = skeleton_ratio(base, out) if a.skeleton else None
        except Exception as e:
            print(f"[f{fid}] 失败: {e}")
            cov, skel, out = None, None, None
        if cov is None:
            verdict = "不可测(参考无边缘)"
        elif cov < a.threshold:
            verdict = "废片"
        else:
            verdict = "通过"
        rows.append({"frame": fid, "edge_cov": cov, "skeleton": skel,
                     "verdict": verdict, "output": out})
        flag = "🔴" if verdict in ("废片", "不可测") else "🟢"
        print(f"[{fid}] {flag} 覆盖率={None if cov is None else round(cov*100,1)}% "
              f"骨架={None if skel is None else round(skel*100,3)}%  → {verdict}  ({time.time()-t0:.0f}s)")

        # contact sheet 面板：灰模帧 | 出图（废片红框）
        src_im = Image.open(src).convert("RGB").resize((512, 288))
        if out and os.path.isfile(out):
            out_im = Image.open(out).convert("RGB").resize((512, 288))
        else:
            out_im = Image.new("RGB", (512, 288), (40, 40, 40))
        pair = Image.new("RGB", (1024, 288))
        pair.paste(src_im, (0, 0)); pair.paste(out_im, (512, 0))
        if verdict in ("废片", "不可测"):
            d = ImageDraw.Draw(pair)
            d.rectangle([512, 0, 1023, 287], outline=(220, 40, 40), width=6)
        panels.append(pair)

    csv_path = os.path.join(a.out, "annotations.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["frame", "edge_cov", "skeleton", "verdict", "output"])
        w.writeheader(); w.writerows(rows)
    sheet = Image.new("RGB", (1024, 288 * len(panels)))
    for i, p in enumerate(panels):
        sheet.paste(p, (0, i * 288))
    sheet_path = os.path.join(a.out, "contact_sheet.png")
    sheet.save(sheet_path)

    n_rej = sum(1 for r in rows if r["verdict"] in ("废片", "不可测"))
    print(f"\n[标注] {len(rows)} 帧，废片/不可测 {n_rej} 帧。")
    print(f"  CSV: {csv_path}")
    print(f"  拼图: {sheet_path}")


if __name__ == "__main__":
    main()
