# -*- coding: utf-8 -*-
"""用"官方三段式"提示词试渲单镜（原样使用，不做任何改动）。

用法：python render_official.py P1B [--spatial]
"""
import json
import subprocess
import sys
from pathlib import Path

BASE = Path(r"E:/创作/武昭君仪/_H3实测/三阶打斗")
GEN = r"E:/teng/tgptgrok/outputs/wzhj_generate.py"
PR = Path(r"D:/AIWorkflow/ComfyUI_H3/prompts_官方三段式")
SEED = {"P1A": 4570, "P1B": 4520, "P1C": 4530, "P1D": 4540,
        "P2A": 4550, "P2B": 4560, "P2C": 4570, "P2D": 4580,
        "P3A": 4590, "P3B": 4600, "P3C": 4710, "P3D": 4720}


def run(sid, spatial=False):
    files = list(PR.glob("wuzhaojunyi_三阶%s_*.txt" % sid))
    assert len(files) == 1, (sid, files)
    ff = BASE / ("%s_first.png" % sid)
    assert ff.is_file(), "缺首帧 " + str(ff)
    tag = "官方" + ("sp" if spatial else "")
    batch = "单镜_%s%s" % (sid, tag)
    cfg = {
        "batch": batch,
        "run_id": "wzhj_%s_%s" % (sid.lower(), tag),
        "theme": "三阶 %s 官方三段式试渲" % sid,
        "workflow": ("comfy/h3_i2v_fl2va_triple_lora.json" if spatial
                     else "comfy/h3_i2v_fl2va_dual_lora.json"),
        "prompt_file": str(files[0]),
        "seed": SEED[sid],
        "prefix": "wzhj_%s_%s" % (sid.lower(), tag),
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
    out = (r.stdout or "") + (r.stderr or "")
    for ln in out.split("\n"):
        if "preflight" in ln or "RESULT" in ln or "提交" in ln or "完成" in ln:
            print(ln[:200])
    d = BASE / batch / "shots" / batch / "raw"
    mp4 = sorted(d.glob("*.mp4")) if d.is_dir() else []
    print("产物:", mp4[-1] if mp4 else "无")


if __name__ == "__main__":
    sid = [a for a in sys.argv[1:] if not a.startswith("--")][0]
    run(sid, "--spatial" in sys.argv)
