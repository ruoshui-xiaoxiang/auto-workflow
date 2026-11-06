# -*- coding: utf-8 -*-
"""第一章 → 万相 3.0 提示词生成器。
复用 h3_shots.py 的切片/台词机制，按万相官方公式输出：
[总体描述] + [分镜N(起-止秒):主体+场景+运动+美学控制] + [台词:xx说:"..."] + [音效] + [风格] + [负向清单]
输出: wan_ch1_prompts.json（23 镜：id/style/secs/prompt/first_frame）
"""
import json, os, sys, re, importlib.util
from pathlib import Path

WZY = r'D:\AIWorkflow\tmp\wzy'
spec = importlib.util.spec_from_file_location('h3_shots', os.path.join(WZY, 'h3_shots.py'))
h3 = importlib.util.module_from_spec(spec)
# 截断 __main__：只取定义部分（SHOTS/SPK/SPEAKERS/BOUND/BASE_CN/ANCIENT_CN/load_ch1/build）
src = open(os.path.join(WZY, 'h3_shots.py'), encoding='utf8').read()
src = src.split("if __name__")[0]
exec(compile(src, 'h3_shots_head.py', 'exec'), h3.__dict__)

lines = h3.load_ch1()
h3.build(lines)
SHOTS = h3.SHOTS
SPK = h3.SPK
jobs = json.load(open(os.path.join(WZY, 'h3', 'jobs.json'), encoding='utf8'))
secs = {j['id']: j['secs'] for j in jobs}
BASE_CN, ANCIENT_CN = h3.BASE_CN, h3.ANCIENT_CN

def wan_prompt(s):
    n = secs.get(s['id'], s.get('act', 10))
    style = BASE_CN if s['style'] == 'cyb' else ANCIENT_CN
    # R17：按信息量拆时间戳分镜——begin/main/end 各一段，按文本长度比例分配时长
    segs = [(s.get('begin', ''), 1), (s.get('main', ''), 1), (s.get('end', ''), 1)]
    segs = [(t.strip(), w) for t, w in segs if t.strip()]
    total_w = sum(w for _, w in segs)
    t = 0
    seg_lines = []
    for i, (txt, w) in enumerate(segs):
        d = round(n * w / total_w)
        if i == len(segs) - 1:
            d = round(n) - t
        seg_lines.append('分镜%d(%d-%d秒)：%s' % (i + 1, t, t + d, txt))
        t += d
    lock = ('锁定：武君仪随身的兵器是**一杆长度与她身高相当的细长杆**，通体同一层白麻布紧贴杆身裹严、'
            '两端把布收细打结、完全封口——它是一根细长的杆，**绝不是刀、剑或任何带刃的武器**；'
            '全程形态、长度、裹布不变。')
    parts = [style, '\n'.join(seg_lines), lock,
             '美学控制：%s，镜头连续平滑、不跳切。' % s['cam']]
    if s.get('dlg'):
        dlg = '；'.join('%s说:"%s"' % (SPK[k][1], t) for k, t in s['dlg'])
        parts.append('台词：%s。' % dlg)
    parts.append('声音：%s。' % s['snd'])
    parts.append('无背景音乐。')
    parts.append('负向清单：画面无任何文字、字幕、水印、台标、可读招牌文字；'
                 '不卡通化、不二次元、不塑料感皮肤、不过曝。')
    return '\n'.join(parts)

out = []
for s in SHOTS:
    ff = Path(WZY, 'kf_out', '%s_first.png' % s['id'])
    out.append({
        'id': s['id'], 'style': s['style'], 'scene': s['scene'],
        'secs': secs.get(s['id'], s.get('act', 10)),
        'first_frame': str(ff) if ff.is_file() else None,
        'has_ff': ff.is_file(),
        'dlg_count': len(s.get('dlg', [])),
        'prompt': wan_prompt(s),
    })
json.dump(out, open(os.path.join(WZY, 'wan_ch1_prompts.json'), 'w', encoding='utf8'),
          ensure_ascii=False, indent=1)
print('生成 %d 镜提示词' % len(out))
print('有首帧的镜: %s' % [o['id'] for o in out if o['has_ff']])
print('缺首帧的镜: %s' % [o['id'] for o in out if not o['has_ff']])
print('总时长 %.1f 秒' % sum(o['secs'] for o in out))
print('\n===== H01 示例 =====\n' + out[0]['prompt'])
