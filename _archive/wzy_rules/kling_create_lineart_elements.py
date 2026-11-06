# -*- coding: utf-8 -*-
"""用可灵线稿做主体库：
- 武君仪：cover=正面线稿，secondary=[侧、背]
- 混混：cover=正面线稿，secondary=[侧、背]
- 长枪：cover=qiang_wrapped，secondary=[qiang_bare]
"""
import re, sys, time, json, subprocess
from pathlib import Path

LINE = Path(r'E:/创作/武昭君仪/首帧图/线稿素材')
KLING_POSIX = '/c/Users/若水/.workbuddy-ai/binaries/node/versions/22.22.2-3/kling'
BASH = r'C:\Users\若水\.workbuddy-ai\binaries\PortableGit\versions\1.2.0\bin\bash.exe'

ELEMENTS = [
    ('武君仪线稿', '武昭君仪女主·线稿三视图版，正面+侧面+背面，藏青高领汉服长袍、银饰高髻、苗条身材、白色布裹长柄冷兵器，背身藏青蓝、衣摆有花枝暗纹', '角色',
     LINE/'jy_line_front.png', [LINE/'jy_line_side.png', LINE/'jy_line_back.png']),
    ('粗臂男线稿', '粗臂男混混·线稿三视图版，正面+侧面+背面，光头、肌肉男、灰色背心、深色工装裤、靴子、右臂机械义体（活塞+关节结构），腰间系布带挂零件', '角色',
     LINE/'hh_line_front.png', [LINE/'hh_line_side.png', LINE/'hh_line_back.png']),
    ('白麻布长枪', '中国传统长柄冷兵器长枪，钢制叶形双刃矛头、八角硬木杆、铜尾鐏；本图包括两态：裹满白麻布的待机态与解开布条裸出的战斗态', '道具',
     LINE/'qiang_wrapped.png', [LINE/'qiang_bare.png']),
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

def submit(name, desc, tag, cover, secondary):
    cmd = ['element_create', '--skill-name', 'kling-cli', '--skill-version', '0.2.0',
           '--name', name, '--description', desc, '--tag', tag,
           '--cover', str(cover)]
    for sec in secondary:
        cmd += ['--secondary', str(sec)]
    r = run(cmd)
    combined = r.stdout + r.stderr
    m = re.search(r'"id"\s*:\s*"([^"]+)"', combined)
    if not m:
        print(f'[{name}] 提交失败:', combined[-800:], flush=True)
        return None
    print(f'[{name}] 已创建 id={m.group(1)}', flush=True)
    return m.group(1)

if __name__ == '__main__':
    results = {}
    for name, desc, tag, cover, secondary in ELEMENTS:
        if not cover.exists():
            print(f'[{name}] cover不存在 {cover}'); continue
        if not all(s.exists() for s in secondary):
            print(f'[{name}] secondary缺失 {[s for s in secondary if not s.exists()]}'); continue
        eid = submit(name, desc, tag, cover, secondary)
        if eid:
            results[name] = eid
    print()
    print('=== 创建结果 ===')
    for k, v in results.items():
        print(f'{k} -> {v}')
    Path('D:/AIWorkflow/tmp/wzy/lineart_elements.json').write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding='utf8')
    print('\n已写 lineart_elements.json')