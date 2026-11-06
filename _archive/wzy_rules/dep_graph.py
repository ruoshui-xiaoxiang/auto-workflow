# -*- coding: utf-8 -*-
"""按「模板路径」重扫依赖：yaml → comfy/*.json → 权重名。

上一版只搜权重名，yaml 里根本没有权重名 ⇒ 假干净。这一版建两级图：
  workflows/*.yaml 的 workflow/template 字段  →  comfy/*.json  →  该 json 点名的权重
再对每个权重给出：哪些流会因为它没了而断（且这些流是否还活着）。
"""
import json
import os
import re
import sys

import yaml

ENG = r"D:\AIWorkflow\engine"
WF_DIR = os.path.join(ENG, "workflows")
TPL_DIR = os.path.join(ENG, "comfy")

WEIGHT_KEYS = ("unet_name", "vae_name", "clip_name", "clip_name1", "clip_name2",
               "control_net_name", "style_model_name", "lora_name", "ckpt_name",
               "name")


def tpl_weights(fn):
    p = os.path.join(TPL_DIR, fn)
    if not os.path.exists(p):
        return None
    txt = open(p, encoding="utf-8").read()
    d = json.loads(txt)
    out = set()
    for node in d.values():
        for k, v in (node.get("inputs") or {}).items():
            if k in WEIGHT_KEYS and isinstance(v, str) and v.endswith(
                    (".safetensors", ".ckpt", ".pt", ".bin")):
                out.add(v)
    return out


def main():
    flows = {}
    for fn in sorted(os.listdir(WF_DIR)):
        if not fn.endswith((".yaml", ".yml")):
            continue
        try:
            d = yaml.safe_load(open(os.path.join(WF_DIR, fn), encoding="utf-8"))
        except Exception as e:
            print("  🔴 %s 解析失败：%s" % (fn, e))
            continue
        refs = set()
        for st in (d or {}).get("steps", []) or []:
            if not isinstance(st, dict):
                continue
            for key in ("workflow", "template"):
                v = st.get(key)
                if isinstance(v, str) and v.endswith(".json"):
                    refs.add(os.path.basename(v))
        flows[fn] = refs

    print("[A] 每条流引用哪些模板（只列引用到 flux* / draft_flux / refine 的）")
    flux_flows = {}
    for f, refs in sorted(flows.items()):
        bad = sorted(r for r in refs if "flux" in r.lower() or r == "refine_usdu_api.json")
        if bad:
            flux_flows[f] = bad
            print("   %-28s → %s" % (f, ", ".join(bad)))
    if not flux_flows:
        print("   （无）")

    print("\n[B] 每个 FLUX 侧权重被哪些模板点名，模板又被哪些流点名")
    for w in ("flux1-dev-fp8.safetensors", "flux1-dev-redux.safetensors",
              "flux-vae-bf16.safetensors", "t5xxl_fp8_e4m3fn.safetensors",
              "clip_l.safetensors"):
        tpls, fls = [], []
        for tf in sorted(os.listdir(TPL_DIR)):
            if not tf.endswith(".json"):
                continue
            ws = tpl_weights(tf) or set()
            if w in ws:
                tpls.append(tf)
                for f, refs in flows.items():
                    if tf in refs:
                        fls.append(f)
        print("   %-34s 模板 %2d 个 | 被流引用：%s"
              % (w, len(tpls), ", ".join(sorted(set(fls))) or "无流直接引用"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
