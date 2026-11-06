# -*- coding: utf-8 -*-
"""两件 MJ LoRA 的硬件资源代价实测。

为什么先 /free 再测：ComfyUI 会把加载过的模型缓着，不腾空的话第二臂读到的是
"上一件还没退"的叠加值，峰值全是假的。

采两路：
  · 显存 = nvidia-smi memory.used（**不用 ComfyUI /system_stats 的 vram_free，那是缓存旧账**）
  · 驻留 = ComfyUI python 进程的 WorkingSet64（权重进 RAM 的量都记在这）
每臂报：峰值显存／峰值驻留／出图秒数／与不挂 LoRA 的差。
"""
import json
import os
import subprocess
import threading
import time
import urllib.request

HOST = "http://127.0.0.1:8189"
TOOLS = r"D:\AIWorkflow\tools"
TPL = os.path.join(r"D:\AIWorkflow\engine\comfy", "z_image_turbo_api.json")
OUT = r"D:\AIWorkflow\tmp\Z-Image_MJ资源实测_20261004"
PY = subprocess.list2cmdline([__import__("sys").executable])
PROMPT = "一名穿月白襦裙的女子侧身立于青石长廊下，远处云雾山谷，竖幅构图"
ARMS = [
    ("A 不挂", None),
    ("B Luneva R128", "ZIT_Midjourney_Luneva_Cinematic_v1_r128.safetensors"),
    ("C MJ_V1 R32", "midj-z-1.safetensors"),
    ("D 像素 R32", "pixel_art_style_z_image_turbo.safetensors"),
]
COMFY_PID = None


def comfy_pid():
    """找 ComfyUI 的 python 进程 PID（靠 8189 端口的持有者）。"""
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                         encoding="gbk", errors="replace").stdout
    for line in out.splitlines():
        if ":8189" in line and "LISTENING" in line:
            return int(line.split()[-1])
    return None


def sample_loop(stop, vram, rss):
    pid = comfy_pid()
    while not stop.is_set():
        try:
            o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                                "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
            vram.append(int(float(o.splitlines()[0])) * 2**20)
        except Exception:
            pass
        if pid:
            try:
                o = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "(Get-Process -Id %d).WorkingSet64" % pid],
                    capture_output=True, text=True, timeout=8).stdout.strip()
                rss.append(int(float(o)))
            except Exception:
                pass
        time.sleep(0.35)


def free_models():
    req = urllib.request.Request(HOST + "/free", method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        urllib.request.urlopen(req, json.dumps(
            {"unload_models": True, "free_memory": True}).encode(), timeout=60)
    except Exception as e:
        print("  /free 失败：", e)


def run_arm(tag, lora):
    os.makedirs(OUT, exist_ok=True)
    free_models()
    time.sleep(3)
    cmd = [__import__("sys").executable, os.path.join(TOOLS, "comfy_run.py"),
           "--workflow", TPL, "--set", "PROMPT=" + PROMPT,
           "--set", "W=768", "--set", "H=1344", "--set", "STEPS=8",
           "--seed", "20261004", "--n", "1", "--out", OUT, "--prefix", "res_" + tag[:1]]
    if lora:
        cmd += ["--lora", "%s:1.0" % lora]
    vram, rss, stop = [], [], threading.Event()
    th = threading.Thread(target=sample_loop, args=(stop, vram, rss), daemon=True)
    th.start()
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    dt = time.time() - t0
    stop.set()
    th.join(timeout=3)
    ok = os.path.exists(os.path.join(OUT, "res_%s_001_00001_.png" % tag[:1]))
    return {"tag": tag, "lora": lora, "sec": round(dt, 1),
            "peak_vram": max(vram) if vram else 0, "peak_rss": max(rss) if rss else 0,
            "n_v": len(vram), "n_r": len(rss), "ok": ok,
            "err": "" if ok else (p.stdout or "")[-200:] + (p.stderr or "")[-200:]}


def main():
    global COMFY_PID
    COMFY_PID = comfy_pid()
    print("ComfyUI PID =", COMFY_PID)
    rows = [run_arm(t, l) for t, l in ARMS]
    base = rows[0]
    print("\n%-16s %-9s %-12s %-12s %-9s %s" % ("臂", "秒/张", "峰值显存", "峰值驻留", "Δ显存", "Δ驻留"))
    for r in rows:
        print("%-16s %-9.1f %-12s %-12s %-9s %s   (采样 %d/%d)"
              % (r["tag"], r["sec"], "%.2f GB" % (r["peak_vram"] / 2**30),
                 "%.2f GB" % (r["peak_rss"] / 2**30),
                 "%+.2f GB" % ((r["peak_vram"] - base["peak_vram"]) / 2**30),
                 "%+.2f GB" % ((r["peak_rss"] - base["peak_rss"]) / 2**30),
                 r["n_v"], r["n_r"]))
        if not r["ok"]:
            print("   🔴 没出图：", r["err"][:200])
    with io_open(os.path.join(OUT, "资源实测.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    return 0


def io_open(*a, **k):
    import io
    return io.open(*a, **k)


if __name__ == "__main__":
    import sys
    sys.exit(main())
