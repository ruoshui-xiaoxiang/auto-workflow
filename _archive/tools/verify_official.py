# -*- coding: utf-8 -*-
"""验证：三阶转换后的官方骨架版 P1B，5 seed 乱码率（预检保持开启）。

若本脚本能跑通 ⇒ 说明 G7 已接受官方骨架（不再要求十块）。
用法：python verify_official.py
"""
import json
import subprocess
import sys
from pathlib import Path

GEN = r'E:/teng/tgptgrok/outputs/wzhj_generate.py'
BASE = Path(r'E:/创作/武昭君仪/_H3实测/三阶打斗')
OUT = Path(r'D:/AIWorkflow/tmp/wzy')
PR = r'D:/AIWorkflow/ComfyUI_H3/prompts_H3官方骨架/wuzhaojunyi_三阶P1B.txt'
SEEDS = [4520, 4521, 4522, 4523, 4524]
KEYS = ['老子', '说话', '跟你']


def render():
    for seed in SEEDS:
        batch = 'OC_官方骨架_P1B_%d' % seed
        d = BASE.parent / batch / 'shots' / batch / 'raw'
        if d.is_dir() and list(d.glob('*.mp4')):
            print('跳过', batch)
            continue
        cfg = {
            'batch': batch, 'run_id': 'wzhj_oc%d' % seed,
            'theme': '官方骨架验证 seed%d' % seed,
            'workflow': 'comfy/h3_i2v_fl2va_dual_lora.json',
            'prompt_file': PR, 'seed': seed, 'prefix': 'wzhj_oc%d' % seed,
            'width': 736, 'height': 416, 'length': 124, 'duration': 5.17, 'steps': 8,
            'lora': 'minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors',
            'lora_strength': 1.0,
            'lora2': 'Bunny_weapon_combatV1.safetensors', 'lora2_strength': 0.5,
            'timeout': 5400, 'ref_images': [str(BASE / 'P1B_first.png')],
        }
        cp = OUT / ('cfg_%s.json' % batch)
        cp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
        r = subprocess.run([sys.executable, GEN, str(cp)], capture_output=True, text=True,
                           encoding='utf8', errors='replace', cwd=str(Path(GEN).parent))
        o = (r.stdout or '') + (r.stderr or '')
        flag = 'preflight通过' if '[preflight] 通过' in o else (
            'preflight拦截' if 'preflight' in o and 'ERROR' in o else '?')
        print('seed %d  %s' % (seed, flag))


def score():
    from faster_whisper import WhisperModel
    FF = r'D:/AIWorkflow/tools/ffmpeg.exe'
    m = WhisperModel('small', device='cpu', compute_type='int8')
    nbad = 0
    for seed in SEEDS:
        batch = 'OC_官方骨架_P1B_%d' % seed
        d = BASE.parent / batch / 'shots' / batch / 'raw'
        mp4 = sorted(d.glob('*.mp4')) if d.is_dir() else []
        if not mp4:
            print('seed %d 缺产物' % seed)
            continue
        w = str(OUT / ('_oc%d.wav' % seed))
        subprocess.run([FF, '-y', '-v', 'error', '-i', str(mp4[-1]), '-vn',
                        '-ac', '1', '-ar', '16000', w], check=True)
        segs = list(m.transcribe(w, language='zh')[0])
        bad = [s for s in segs if not any(k in s.text for k in KEYS)]
        if bad:
            nbad += 1
        print('seed %d  段数%d  乱码%d  %s' % (
            seed, len(segs), len(bad), ' / '.join(b.text for b in bad) or '干净'))
    print('\n汇总：官方骨架版 %d/%d 条出现乱码' % (nbad, len(SEEDS)))


if __name__ == '__main__':
    if 'render' in sys.argv:
        render()
    elif 'score' in sys.argv:
        score()
