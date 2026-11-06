#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
controlnet_smoke.py — 出图侧 FLUX ControlNet 冒烟（previz 路线 B 的 pose/canny 两条腿）

背景：FLUX ControlNet Union Pro fp8 + comfyui_controlnet_aux 预处理器早就装好了，
但管线里**一次都没接过**（0 个工作流用它）。本脚本把"灰模帧 → 结构控制 → FLUX 出图"
这条链打通，用来回答一个问题：**灰模锁不锁得住结构**。

两条腿都不需要额外下载：
  canny —— CannyEdgePreprocessor（纯 OpenCV）
  pose  —— OpenposePreprocessor（DWPose 权重已在 custom_nodes/comfyui_controlnet_aux/ckpts）
（depth 那条需要 depth_anything_v2 权重，本地没有，故未纳入本轮）

用法:
  py -3.12 controlnet_smoke.py --control canny --src 灰模帧.png
  py -3.12 controlnet_smoke.py --control pose  --src 灰模帧.png --strength 0.7
"""

import os, sys, json, time, shutil, argparse, urllib.request

import yaml

CFG = r"D:\AIWorkflow\engine\config.yaml"
INPUT_DIR = r"D:\AIWorkflow\ComfyUI_H3\ComfyUI\input"
OUT_DIR = r"D:\AIWorkflow\ComfyUI_H3\output"

MODEL = "flux1-dev-fp8.safetensors"
CLIP1, CLIP2 = "clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors"
VAE = "flux-vae-bf16.safetensors"
CN = "FLUX.1-dev-ControlNet-Union-Pro-fp8.safetensors"


def _flux_line_alive(base="http://127.0.0.1:8189"):
    """FLUX 线还在不在＝**问运行时**，不猜路径（本机模型树是 junction 指
    D:\\AIWorkflow\\models\\comfyui\\*，从没挂过 E:\\Models\\ComfyUI）。"""
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


# ⚠ 2026-10-19 第⑫条(b) 尾巴 · 停料守卫。五条判据里这个没过：`E:\本地工作流规范手册\08_Qoder记忆_现行约定\
# reference-minimax-h3-local.md:179` 把「出图侧 ControlNet 已打通（tools\controlnet_smoke.py）：canny 48s /
# pose 68s」当**现行约定的证据**在引用 ⇒ 文件留在原位不搬走，只拦执行。
# ⚠ 那句"已打通"打通的是 FLUX 这条腿；本机另一条腿是 Z-Image×ControlNet（结论不同，别混用）。
# 判据是活的：哪天把 E:\Models\ComfyUI 挂进模型树并重启 8189，这里自动放行，不用回来改代码。
_ok, _why = _flux_line_alive()
if not _ok:
    print("!! 已停料：本脚本走 FLUX 线，而这条线在 2026-10-19 被判退役。依据：%s" % _why)
    print("   它曾是『出图侧 ControlNet 已打通』的证据脚本（现行约定记忆:179）——那条说法现在只对 FLUX 腿失效，")
    print("   Z-Image 腿另有结论（记忆 reference-zimage-lora-cn）。要复活看 engine/comfy/_已退役_FLUX_20261019.md 六步。")
    sys.exit(78)   # EX_CONFIG：路封了，不是脚本自己崩了

DEFAULT_PROMPT = (
    "沈无音在古风庭院的石凳上垂眸读书：21 岁清冷温婉、及腰黑长直发、头顶半盘发髻插银质步摇、"
    "两侧蓝花钗、额间朱砂莲花钿、月白与鸦青渐变交领汉服、腰间淡蓝织带挂着米色小布袋；"
    "青石地面、一张石桌一个石凳、旁有古树，竹影与洒落的光斑，背景轻微虚化。"
    "电影级写实 CG，浅景深，柔和高原天光透过树叶洒下斑驳光点。"
    "只采用输入图的构图、人物姿态与机位结构，画风按本描述渲染；"
    "不得继承灰色模型材质、不得出现灰色塑料感、不得保留占位方块。8K 细节。"
)


def base_url():
    with open(CFG, encoding="utf-8") as f:
        return yaml.safe_load(f)["comfyui"]["base_url"].rstrip("/")


def graph(control, img_name, prompt, strength, w, h, seed, steps):
    pre = {"class_type": "CannyEdgePreprocessor",
           "inputs": {"image": ["14", 0], "low_threshold": 100,
                      "high_threshold": 200, "resolution": 1024}}
    mode = "0: canny / lineart"
    if control == "pose":
        pre = {"class_type": "OpenposePreprocessor",
               "inputs": {"image": ["14", 0], "detect_hand": "enable",
                          "detect_body": "enable", "detect_face": "enable",
                          "resolution": 1024, "scale_stick_for_xinsr_cn": "disable"}}
        mode = "4: openpose"
    if control == "depth":
        pre = {"class_type": "DepthAnythingV2Preprocessor",
               "inputs": {"image": ["14", 0],
                          "ckpt_name": "depth_anything_v2_vitl.pth",
                          "resolution": 1024}}
        mode = "2: depth"
    if control == "none":
        # 无控制基线：纯文生图，只留 FluxGuidance，不接 ControlNet
        return {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": MODEL, "weight_dtype": "default"}},
            "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": CLIP1, "clip_name2": CLIP2, "type": "flux"}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
            "5": {"class_type": "FluxGuidance", "inputs": {"guidance": 3.5, "conditioning": ["3", 0]}},
            "9": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
            "6": {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
            "7": {"class_type": "KSampler",
                  "inputs": {"seed": seed, "steps": steps, "cfg": 1.0, "sampler_name": "euler",
                             "scheduler": "simple", "denoise": 1.0, "model": ["1", 0],
                             "positive": ["5", 0], "negative": ["4", 0], "latent_image": ["6", 0]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["9", 0]}},
            "12": {"class_type": "SaveImage", "inputs": {"filename_prefix": "cn_none", "images": ["8", 0]}},
        }
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": MODEL, "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": CLIP1, "clip_name2": CLIP2, "type": "flux"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
        "5": {"class_type": "FluxGuidance", "inputs": {"guidance": 3.5, "conditioning": ["3", 0]}},
        "9": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "14": {"class_type": "LoadImage", "inputs": {"image": img_name}},
        "15": pre,
        "16": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": CN}},
        "17": {"class_type": "FluxUnionControlNetMode", "inputs": {"control_net": ["16", 0], "mode": mode}},
        "18": {"class_type": "ControlNetApplyAdvanced",
               "inputs": {"positive": ["5", 0], "negative": ["4", 0], "control_net": ["17", 0],
                          "image": ["15", 0], "strength": strength,
                          "start_percent": 0.0, "end_percent": 1.0,
                          "vae": ["9", 0]}},   # FLUX ControlNet Union 必须给 vae，否则 KSampler 报错
        "6": {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "7": {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": steps, "cfg": 1.0, "sampler_name": "euler",
                         "scheduler": "simple", "denoise": 1.0, "model": ["1", 0],
                         "positive": ["18", 0], "negative": ["4", 0], "latent_image": ["6", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["9", 0]}},
        "12": {"class_type": "SaveImage", "inputs": {"filename_prefix": f"cn_{control}", "images": ["8", 0]}},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", choices=["canny", "pose", "depth", "none"], required=True)
    ap.add_argument("--src", required=True, help="灰模帧（本机路径）")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--strength", type=float, default=0.8)
    ap.add_argument("--w", type=int, default=1024)
    ap.add_argument("--h", type=int, default=576)
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    if not os.path.isfile(a.src):
        print(f"源图不存在: {a.src}")
        sys.exit(2)
    dst_name = f"cn_src_{a.control}.png"
    os.makedirs(INPUT_DIR, exist_ok=True)
    shutil.copy2(a.src, os.path.join(INPUT_DIR, dst_name))
    print(f"[1/3] 已把灰模帧放入 input: {dst_name}")

    g = graph(a.control, dst_name, a.prompt, a.strength, a.w, a.h, a.seed, a.steps)
    base = base_url()
    req = urllib.request.Request(
        f"{base}/prompt",
        data=json.dumps({"prompt": g, "client_id": "cn_smoke"}).encode(),
        headers={"Content-Type": "application/json"})
    pid = json.loads(urllib.request.urlopen(req, timeout=30).read())["prompt_id"]
    print(f"[2/3] 已提交 prompt_id={pid}，等待出图…")

    t0 = time.time()
    imgs = []
    while time.time() - t0 < 900:
        time.sleep(4)
        try:
            h = json.loads(urllib.request.urlopen(f"{base}/history/{pid}", timeout=15).read())
        except Exception:
            continue
        if pid in h:
            outs = h[pid].get("outputs") or {}
            for node in outs.values():
                imgs += node.get("images") or []
            break
    if not imgs:
        print("[!] 超时或没有输出"); sys.exit(3)

    got = []
    for im in imgs:
        p = os.path.join(OUT_DIR, im.get("subfolder", ""), im["filename"])
        if os.path.isfile(p):
            got.append(p)
    print(f"[3/3] 出图完成（{time.time()-t0:.0f}s）：")
    for p in got:
        print("   ", p)
    if not got:
        print("[!] history 里有记录但文件没找到"); sys.exit(4)


if __name__ == "__main__":
    main()
