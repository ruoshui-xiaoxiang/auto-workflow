# -*- coding: utf-8 -*-
"""删 FLUX.1 权重前的三道预检。

1. 三条编辑流的 yaml 能解析，且 workflow 指向的模板文件在盘上存在。
2. 新模板里每个 __X__ 占位符，都在引擎 build_graph_control 的填充表里
   （漏一个就会把字面量 __X__ 提交给 ComfyUI）。
3. 依赖账：还有多少模板/工作流点名 flux1-dev-fp8.safetensors（删完就断的那些）。
"""
import json
import os
import re
import sys

import yaml

ENG = r"D:\AIWorkflow\engine"
COMFY = r"D:\AIWorkflow\ComfyUI_H3\ComfyUI\models"
WF_DIR = os.path.join(ENG, "workflows")
TPL_DIR = os.path.join(ENG, "comfy")
TASKS = os.path.join(ENG, "tasks.py")

FLOWS = ["image_i2i.yaml", "image_inpaint.yaml", "image_outpaint.yaml"]
NEW_TPLS = ["z_image_i2i_api.json", "z_image_inpaint_api.json",
            "z_image_outpaint_api.json", "z_image_turbo_api.json"]


def rep_keys():
    src = open(TASKS, encoding="utf-8").read()
    m = re.search(r"def build_graph_control.*?\n    rep = \{(.*?)\n    \}", src, re.S)
    if not m:
        raise SystemExit("找不到 build_graph_control 的 rep 表")
    keys = set(re.findall(r'"(__[A-Z0-9_]+__)"', m.group(1)))
    keys |= {"__CTRL_IMAGE__", "__CTRL_STRENGTH__"}   # 由 extra_rep 注入
    return keys


def placeholders(path):
    txt = open(path, encoding="utf-8").read()
    return set(re.findall(r"__[A-Z0-9_]+__", txt))


def main():
    rc = 0
    keys = rep_keys()
    print("[1] 三条编辑流 yaml")
    for f in FLOWS:
        p = os.path.join(WF_DIR, f)
        d = yaml.safe_load(open(p, encoding="utf-8"))
        tpl = None
        for st in d.get("steps", []):
            if st.get("task") == "control":
                tpl = st.get("workflow")
        tp = os.path.join(ENG, tpl.replace("/", os.sep)) if tpl else None
        ok = bool(tp) and os.path.exists(tp)
        print("   %-20s control.workflow=%-34s 存在=%s  steps=%s  denoise=%s"
              % (f, tpl, ok, d["args"].get("steps"), d["args"].get("denoise")))
        rc |= 0 if ok else 1

    print("\n[2] 占位符覆盖（引擎 rep 表共 %d 键）" % len(keys))
    for t in NEW_TPLS:
        p = os.path.join(TPL_DIR, t)
        ph = placeholders(p)
        miss = ph - keys
        print("   %-28s 占位符 %-42s 缺=%s"
              % (t, ", ".join(sorted(ph)) or "（无）",
                 "无" if not miss else "🔴 " + ", ".join(sorted(miss))))
        rc |= 1 if miss else 0

    print("\n[3] FLUX.1 权重依赖账（flux1-dev-fp8.safetensors）")
    hit_tpl, hit_wf = [], []
    for root, bag in ((TPL_DIR, hit_tpl), (WF_DIR, hit_wf)):
        for fn in sorted(os.listdir(root)):
            if not fn.endswith((".json", ".yaml", ".yml")):
                continue
            if "flux1-dev-fp8" in open(os.path.join(root, fn), encoding="utf-8",
                                        errors="ignore").read():
                bag.append(fn)
    print("   engine/comfy 模板点名它：%s" % (", ".join(hit_tpl) or "无"))
    print("   engine/workflows 流点名它：%s" % (", ".join(hit_wf) or "无"))

    other = []
    for root, _ in ((TPL_DIR, None), (WF_DIR, None)):
        for fn in sorted(os.listdir(root)):
            if not fn.endswith((".json", ".yaml", ".yml")):
                continue
            txt = open(os.path.join(root, fn), encoding="utf-8", errors="ignore").read()
            for w in ("flux1-dev-redux", "flux1-depth", "flux1-canny",
                      "clip_l.safetensors", "t5xxl_fp8_e4m3fn", "flux-vae-bf16"):
                if w in txt:
                    other.append((fn, w))
    print("   仍点名其它 FLUX 侧件（本次不删，只登记）：")
    for fn, w in other:
        print("      %-40s → %s" % (fn, w))

    tgt = os.path.join(COMFY, "diffusion_models", "flux1-dev-fp8.safetensors")
    print("\n[4] 待删文件 %s  存在=%s  字节=%s"
          % (tgt, os.path.exists(tgt),
             os.path.getsize(tgt) if os.path.exists(tgt) else "-"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
