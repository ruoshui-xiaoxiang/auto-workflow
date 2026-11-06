#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""run_tp_bunny.py · 打戏定稿档 D：TwoPass 4+4 + turbo4 + Bunny@0.5

2026-10-09 用户目审确认（同 R3f/同 seed 四档对照）：
  A 单遍8 画质不够；B 二采无 Bunny 打击感差且雪花→碎玻璃；
  C 单遍+Bunny 打击好但画质不够；**D=本脚本 画质+打击最好**。

用法:
  py run_tp_bunny.py --image 首帧.jpg --prompt-file 提示词.txt \
      [--w 736 --h 416 --len 124 --seed 20261008 --out r3f_tp_bunny] [--strength 0.5]
"""
from __future__ import print_function
import argparse
import json
import shutil
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = "http://127.0.0.1:8189"
INPUT = Path(r"D:\AIWorkflow\ComfyUI_H3\ComfyUI\input")
OUTPUT = Path(r"D:\AIWorkflow\ComfyUI_H3\output")
TPL = Path(r"D:\AIWorkflow\engine\comfy\h3_two_pass_api.json")


def walk(v, rep):
    if isinstance(v, dict):
        return {k: walk(x, rep) for k, x in v.items()}
    if isinstance(v, list):
        return [walk(x, rep) for x in v]
    if isinstance(v, str) and v in rep:
        return rep[v]
    return v


def build_graph(image_name, prompt, w, h, length, seed, prefix, bunny_strength=0.5):
    tpl = json.loads(TPL.read_text(encoding="utf-8"))
    # 模板 node14 字段损坏，必须按 run_two_pass 同构重建
    tpl["14"] = {
        "class_type": "MiniMaxH3AudioConditioningT8",
        "inputs": {
            "clip": ["3", 0],
            "video_vae": ["1", 0],
            "audio_vae": ["2", 0],
            "width": ["13", 1],
            "height": ["13", 2],
            "first_frame": ["6", 0],
            "prompt": "__PROMPT__",
            "length": int(length),
            "task_type": "I2VA",
            "audio_mode": "native",
            "audio_denoise_strength": 1.0,
            "add_source_as_reference": False,
            "prompt_primary_audio_ordinal": 0,
            "strict_prompt_tags": True,
            "ref_image_size": "match",
            "reference_video_policy": "official_2_to_15s",
            "allow_above_reference_area": False,
        },
    }
    # 先改接再插 5b，避免 5b 自指（dependency_cycle）
    for k, v in tpl.items():
        if k == "5b":
            continue
        ins = v.get("inputs", {})
        for ik, iv in list(ins.items()):
            if isinstance(iv, list) and len(iv) == 2 and iv[0] == "5" and ik == "model":
                ins[ik] = ["5b", 0]
    tpl["5b"] = {
        "class_type": "LoraLoaderModelOnly",
        "inputs": {
            "model": ["5", 0],
            "lora_name": "Bunny_weapon_combatV1.safetensors",
            "strength_model": float(bunny_strength),
        },
    }
    rep = {
        "__REF1__": image_name,
        "__PROMPT__": prompt,
        "__W__": int(w),
        "__H__": int(h),
        "__LEN__": int(length),
        "__SEED__": int(seed),
        "__PREFIX__": prefix,
    }
    return walk(tpl, rep)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--w", type=int, default=736)
    ap.add_argument("--h", type=int, default=416)
    ap.add_argument("--len", dest="length", type=int, default=124)
    ap.add_argument("--seed", type=int, default=20261008)
    ap.add_argument("--out", default="tp_bunny")
    ap.add_argument("--strength", type=float, default=0.5)
    a = ap.parse_args()

    prompt = Path(a.prompt_file).read_text(encoding="utf-8").strip()
    ref = Path(a.image)
    dst = INPUT / f"tpb_{uuid.uuid4().hex[:8]}{ref.suffix}"
    shutil.copy2(ref, dst)
    graph = build_graph(dst.name, prompt, a.w, a.h, a.length, a.seed, a.out, a.strength)
    body = json.dumps({"prompt": graph}).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/prompt", data=body, headers={"Content-Type": "application/json"}
    )
    pre = set(p for p in OUTPUT.rglob("*") if p.is_file())
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            pid = json.loads(r.read())["prompt_id"]
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode("utf-8", "replace")[:1500])
        return 1
    print("prompt_id", pid, flush=True)
    t0 = time.time()
    while time.time() - t0 < 1200:
        time.sleep(15)
        try:
            with urllib.request.urlopen(BASE + "/history/%s" % pid, timeout=30) as r:
                hist = json.loads(r.read())
            if pid in hist:
                st = hist[pid].get("status", {})
                status = st.get("status_str") or st
                print("status", status, "elapsed", round(time.time() - t0, 1), flush=True)
                if status in ("success", "error", "failed"):
                    break
        except Exception:
            print("poll wait", flush=True)
    new = [p for p in OUTPUT.rglob("*") if p.is_file() and p not in pre]
    print("outputs", [str(p) for p in new])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
