# -*- coding: utf-8 -*-
"""《逐玉》247-289s 整段复刻：串行跑 8 段 ref2va（参考视频 + 锚点图），完成后自动按原序拼接。

用法: py -3.12 run_segments.py [起始段号]
  seg02 已在外部跑，本脚本会先等它的产物出现再继续。
"""
import os, subprocess, sys, time

H3 = r"D:\AIWorkflow\ComfyUI_H3"
OUT = os.path.join(H3, "output")
REFDIR = r"E:\图像影音资源池\无音_镜1镜2_对照\无音_复刻参考片段\整段_逐玉"
MALE = r"E:\图像影音资源池\无音_镜1镜2_对照\无音_复刻参考片段\原创角色\char_male_orig.png"
WUYIN = r"E:\创作\无音项目\图\定妆\wuyin_anchor_role.png"
STYLE = r"E:\创作\无音项目\图\画风参考\用户选定_鞠婧祎古装.jpg"
LORA = "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"

# (段名, 参考视频文件名, 角色组合, 生成帧数=17n+5 对齐值)
SEGS = [
    ("seg01", "ref_01_247.12-254.24.mp4", "wu",   158),
    ("seg02", "ref_02_254.24-261.88.mp4", "male", 175),
    ("seg03", "ref_03_261.88-266.36.mp4", "both", 107),
    ("seg04", "ref_04_266.36-270.8.mp4",  "male", 107),
    ("seg05", "ref_05_270.8-275.08.mp4",  "wu",    90),
    ("seg06", "ref_06_275.08-278.12.mp4", "male",  73),
    ("seg07", "ref_07_278.12-282.96.mp4", "both", 107),
    ("seg08", "ref_08_282.96-289.04.mp4", "wu",   141),
]

ANCHORS = {
    "wu":   [WUYIN, STYLE],
    "male": [MALE, STYLE],
    "both": [WUYIN, MALE, STYLE],
}
PROMPT_FILE = {"seg02": "seg02_male.txt"}


def wait_for(out_name, timeout=2400):
    """等某个段的产物出现（外部已在跑的段用）"""
    dst = os.path.join(OUT, out_name + ".mp4")
    t0 = time.time()
    while time.time() - t0 < timeout:
        if os.path.exists(dst) and os.path.getsize(dst) > 50000:
            return True
        time.sleep(20)
    return False


def run_seg(name, ref_video, combo, length):
    dst = os.path.join(OUT, name + ".mp4")
    if os.path.exists(dst) and os.path.getsize(dst) > 50000:
        print(f"[skip] {name} 已存在", flush=True)
        return True
    prompt = PROMPT_FILE.get(name, name + ".txt")
    cmd = [sys.executable, os.path.join(H3, "run_h3.py"),
           "--ref-images", ",".join(ANCHORS[combo]),
           "--ref-videos", os.path.join(REFDIR, ref_video),
           "--prompt-file", os.path.join(H3, "prompts", prompt),
           "--w", "1024", "--h", "576", "--len", str(length), "--steps", "8",
           "--lora", LORA, "--out", name]
    t0 = time.time()
    print(f"[run] {name} combo={combo} len={length}", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=H3)
    ok = os.path.exists(dst) and os.path.getsize(dst) > 50000
    print(f"[{'OK' if ok else 'FAIL'}] {name} {time.time()-t0:.0f}s", flush=True)
    if not ok:
        print((r.stdout or "")[-600:], (r.stderr or "")[-600:], flush=True)
    return ok


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else None
    started = start is None
    for name, ref, combo, length in SEGS:
        if not started:
            if name == start:
                started = True
            else:
                continue
        if name == "seg02":
            # 外部已提交在跑，等它落盘
            print(f"[wait] 等 seg02（外部任务）…", flush=True)
            if wait_for(name):
                print("[OK] seg02 已就绪", flush=True)
                continue
            print("[warn] seg02 等待超时，改为自己跑", flush=True)
        run_seg(name, ref, combo, length)


if __name__ == "__main__":
    main()
