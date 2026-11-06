# -*- coding: utf-8 -*-
"""生成「不挂 LoRA」的 fl2va 模板变体（精细 20 步档用），以及确认双 LoRA 模板的槽位数。

为什么必须做变体：模板里 LoraLoaderModelOnly 的 lora_name 是 __LORA__ 占位符，
传空字符串会被 ComfyUI 判成无效 LoRA 名 —— 唯一干净的办法是把 LoRA 节点从链路上摘掉：
UNETLoader(2) → MiniMaxLowVRAMAttention(4)，跳过 13。
"""
import json
from pathlib import Path

D = Path(r"D:\AIWorkflow\engine\comfy")
JOBS = [
    ("h3_i2v_fl2va_api.json", "h3_i2v_fl2va_nolora_api.json", "单首帧"),
    ("h3_i2v_fl2va_dual_api.json", "h3_i2v_fl2va_dual_nolora_api.json", "首尾帧两头夹"),
    # 10-24 用户裁定「三格都建」：可选首尾帧图与 Ref2VA 9/3/3/12 图各出一张不挂 LoRA 的变体，
    # 用来把 recipe_matrix 里 t2va×clean20／l2va×clean20／ref2va×clean20 三格从 need_graph 转 available。
    ("h3_keyframes_optional_api.json", "h3_keyframes_optional_nolora_api.json",
     "可选首尾帧（T2VA/I2VA/L2VA/FL2VA 一图四模式）"),
    ("h3_i2v_ref2va9_api.json", "h3_i2v_ref2va9_nolora_api.json",
     "Ref2VA 9图/3视频/3原声/3独立音频（动态槽）"),
]

for src_name, dst_name, label in JOBS:
    src, dst = D / src_name, D / dst_name
    wf = json.loads(src.read_text(encoding="utf-8"))
    if "13" not in wf:
        raise SystemExit(f"{src_name} 里没有 LoRA 节点 13，先人工核对再跑")
    if wf["4"]["inputs"]["model"] != ["13", 0]:
        raise SystemExit(f"{src_name} 的 4.model 不是接在 13 上（链路被人改过），停手")
    del wf["13"]
    wf["4"]["inputs"]["model"] = ["2", 0]
    meta = wf.get("_meta")
    if isinstance(meta, dict):
        # `_meta` 在提交前由 build_graph_video 剥离，不会进 ComfyUI；这里只是把"为什么是另一张图"写清
        meta["note"] = (str(meta.get("note") or "") +
                        "｜本文件是**同一张图的干净 20 步变体**：13 号 LoraLoaderModelOnly 已摘，"
                        "4.model 直接接 2 号 UNETLoader；传空 lora 不会被判无效 LoRA 名。"
                        "由 comfy/make_nolora_templates.py 生成，别手改。")
    dst.write_text(json.dumps(wf, ensure_ascii=False, indent=2), encoding="utf-8")
    refs = sorted({int(x) for x in __import__("re").findall(r"__REF(\d+)__", dst.read_text(encoding="utf-8"))})
    lora_left = "__LORA__" in dst.read_text(encoding="utf-8")
    print(f"{label}: {dst_name}  节点数 {len(wf)}  LoRA 节点已摘={not lora_left}  __REF 槽={refs}")

# 双 LoRA（打斗档）模板：只核对，不改
dl = D / "h3_i2v_fl2va_dual_lora.json"
if dl.is_file():
    t = dl.read_text(encoding="utf-8")
    import re
    print("dual_lora 模板: __REF 槽=", sorted({int(x) for x in re.findall(r"__REF(\d+)__", t)}),
          " LoRA 占位=", sorted(set(re.findall(r"__LORA2?__", t))))
else:
    print("dual_lora 模板不存在（fight8 档先别挂）")
