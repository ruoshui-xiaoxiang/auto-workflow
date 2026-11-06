# -*- coding: utf-8 -*-
"""合成 flux_cn_redux_api.json：ControlNet 锁构图 + Redux 锁造型 双锚。

⚠ 2026-10-19 第⑫条(b) 停料：这条 FLUX 线已退役（底模从没挂进 ComfyUI 模型树；权重整套在
E:\\Models\\ComfyUI，判据与复活步骤见 官方路径.json 的 deprecated 与
`_已退役_FLUX_20261019.md`）。本脚本的输入已是路障桩，所以在这里就地拦下——
**它原本是会把桩覆盖成一个坏模板的**（读进来加几个节点再 dump 回同名文件）。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_src = os.path.join(HERE, "flux_controlnet_lineart_api.json")
_txt = open(_src, encoding="utf-8", errors="replace").read()
if "OFFICIAL-PATH-TOMBSTONE" in _txt:
    print("!! 已停料：%s 是退役桩，不是模板（2026-10-19 第⑫条(b)）。" % os.path.basename(_src))
    print("   正身模板在 backups/_治理_20261019/归档件/FLUX线退役_20261019/；"
          "要复活 FLUX 先看 engine/comfy/_已退役_FLUX_20261019.md 的六步。")
    sys.exit(78)   # EX_CONFIG：路封了，不是脚本自己崩了
base = json.loads(_txt)

# Redux 链（编号 20+ 避免冲突）
base["20"] = {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": "sigclip_vision_patch14_384.safetensors"}}
base["21"] = {"class_type": "LoadImage", "inputs": {"image": "__REF__"}}
base["22"] = {"class_type": "StyleModelLoader", "inputs": {"style_model_name": "flux1-redux-dev.safetensors"}}
base["23"] = {"class_type": "CLIPVisionEncode", "inputs": {"clip_vision": ["20", 0], "image": ["21", 0], "crop": "none"}}
# 文本 → Redux → ControlNet → Guidance → 采样
base["3"]["inputs"] = {"text": "__PROMPT__", "clip": ["2", 0]}
base["24"] = {"class_type": "StyleModelApply", "inputs": {
    "conditioning": ["3", 0], "style_model": ["22", 0], "clip_vision_output": ["23", 0],
    "strength": "__REDUX_STRENGTH__", "strength_type": "multiply"}}
base["5"]["inputs"] = {"guidance": 3.5, "conditioning": ["24", 0]}
base["18"]["inputs"]["positive"] = ["5", 0]

out = os.path.join(HERE, "flux_cn_redux_api.json")
json.dump(base, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("ok ->", out)
