# -*- coding: utf-8 -*-
"""单镜试渲通用器：同首帧/同seed/可选 triple，用来逐镜验证提示词改动。

用法：python render_one.py P1B 4520 [--spatial]
"""
import json
import subprocess
import sys
from pathlib import Path

BASE = Path(r"E:/创作/武昭君仪/_H3实测/三阶打斗")
GEN = r"E:/teng/tgptgrok/outputs/wzhj_generate.py"
PR = Path(r"D:/AIWorkflow/ComfyUI_H3/prompts")

SEED = {"P1A": 4570, "P1B": 4520, "P1C": 4530, "P1D": 4540,
        "P2A": 4550, "P2B": 4560, "P2C": 4570, "P2D": 4580,
        "P3A": 4590, "P3B": 4600, "P3C": 4710, "P3D": 4720}


def run(sid, seed=None, spatial=False, tag=""):
    seed = seed or SEED[sid]
    files = list(PR.glob("wuzhaojunyi_三阶%s_*.txt" % sid))
    assert len(files) == 1, (sid, files)
    ff = BASE / ("%s_first.png" % sid)
    assert ff.is_file(), "缺首帧 " + str(ff)
    batch = "单镜_%s%s%s" % (sid, tag, "_spatial" if spatial else "")
    cfg = {
        "batch": batch,
        "run_id": "wzhj_%s%s%s" % (sid.lower(), tag.lower(), "sp" if spatial else ""),
        "theme": "三阶 %s 单镜试渲%s" % (sid, "（triple+spatial）" if spatial else ""),
        "workflow": ("comfy/h3_i2v_fl2va_triple_lora.json" if spatial
                     else "comfy/h3_i2v_fl2va_dual_lora.json"),
        "prompt_file": str(files[0]),
        "seed": seed,
        "prefix": "wzhj_%s%s%s" % (sid.lower(), tag.lower(), "sp" if spatial else ""),
        "width": 736, "height": 416, "length": 124, "duration": 5.17,
        "steps": 8,
        "lora": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
        "lora_strength": 1.0,
        "lora2": "Bunny_weapon_combatV1.safetensors",
        "lora2_strength": 0.5,
        "timeout": 5400,
        "ref_images": [str(ff)],
    }
    if spatial:
        cfg["lora3"] = "wushu_spatial_physics_clean_3000_pruned.safetensors"
        cfg["lora3_strength"] = 0.3
    cp = Path(r"D:/AIWorkflow/tmp/wzy") / ("cfg_%s.json" % batch)
    cp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    r = subprocess.run([sys.executable, GEN, str(cp)], capture_output=True, text=True,
                       encoding="utf8", errors="replace", cwd=str(Path(GEN).parent))
    print((r.stdout or "")[-400:])
    print((r.stderr or "")[-300:])
    d = BASE / batch / "shots" / batch / "raw"
    mp4 = list(d.glob("*.mp4")) if d.is_dir() else []
    print("产物:", mp4[0] if mp4 else "无")


if __name__ == "__main__":
    argv = sys.argv[1:]
    tag = ""
    if "--tag" in argv:
        i = argv.index("--tag")
        tag = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    args = [a for a in argv if not a.startswith("--")]
    run(args[0], int(args[1]) if len(args) > 1 else None, "--spatial" in sys.argv, tag)
