# -*- coding: utf-8 -*-
"""十块 vs 官方骨架：5 seed × 2 臂的乱码率对照。

臂 A＝十块（prompts/wuzhaojunyi_三阶P1B_试探.txt）
臂 B＝官方三段式骨架、删元信息块（prompts_官方三段式/...官方骨架无元信息.txt）
其余全同：首帧 P1B_first.png、dual LoRA(turbo+Bunny0.5)、8 步、124 帧。

渲染阶段需要临时关 preflight（B 版没有十块），try/finally 保证恢复。
用法：python ab_tenblock.py render   # 渲染缺失的
      python ab_tenblock.py score    # ASR 打分
"""
import io
import json
import subprocess
import sys
from pathlib import Path

ENG = Path(r'D:/AIWorkflow/engine/config.yaml')
GEN = r'E:/teng/tgptgrok/outputs/wzhj_generate.py'
BASE = Path(r'E:/创作/武昭君仪/_H3实测/三阶打斗')
OUT = Path(r'D:/AIWorkflow/tmp/wzy')
SEEDS = [4520, 4521, 4522, 4523, 4524]
ARMS = {
    # 臂 A 的十块稿 09-28 已从真源目录判废搬走（三阶现行真源＝prompts_H3官方骨架/，
    # 旧十块留在 prompts/ 会被旧 glob 误命中 ⇒ 见手册冲突表风险 23 与 C63）。
    # 这里改指**归档件**（sha256 已核，与当年跑 A/B 时逐字相同）⇒ 这条承重证据仍可复现，
    # 而不是悄悄变成"路径没了、以后谁也重跑不了"。
    'A': (r'E:/图像影音资源池/武昭君仪/_判废归档_20260928/prompts/wuzhaojunyi_三阶P1B_试探.txt',
          'wzhj_abA'),
    'B': (r'D:/AIWorkflow/ComfyUI_H3/prompts_官方三段式/wuzhaojunyi_三阶P1B_官方骨架无元信息.txt',
          'wzhj_abB'),
    'C': (r'D:/AIWorkflow/ComfyUI_H3/prompts_官方三段式/wuzhaojunyi_三阶P1B_仅去星号.txt',
          'wzhj_abC'),
}
KEYS = ['老子', '说话', '跟你']          # 唯一合法台词的关键词


def render():
    orig = ENG.read_text(encoding='utf8')
    assert '\npreflight: on' in orig
    ENG.write_text(orig.replace('\npreflight: on', '\npreflight: off'), encoding='utf8')
    print('preflight 临时关')
    try:
        for arm, (pf, prefix) in ARMS.items():
            for seed in SEEDS:
                batch = 'AB_%s_%d' % (arm, seed)
                d = BASE / batch / 'shots' / batch / 'raw'
                if d.is_dir() and list(d.glob('*.mp4')):
                    print('跳过', batch, '已有')
                    continue
                cfg = {
                    'batch': batch, 'run_id': '%s_%d' % (prefix, seed),
                    'theme': 'AB 十块vs官方 %s seed%d' % (arm, seed),
                    'workflow': 'comfy/h3_i2v_fl2va_dual_lora.json',
                    'prompt_file': pf, 'seed': seed, 'prefix': '%s%d' % (prefix, seed),
                    'width': 736, 'height': 416, 'length': 124, 'duration': 5.17, 'steps': 8,
                    'lora': 'minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors',
                    'lora_strength': 1.0,
                    'lora2': 'Bunny_weapon_combatV1.safetensors', 'lora2_strength': 0.5,
                    'timeout': 5400, 'ref_images': [str(BASE / 'P1B_first.png')],
                }
                cp = OUT / ('cfg_%s.json' % batch)
                cp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
                r = subprocess.run([sys.executable, GEN, str(cp)], capture_output=True,
                                   text=True, encoding='utf8', errors='replace',
                                   cwd=str(Path(GEN).parent))
                got = list(d.glob('*.mp4')) if d.is_dir() else []
                print('%-12s %s' % (batch, 'OK' if got else '失败 ' + (r.stdout or '')[-120:]))
    finally:
        ENG.write_text(orig, encoding='utf8')
        print('preflight 已恢复 on')


def score():
    from faster_whisper import WhisperModel
    FF = r'D:/AIWorkflow/tools/ffmpeg.exe'
    m = WhisperModel('small', device='cpu', compute_type='int8')
    rows = []
    for arm, (pf, prefix) in ARMS.items():
        for seed in SEEDS:
            batch = 'AB_%s_%d' % (arm, seed)
            d = BASE.parent / batch / 'shots' / batch / 'raw'
            mp4 = sorted(d.glob('*.mp4')) if d.is_dir() else []
            if not mp4:
                rows.append((arm, seed, None, None, '缺产物'))
                continue
            w = str(OUT / ('_ab_%s_%d.wav' % (arm, seed)))
            subprocess.run([FF, '-y', '-v', 'error', '-i', str(mp4[-1]), '-vn',
                            '-ac', '1', '-ar', '16000', w], check=True)
            segs = list(m.transcribe(w, language='zh')[0])
            bad = [s for s in segs if not any(k in s.text for k in KEYS)]
            ok = any(any(k in s.text for k in KEYS) for s in segs)
            rows.append((arm, seed, len(segs), len(bad),
                         ('乱码%.1fs: ' % sum(b.end - b.start for b in bad) +
                          ' / '.join(b.text for b in bad)) if bad else ('干净' + ('' if ok else ' ⚠台词没出现'))))
    print('\n臂 seed  段数 乱码段  情况')
    print('-' * 96)
    for arm, seed, n, nb, note in rows:
        print('%-2s %4d  %5s %5s  %s' % (arm, seed, n if n is not None else '-',
                                          nb if nb is not None else '-', note))
    print('\n汇总：')
    for arm in ARMS:
        rs = [r for r in rows if r[0] == arm and r[3] is not None]
        nbad = sum(1 for r in rs if r[3] > 0)
        print('  臂%s：%d/%d 条出现乱码，乱码段合计 %d' % (
            arm, nbad, len(rs), sum(r[3] for r in rs)))


if __name__ == '__main__':
    if 'render' in sys.argv:
        render()
    elif 'score' in sys.argv:
        score()
    else:
        print(__doc__)
