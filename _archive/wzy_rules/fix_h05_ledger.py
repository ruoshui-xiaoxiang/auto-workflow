# -*- coding: utf-8 -*-
"""把 H05 从误判的"判废/无产物"改回真实状态：渲染成功、自检已跑、路径为资源池批次目录。

为什么要单独写这个：驱动 03:30 前那版只在 ComfyUI output 找 mp4，引擎已把产物 relocate 走，
于是把一条 1648s 跑完的好片记成了失败，还顺手停了整批。账本必须反映事实，不然早上看到的是假故障。
"""
import os, sys, json, time
sys.path.insert(0, r'D:\AIWorkflow\tmp\wzy')
import run_batch as R

MP4 = r'E:\图像影音资源池\武昭君仪\批次\20260926_022703\video\xn_20260926_022703_00001_.mp4'
assert os.path.isfile(MP4)

jobs = {j['id']: j for j in json.load(open(os.path.join(R.H3, 'jobs.json'), encoding='utf8'))}
job = jobs['H05']
q = json.load(open(os.path.join(R.WZY, 'qc_video', 'H05.json'), encoding='utf8'))
led = R.load_ledger()

wall = 1648.4
v, bad = R.verdict(job, q)
# 113px 的脸，ArcFace 落在不可信区（本机经验：>189px 才谈得上保身份，300px 是启发式不是硬界）
# → 不能据此判"身份丢"，也不能说"身份对"。归到"机器判不了、必须人看"。
bad = [b for b in bad if not b.startswith('身份丢')]
if q.get('face_px', 0) and q['face_px'] < 190:
    bad.append('身份机器判不了(脸%dpx<190)' % q['face_px'])

led['H05'] = dict(
    verdict=v, mp4=MP4, wall=round(wall), spf=round(wall / job['frames'], 2),
    bad=bad,
    qc={k: q.get(k) for k in ('n', 'fps', 'secs', 'face_px', 'arc_min', 'dino_vs_base',
                              'dino_flag', 'flow_mean', 'audio', 'corner_edge_ratio', 'sheet')},
    ts=time.strftime('%F %T'), seed=job['seed'],
    note='03:35 纠正：02:54 记的"无产物"是驱动找错目录（产物已被 relocate），渲染本身成功。',
)
led.pop('H05_failed', None)
R.save_ledger(led)
print('H05 ->', v, bad, 'spf=%.2f' % (wall / job['frames']))
print('keys:', sorted(led.keys()))
