# -*- coding: utf-8 -*-
"""对照实验：P2C 同首帧/同prompt/同seed，dual(Bunny) vs triple(Bunny+spatial-physics)。

目的：验证"格挡反击抽射流畅有打斗感"与"12镜链打斗感弱"的根因是否＝缺 spatial-physics LoRA。
单变量：只换 workflow（dual→triple）+ 加 lora3。其余逐字相同。
"""
import json
import subprocess
import sys
from pathlib import Path

PY = sys.executable
GEN = r"E:/teng/tgptgrok/outputs/wzhj_generate.py"
BASE = Path(r"E:/创作/武昭君仪/_H3实测/三阶打斗")
FF = BASE / "P2C_first.png"

CFG = {
    "batch": "对照_spatial_P2C",
    "run_id": "wzhj_p2c_spatial",
    "theme": "对照 P2C + spatial-physics",
    "workflow": "comfy/h3_i2v_fl2va_triple_lora.json",
    "prompt_file": r"D:/AIWorkflow/ComfyUI_H3/prompts/wuzhaojunyi_三阶P2C_棍扫.txt",
    "seed": 4570,
    "prefix": "wzhj_p2csp",
    "width": 736, "height": 416, "length": 124, "duration": 5.17,
    "steps": 8,
    "lora": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
    "lora_strength": 1.0,
    "lora2": "Bunny_weapon_combatV1.safetensors",
    "lora2_strength": 0.5,
    "lora3": "wushu_spatial_physics_clean_3000_pruned.safetensors",
    "lora3_strength": 0.3,
    "timeout": 5400,
    "ref_images": [str(FF)],
}

if __name__ == "__main__":
    cp = BASE / "cfg_spatial_P2C.json"
    cp.write_text(json.dumps(CFG, ensure_ascii=False, indent=2), encoding="utf-8")
    r = subprocess.run([PY, GEN, str(cp)], capture_output=True, text=True,
                       encoding="utf8", errors="replace", cwd=str(Path(GEN).parent))
    print((r.stdout or "")[-1500:])
    print((r.stderr or "")[-500:])
