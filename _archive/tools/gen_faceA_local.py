# -*- coding: utf-8 -*-
r"""脸A · 本地生成器（FLUX + Redux）——「出图先走本地」的第一块落地。

背景（2026-09-16 用户定）：出图出视频默认先走本地，云端降为补充。理由是可控、不计次，
以及**训练分布＝使用分布**（LoRA 将来在本地 FLUX 上用，训练集就该是本地出的）。

关键设计：
  1. 身份靠 **Redux 参考图**（基准脸方形裁切），不靠文字描述长相——
     挂了参考图还在文字里描写五官，两者会打架，这是踩过的坑。
  2. 提示词走**英文**：FLUX 的 T5 对中文支持差。
  3. 变化维度：机位 / 表情 / 光照 / 背景 / 发型 / 取景。

两种模式：
  phase1  6 张（3 机位 × 2 光照）——验证 Redux 到底能不能扛住这张脸
  phase2  54 张（6 机位 × L9 正交表）——正式铺训练集

用法：
  py gen_faceA_local.py phase1
  py gen_faceA_local.py phase2
"""
import argparse
import os
import subprocess
import sys

COMFY_RUN = r"D:\AIWorkflow\tools\comfy_run.py"
WORKFLOW = r"D:\AIWorkflow\engine\comfy\flux_redux_ref_api.json"
PY = r"D:\AIWorkflow\ComfyUI_H3\python_embeded\python.exe"

# ⚠ 2026-10-19 第⑫条(b) 停料：FLUX 线已退役（底模从没挂进 ComfyUI 模型树 ⇒ UNETLoader 枚举里没有
# flux；权重整套其实在 E:\Models\ComfyUI，判据见 官方路径.json 的 deprecated）。
# 原 WORKFLOW 现在是路障桩。在这里拦下，别让它一路跑到 ComfyUI 才炸个看不懂的枚举错。
# 复活六步见 engine/comfy/_已退役_FLUX_20261019.md；正身模板在 backups/_治理_20261019/归档件/FLUX线退役_20261019/。
if "OFFICIAL-PATH-TOMBSTONE" in open(WORKFLOW, encoding="utf-8", errors="replace").read():
    print("!! 已停料：%s 是退役桩，本脚本跑不了（2026-10-19 第⑫条(b) 用户裁『改判＋退役处理』）。"
          % os.path.basename(WORKFLOW))
    print("   要出图请走 Z-Image 线（engine/comfy/z_style_*_api.json）或即梦参考图（run.py 的 image 任务）。")
    sys.exit(78)   # EX_CONFIG：路封了，不是脚本自己崩了

REFS = r"D:\AIWorkflow\tmp\faceA_redux_refs"
REF_DEFAULT = os.path.join(REFS, "A1_脸·文字靶·正面_ref.png")

# 输出落位（AGENTS.md 保存规范：批次交付进资源池；这里先落 tmp 供质检）
OUT1 = r"D:\AIWorkflow\tmp\faceA_phase1_redux"
OUT2 = r"D:\AIWorkflow\tmp\faceA_phase2_train"

ANGLE = {
    "front": "front view, facing the camera directly at eye level",
    "up":    "slightly low angle, chin raised a little",
    "q34l":  "three-quarter view turned to her left",
    "q34r":  "three-quarter view turned to her right",
    "sideL": "full profile facing left",
    "sideR": "full profile facing right",
}
EXPR = {
    "calm":  "calm neutral expression, not smiling",
    "smile": "a very faint closed-mouth smile, eyes still cool",
    "frown": "faintly knitted brows, cool and distant",
}
LIGHT = {
    "soft": "soft frontal studio lighting, gentle tonal transition",
    "rim":  "side-back rim light, one cheek falling into shadow, hair edges glowing",
    "top":  "top light with warm ambient bounce from below",
}
BG = {
    "grey":  "plain light grey studio background",
    "dark":  "dark charcoal studio background",
    "out":   "blurred outdoor background with soft bokeh",
}
HAIR = {
    "loose": "long hair worn loose",
    "back":  "hair tied back in a low ponytail",
    "half":  "half-up hair with a small simple ornament",
}
FRAME = {
    "face":  "close-up portrait, framed to the chin",
    "chest": "head and shoulders, framed to the chest",
    "waist": "half body, framed to the waist",
}

TAIL = ("photorealistic CG render, fine and translucent skin texture, sharp specular highlights, "
        "cinematic lighting, shallow depth of field, vertical 9:16 composition, "
        "no text, no watermark, no glasses, no glasses on her face")

W, H, STEPS, GUID = 832, 1216, 20, 3.5
REDUX_STRENGTH = 0.9

# L9 正交表：五个维度各 3 水平，每个水平恰好出现 3 次
L9 = [
    ("calm",  "soft", "grey", "loose", "face"),
    ("calm",  "rim",  "dark", "back",  "chest"),
    ("calm",  "top",  "out",  "half",  "waist"),
    ("smile", "soft", "dark", "half",  "waist"),
    ("smile", "rim",  "out",  "loose", "face"),
    ("smile", "top",  "grey", "back",  "chest"),
    ("frown", "soft", "out",  "back",  "chest"),
    ("frown", "rim",  "grey", "half",  "waist"),
    ("frown", "top",  "dark", "loose", "face"),
]


def build_prompt(angle, expr, light, bg, hair, frame, extra=""):
    parts = [ANGLE[angle], EXPR[expr], LIGHT[light], BG[bg], HAIR[hair], FRAME[frame]]
    s = "Same young woman as the reference image as the only identity source. " + ", ".join(parts) + "."
    if extra:
        s += " " + extra
    return s + " " + TAIL


def run(prompt, out_dir, prefix, ref, n=1):
    cmd = [PY, COMFY_RUN, "--workflow", WORKFLOW,
           "--ref", ref,
           "--set", "PROMPT=" + prompt,
           "--set", "W=%d" % W, "--set", "H=%d" % H,
           "--set", "STEPS=%d" % STEPS, "--set", "GUIDANCE=%s" % GUID,
           "--set", "REDUX_STRENGTH=%s" % REDUX_STRENGTH,
           "--n", str(n), "--out", out_dir, "--prefix", prefix]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", shell=False)
    tail = (r.stdout or "")[-400:]
    print(tail)
    if r.returncode != 0:
        print("  (stderr) %s" % (r.stderr or "")[-300:])


def phase1():
    os.makedirs(OUT1, exist_ok=True)
    # 3 机位 × 2 光照，其余固定，纯看 Redux 扛不扛得住
    jobs = [
        ("P1_front_soft",  "front", "calm", "soft", "grey", "loose", "face"),
        ("P2_front_rim",   "front", "calm", "rim",  "grey", "loose", "face"),
        ("P3_q34l_soft",   "q34l",  "calm", "soft", "grey", "loose", "chest"),
        ("P4_q34l_rim",    "q34l",  "calm", "rim",  "grey", "loose", "chest"),
        ("P5_sideL_soft",  "sideL", "calm", "soft", "grey", "loose", "chest"),
        ("P6_sideL_rim",   "sideL", "calm", "rim",  "grey", "loose", "chest"),
    ]
    for name, *dims in jobs:
        if os.path.exists(os.path.join(OUT1, name + "_001.png")):
            print("%s 已有，跳过" % name)
            continue
        print("\n=== %s ===" % name)
        run(build_prompt(*dims), OUT1, name, REF_DEFAULT, n=1)


def phase2():
    os.makedirs(OUT2, exist_ok=True)
    angles = ["front", "up", "q34l", "q34r", "sideL", "sideR"]
    n = 0
    for ang in angles:
        for i, (ex, li, bg, ha, fr) in enumerate(L9):
            n += 1
            code = "T%02d" % n
            name = "%s_%s_%s" % (code, ang, i + 1)
            if os.path.exists(os.path.join(OUT2, name + "_001.png")):
                print("%s 已有，跳过" % code)
                continue
            print("\n=== %s %s ===" % (code, ang))
            run(build_prompt(ang, ex, li, bg, ha, fr), OUT2, name, REF_DEFAULT, n=1)
    print("\n共 %d 张" % n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["phase1", "phase2"])
    a = ap.parse_args()
    if a.phase == "phase1":
        phase1()
    else:
        phase2()
    return 0


if __name__ == "__main__":
    sys.exit(main())
