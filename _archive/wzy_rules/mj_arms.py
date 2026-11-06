# -*- coding: utf-8 -*-
"""MJ LoRA 四臂实测：同 seed、同提示词、一次只动"挂哪件 LoRA"这一根轴。

两条设计约定：
  1. 提示词**不含任何光影／电影感／质感词**——否则基线自己就带那味儿，会把 LoRA 的贡献盖住
     （上一轮 p3a 就是这么把增量压成 +0.22 的）。
  2. 阳性对照＝已知能生效的像素风 LoRA（带触发词），用来证明"这一轮链路本身没问题"。
     没有阳性对照的话，"MJ 没变化"就分不清是 LoRA 无效还是我挂错了。

跑完自动接检光（light_scopes.py）量对比档／饱和 R／冷暖分区——MJ 那套招牌长相
就是"高对比＋高饱和＋戏剧光"，这三根轴是能机械量的。
"""
import os
import subprocess
import sys

TOOLS = r"D:\AIWorkflow\tools"
TPL = os.path.join(r"D:\AIWorkflow\engine\comfy", "z_image_turbo_api.json")
OUT = r"D:\AIWorkflow\tmp\Z-Image_MJ实测_20261004"
LORAS = r"D:\Models\ComfyUI\loras"
PY = sys.executable

PROMPT = "一名穿月白襦裙的女子侧身立于青石长廊下，远处云雾山谷，竖幅构图"
W, H, STEPS, SEED = 768, 1344, 8, 20261004

ARMS = [
    ("A_不挂", None, None),
    ("B_Luneva", "ZIT_Midjourney_Luneva_Cinematic_v1_r128.safetensors", None),
    ("C_MJ_V1", "midj-z-1.safetensors", None),
    ("D_像素阳性", "pixel_art_style_z_image_turbo.safetensors", "Pixel art style. "),
]


def run(tag, lora, trigger):
    p = os.path.join(OUT, "%s_001_00001_.png" % tag)
    if os.path.exists(p):
        print("  已有，跳过", tag)
        return p
    cmd = [PY, os.path.join(TOOLS, "comfy_run.py"), "--workflow", TPL,
           "--set", "PROMPT=" + (trigger or "") + PROMPT,
           "--set", "W=%d" % W, "--set", "H=%d" % H, "--set", "STEPS=%d" % STEPS,
           "--seed", str(SEED), "--n", "1", "--out", OUT, "--prefix", tag]
    if lora:
        cmd += ["--lora", "%s:1.0" % lora]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = (r.stdout or "").strip().split("\n")[-2:]
    print("  %-14s %s" % (tag, " | ".join(tail)))
    return p if os.path.exists(p) else None


def main():
    os.makedirs(OUT, exist_ok=True)
    missing = [n for n, f, _ in ARMS if f and not os.path.exists(os.path.join(LORAS, f))]
    if missing:
        print("🔴 缺 LoRA 文件，先下完：", ", ".join(missing))
        return 2
    got = [run(t, f, tr) for t, f, tr in ARMS]
    got = [g for g in got if g]
    print("\n出图 %d 张，接着量检光" % len(got))
    if got:
        rep = os.path.join(OUT, "检光")
        # light_scopes 收 --in（目录或单张），PNG 是全摆幅 ⇒ 明写 full，别让 auto 猜
        r = subprocess.run([PY, os.path.join(TOOLS, "post", "light_scopes.py"),
                            "--in", OUT, "--out", rep, "--range", "full"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        print((r.stdout or "")[-3000:])
        if r.returncode:
            print("检光报错：", (r.stderr or "")[:600])
        else:
            print("检光报表落点：", rep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
