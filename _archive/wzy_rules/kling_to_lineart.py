# -*- coding: utf-8 -*-
"""可灵转线稿：把君仪/混混/长枪（裹布+裸）的参考图转成纯黑线稿（白底、无颜色、无阴影）。"""
import re, sys, time, json, subprocess
from pathlib import Path

REF = Path(r'E:/创作/武昭君仪/首帧图/可灵参考素材')
GUN_REF = Path(r'D:/AIWorkflow/tmp/wzy/kling_out/gun_view1.png')
OUT = Path(r'E:/创作/武昭君仪/首帧图/线稿素材')
OUT.mkdir(parents=True, exist_ok=True)
KLING_POSIX = '/c/Users/若水/.workbuddy-ai/binaries/node/versions/22.22.2-3/kling'
BASH = r'C:\Users\若水\.workbuddy-ai\binaries\PortableGit\versions\1.2.0\bin\bash.exe'

# (name, ref_path_or_None, prompt, use_text_to_image)
TASKS = [
    ('jy_line_front', REF/'jy_正面.png', 'convert this character photo into a clean black ink line drawing on pure white background, manga sketch style, no color, no shading, no gradient, no grayscale fill — only clean black outlines defining the character silhouette from the FRONT view, hair ornaments, robe folds and body proportions; face rendered as simple minimal oval with two dots for eyes and a thin line for mouth, do NOT draw detailed facial features; ultra clean lines, manga inking quality', False),
    ('jy_line_side', REF/'jy_侧面.png', 'convert this character photo into a clean black ink line drawing on pure white background, manga sketch style, no color, no shading, no gradient, no grayscale fill — only clean black outlines defining the character silhouette from the SIDE view (right side profile), hair bun profile, robe folds and body proportions; face rendered as simple minimal oval profile with a single dot for the visible eye and a tiny line for mouth/nose, do NOT draw detailed facial features; ultra clean lines, manga inking quality', False),
    ('jy_line_back', REF/'jy_背面.png', 'convert this character photo into a clean black ink line drawing on pure white background, manga sketch style, no color, no shading, no gradient, no grayscale fill — only clean black outlines defining the character silhouette from the BACK view, hair bun from behind, robe folds and body proportions; do NOT show the face at all (back of head only); ultra clean lines, manga inking quality', False),
    ('hh_line_front', REF/'hh_正面.png', 'convert this character photo into a clean black ink line drawing on pure white background, manga sketch style, no color, no shading, no gradient, no grayscale fill — only clean black outlines defining the bald head, muscular upper body, dirty tank top, mechanical right arm with pistons and joints, belt, baggy pants and boots from the FRONT view; face rendered as simple minimal oval with two dots for eyes and a thin line for mouth, do NOT draw detailed facial features or tattoos; ultra clean lines, manga inking quality', False),
    ('hh_line_side', REF/'hh_侧面.png', 'convert this character photo into a clean black ink line drawing on pure white background, manga sketch style, no color, no shading, no gradient, no grayscale fill — only clean black outlines defining the bald head profile, muscular upper body profile, dirty tank top, mechanical right arm profile with pistons and joints, belt, baggy pants and boots from the SIDE view (right side profile); face rendered as simple minimal oval profile with a single dot for the visible eye and a tiny line for mouth/nose, do NOT draw detailed facial features or tattoos; ultra clean lines, manga inking quality', False),
    ('hh_line_back', REF/'hh_背面.png', 'convert this character photo into a clean black ink line drawing on pure white background, manga sketch style, no color, no shading, no gradient, no grayscale fill — only clean black outlines defining the bald head from behind, muscular upper body, dirty tank top back, mechanical right arm back view with pistons and joints, belt, baggy pants and boots from the BACK view; do NOT show the face at all (back of head only); ultra clean lines, manga inking quality', False),
    ('qiang_wrapped', GUN_REF, 'convert this prop photo into a clean black ink line drawing on pure white background, manga sketch style, no color, no shading, no gradient, no grayscale fill — only clean black outlines defining the long spear shaft wrapped ENTIRELY in white cloth strips with crisscross binding pattern covering 100 percent of the shaft from spearhead to butt cap, pointed metal spearhead visible at left end, blunt butt cap at right end, the entire weapon shown horizontally in the frame, ultra clean lines, manga inking quality', False),
]

def run(cmd, timeout=120):
    parts = []
    i = 0
    while i < len(cmd):
        a = str(cmd[i])
        if a.startswith('--') and i + 1 < len(cmd) and not str(cmd[i + 1]).startswith('--'):
            val = str(cmd[i + 1])
            parts.append(a + ' "' + val + '"')
            i += 2
        else:
            parts.append('"' + a.replace('"', '') + '"')
            i += 1
    bash_cmd = KLING_POSIX + ' ' + ' '.join(parts)
    return subprocess.run([BASH, '-c', bash_cmd], capture_output=True, text=True,
                          encoding='utf8', errors='replace', timeout=timeout)

def submit(name, ref_path, prompt, use_text):
    if use_text:
        cmd = ['text_to_image', '--skill-name', 'kling-cli', '--skill-version', '0.2.0',
               '--model', 'kling-image-v3_0_omni', '--aspectRatio', '16:9', '--imageCount', '1',
               prompt]
    else:
        cmd = ['image_to_image', '--skill-name', 'kling-cli', '--skill-version', '0.2.0',
               '--model', 'kling-image-v3_0_omni', '--aspectRatio', '1:1', '--imageCount', '1',
               '--image', str(ref_path), prompt]
    r = run(cmd)
    combined = r.stdout + r.stderr
    m = re.search(r'"generation_id"\s*:\s*"([^"]+)"', combined)
    if not m:
        print(f'[{name}] 提交失败:', combined[-500:], flush=True)
        return None
    print(f'[{name}] 已提交 {m.group(1)}', flush=True)
    return m.group(1)

def poll_dl(gid, name):
    for i in range(40):
        time.sleep(15)
        r = run(['query_tasks', '--skill-name', 'kling-cli', '--skill-version', '0.2.0', gid])
        try:
            j = json.loads(r.stdout)
            b = j.get('body', {})
            if b.get('status') in ('COMPLETED', 'succeed'):
                ws = b.get('works', [])
                if ws:
                    u = ws[0].get('url') or ws[0].get('urlWithoutWatermark')
                    subprocess.run(['curl', '-sL', '-A', 'Mozilla/5.0', '-o',
                                    str(OUT / f'{name}.png'), u], check=True)
                    print(f'[{name}] 已下载', flush=True)
                    return True
                return False
            if b.get('status') in ('FAILED', 'CANCELLED'):
                print(f'[{name}] 任务失败 status={b.get("status")}', flush=True)
                return False
        except Exception as e:
            print(f'[{name}] 轮询异常 {e}', flush=True)
    print(f'[{name}] 轮询超时', flush=True)
    return False

if __name__ == '__main__':
    only = sys.argv[1:] or [t[0] for t in TASKS]
    for name, ref, prompt, use_text in TASKS:
        if name not in only: continue
        if not use_text and (ref is None or not ref.exists()):
            print(f'[{name}] 参考图不存在 {ref}'); continue
        gid = submit(name, ref, prompt, use_text)
        if gid:
            poll_dl(gid, name)