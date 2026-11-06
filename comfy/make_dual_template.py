# -*- coding: utf-8 -*-
"""生成 fl2va「首帧+尾帧两头夹」模板变体（不改现有 h3_i2v_fl2va_api.json）。

依据：MiniMaxH3ImageToVideo 原生带可选 last_frame 输入（首帧=plain stretch 拉伸，
尾帧=frame_count-1 居中裁切），引擎的 video 任务按 __REFi__ 逐个替换，
所以只要多接一个 LoadImage 到 last_frame，就能用 ref_images 的第 2 张喂尾帧。
"""
import json
from pathlib import Path

SRC = Path(r"D:\AIWorkflow\engine\comfy\h3_i2v_fl2va_api.json")
DST = Path(r"D:\AIWorkflow\engine\comfy\h3_i2v_fl2va_dual_api.json")

wf = json.loads(SRC.read_text(encoding="utf-8"))

if "21" in wf or "last_frame" in wf["7"]["inputs"]:
    raise SystemExit("模板已改过，停手：先人工核对再跑")

wf["21"] = {"class_type": "LoadImage", "inputs": {"image": "__REF2__"}}
wf["7"]["inputs"]["last_frame"] = ["21", 0]

DST.write_text(json.dumps(wf, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote", DST)
print("slots:", sorted({k for k in DST.read_text(encoding="utf-8").split() if k.startswith("__REF")}))
print("node7 inputs:", list(wf["7"]["inputs"].keys()))
