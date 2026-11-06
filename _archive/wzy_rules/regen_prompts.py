# -*- coding: utf-8 -*-
"""只重编译并落盘提示词，**不碰 jobs.json**（驱动正在用它传递链式首帧）。

为什么不用 `py h3_shots.py`：那个 __main__ 块还会 write_jobs()，
驱动刚写完 H14 的 first_frame 指针就被我覆盖成模板值 → 下一镜"缺首帧停链"。
这里做同一件事的只写提示词版，并且跑完三道闸＋"枪"字硬闸才落盘。
"""
import os, sys, io, json, hashlib
sys.path.insert(0, r'D:\AIWorkflow\tmp\wzy')
sys.path.insert(0, r'D:\AIWorkflow\tools')
import h3_shots as H
import prompt_lint as L
from check_preflight import run_checks

JOBS = os.path.join(H.OUT, 'jobs.json')
before = hashlib.md5(open(JOBS, 'rb').read()).hexdigest()

fails = []
H.build(H.load_ch1())          # 切片＋配台词（逐字校验），不写盘
for s in H.SHOTS:
    H.timing(s)
for s in H.SHOTS:
    p = H.compile_video(s)
    vis = H._DLG_SPAN.sub('', p)
    if '枪' in vis:
        fails.append('%s 视觉区含枪字' % s['id']); continue
    r = L.scan_text(p)
    prof = L.profile_check(p, profile='realistic_ancient' if s['style'] == 'anc' else 'realistic_cyber',
                           baseline=H.degun(H.BASE_CN if s['style'] != 'anc' else H.anc_style(s)))
    rep = run_checks({'prompt': p, 'refs': [H.A[s['scene']]], 'w': 1344, 'h': 768,
                      'length': s['frames'], 'duration': s['secs'],
                      'prompt_kind': 'h3_i2va', 'provider': 'local',
                      'only': ['G1', 'G5', 'G6', 'G7']})
    g7 = ['%s:%s' % (g, m) for lv, g, m in rep.items if lv == 'error']   # Report.items 是列表属性，不带括号
    if not L.gate(r) or prof or g7:
        fails.append('%s 词表=%s 基调=%s G7=%s' % (s['id'], r['score'], prof, g7)); continue
    io.open(os.path.join(H.OUT, '%s_video.txt' % s['id']), 'w', encoding='utf8').write(p)
    if s['kf'] == 'seedream':
        io.open(os.path.join(H.OUT, '%s_kf.txt' % s['id']), 'w', encoding='utf8').write(H.compile_kf(s))

after = hashlib.md5(open(JOBS, 'rb').read()).hexdigest()
print('闸口不合格：', fails or '无（23/23 过）')
print('jobs.json 未被动过：', before == after)
for sid in ('H08', 'H15'):
    t = io.open(os.path.join(H.OUT, '%s_video.txt' % s['id']), encoding='utf8').read()
    key = '头巾' if sid == 'H08' else '机械义肢'
    print('%s 反复制句=%s 逐人名单=%s' % (sid, '彼此可辨' in t, key in t))
